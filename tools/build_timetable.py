#!/usr/bin/env python3
"""Build data/sanyo-timetable.js: every Sanyo Shinkansen train running on one day, from JR West's timetable site
(timetable.jr-odekake.net).

How it works
  1. Read the station timetables (both directions) at the stations where most trains start or pass:
     Shin-Osaka, Okayama, Hiroshima and Hakata. Each departure links to a train page.
  2. Read each train page once: name and number, rolling stock, car count, destination, and every stop with times.
  3. Keep the stops on the Sanyo line (Shin-Osaka to Hakata) and write them out for the app.

A few short workings that never depart from one of those four stations (e.g. a Himeji to Okayama Kodama) are missed.

Usage:  python3 tools/build_timetable.py [--date YYYYMMDD] [--out data/sanyo-timetable.js] [--dump DIR]
The date defaults to today in Japan. --dump saves the raw pages, for debugging the parser.
"""
import argparse, datetime, html, json, os, re, sys, time, unicodedata, urllib.request
from html.parser import HTMLParser

BASE = 'https://timetable.jr-odekake.net'
# station timetable ids: <station><line 002 = Tokaido/Sanyo/Kyushu Shinkansen><direction 001/002>
STATION_PAGES = ['2815002001', '2815002002',   # Shin-Osaka
                 '3449002001', '3449002002',   # Okayama
                 '3863002001', '3863002002',   # Hiroshima
                 '4102002001', '4102002002']   # Hakata
SANYO = ['新大阪', '新神戸', '西明石', '姫路', '相生', '岡山', '新倉敷', '福山', '新尾道', '三原', '東広島', '広島',
         '新岩国', '徳山', '新山口', '厚狭', '新下関', '小倉', '博多']
OTHER = ['東京', '品川', '新横浜', '小田原', '熱海', '三島', '新富士', '静岡', '掛川', '浜松', '豊橋', '三河安城', '名古屋',
         '岐阜羽島', '米原', '京都', '新鳥栖', '久留米', '筑後船小屋', '新大牟田', '新玉名', '熊本', '新八代', '新水俣',
         '出水', '川内', '鹿児島中央', '博多南']
ALL = sorted(SANYO + OTHER, key=len, reverse=True)   # longest first, so 新大阪 never matches as 大阪 etc.
TYPES = {'のぞみ': 'nozomi', 'ひかり': 'hikari', 'こだま': 'kodama', 'みずほ': 'mizuho', 'さくら': 'sakura', 'つばめ': 'tsubame'}
UA = 'ShinkaViz timetable builder (+https://github.com/alexfry/ShinkaViz)'


def fetch(url, tries=4):
    for k in range(tries):
        try:
            req = urllib.request.Request(url, headers={'User-Agent': UA, 'Accept-Language': 'ja,en;q=0.5'})
            with urllib.request.urlopen(req, timeout=30) as r:
                return r.read().decode('utf-8', 'replace')
        except Exception as e:
            print(f'  retry {k + 1}/{tries} {url}: {e}', file=sys.stderr)
            time.sleep(3 * (k + 1))
    raise RuntimeError('failed: ' + url)


class Text(HTMLParser):
    """Visible text as lines; block-level tags and table cells start new lines."""
    BLOCK = {'p', 'div', 'li', 'tr', 'td', 'th', 'br', 'h1', 'h2', 'h3', 'h4', 'h5', 'dt', 'dd', 'table', 'section', 'ul', 'ol', 'span'}

    def __init__(self):
        super().__init__(); self.out = []; self.skip = 0

    def handle_starttag(self, t, a):
        if t in ('script', 'style', 'noscript'): self.skip += 1
        elif t in self.BLOCK: self.out.append('\n')

    def handle_endtag(self, t):
        if t in ('script', 'style', 'noscript'): self.skip = max(0, self.skip - 1)
        elif t in self.BLOCK: self.out.append('\n')

    def handle_data(self, d):
        if not self.skip: self.out.append(d)

    def lines(self):
        # NFKC folds full-width letters and digits (Ｎ７００系, ８両) to ASCII
        t = unicodedata.normalize('NFKC', ''.join(self.out))
        return [re.sub(r'\s+', ' ', l).strip() for l in t.split('\n') if l.strip()]


def text_lines(page):
    p = Text(); p.feed(page); return p.lines()


TIME = re.compile(r'(\d{1,2}):(\d{2})\s*(着|発)?')


def secs(h, m):
    h, m = int(h), int(m)
    if h < 4: h += 24                      # the site's day runs 04:00 to 03:59
    return h * 3600 + m * 60


def parse_train(page):
    L = text_lines(page)
    full = '\n'.join(L)
    m = re.search(r'(のぞみ|ひかり|こだま|みずほ|さくら|つばめ)\s*(\d+)\s*号', full)
    if not m: return None
    name, num = m.group(1), int(m.group(2))
    # rolling stock: prefer "<series>系 ... <n>両" (the formation line); a bare "<series>系" can also be a site banner
    stock = cars = None
    f = re.search(r'(N700S|N700A|N700|800|700|500)\s*系[^\n]{0,12}?(\d{1,2})\s*両', full)
    if f: stock, cars = f.group(1), int(f.group(2))
    else:
        for s in re.finditer(r'(N700S|N700A|N700|800|700|500)\s*系', full):
            ctx = full[max(0, s.start() - 30):s.end() + 30]
            if not re.search(r'ラスト|last|LAST|特設|サイト', ctx): stock = s.group(1); break
        c = re.search(r'(\d{1,2})\s*両', full)
        if c: cars = int(c.group(1))
    dest = None
    d = re.search(r'(' + '|'.join(ALL) + r')\s*行', full)
    if d: dest = d.group(1)
    # stops: a line that is (or starts with) a station name opens a stop; times until the next station belong to it
    stops, cur = [], None
    for ln in L:
        st = next((s for s in ALL if ln == s or ln.startswith(s + ' ') or ln.startswith(s + '駅')), None)
        if st and not re.search(r'行|方面|号', ln):
            cur = {'st': st, 'times': []}; stops.append(cur); ln = ln[len(st):]
        if cur is None: continue
        for t in TIME.finditer(ln):
            cur['times'].append((secs(t.group(1), t.group(2)), t.group(3)))
        if ln.strip() in ('着', '発') and cur['times'] and cur['times'][-1][1] is None:   # label in its own element
            cur['times'][-1] = (cur['times'][-1][0], ln.strip())
        if re.fullmatch(r'(レ|\|\||ㇾ|=|通過)', ln.strip()): cur['pass'] = True
    out = []
    stops = [s for s in stops if s['times'] and not s.get('pass')]
    for i, s in enumerate(stops):
        arr = dep = None
        for t, lab in s['times'][:2]:
            if lab == '着': arr = t
            elif lab == '発': dep = t
        un = [t for t, lab in s['times'][:2] if not lab]
        if arr is None and dep is None:
            if len(un) >= 2: arr, dep = un[0], un[1]
            elif un: arr = dep = un[0]
        elif arr is None and un: arr = un[0]
        elif dep is None and un: dep = un[0]
        if i == 0 and dep is not None and (arr is None or arr == dep): arr = None
        if i == len(stops) - 1 and arr is None: arr = dep
        out.append([s['st'], arr, dep])
    return {'name': name, 'type': TYPES[name], 'num': num, 'stock': stock, 'cars': cars, 'dest': dest, 'stops': out}


def main():
    ap = argparse.ArgumentParser()
    jst = datetime.datetime.utcnow() + datetime.timedelta(hours=9)
    ap.add_argument('--date', default=jst.strftime('%Y%m%d'))
    ap.add_argument('--out', default=os.path.join(os.path.dirname(__file__), '..', 'data', 'sanyo-timetable.js'))
    ap.add_argument('--dump', default=None)
    ap.add_argument('--min', type=int, default=150, help='refuse to write fewer trains than this')
    ap.add_argument('--delay', type=float, default=0.7)
    ap.add_argument('--show', type=int, default=0, help='print the text of the first N train pages (for checking the parser)')
    a = ap.parse_args()
    if a.dump: os.makedirs(a.dump, exist_ok=True)
    ids = {}
    for sp in STATION_PAGES:
        url = f'{BASE}/station-timetable/{sp}?date={a.date}'
        page = fetch(url); time.sleep(a.delay)
        if a.dump: open(os.path.join(a.dump, f'station-{sp}.html'), 'w').write(page)
        found = re.findall(r'train-timetable/(\d+)', page)
        for t in found: ids.setdefault(t, sp)
        print(f'{sp}: {len(set(found))} trains ({len(ids)} total)', flush=True)
    trains, bad = [], 0
    for n, tid in enumerate(sorted(ids)):
        page = fetch(f'{BASE}/train-timetable/{tid}?date={a.date}'); time.sleep(a.delay)
        if a.dump and n < 6: open(os.path.join(a.dump, f'train-{tid}.html'), 'w').write(page)
        if n < a.show: print(f'--- train page {tid} ---\n' + '\n'.join(text_lines(page)[:120]) + '\n---', flush=True)
        t = parse_train(page)
        if t: t['stops'] = [s for s in t['stops'] if s[0] in SANYO]
        if not t or len(t['stops']) < 2 or any(s[1] is None and s[2] is None for s in t['stops']):
            bad += 1; print(f'  skip {tid}: could not read', file=sys.stderr); continue
        a0, a1 = SANYO.index(t['stops'][0][0]), SANYO.index(t['stops'][-1][0])
        t['dir'] = 1 if a1 > a0 else -1
        t['id'] = tid
        trains.append(t)
        if n % 25 == 0: print(f'  {n + 1}/{len(ids)} {t["name"]}{t["num"]} {t["stock"]} {len(t["stops"])} stops', flush=True)
    trains.sort(key=lambda t: (t['stops'][0][2] or t['stops'][0][1] or 0))
    print(f'{len(trains)} trains, {bad} unreadable')
    if len(trains) < a.min:
        sys.exit(f'only {len(trains)} trains read (minimum {a.min}); not writing {a.out}')
    d = a.date
    doc = {'date': f'{d[:4]}-{d[4:6]}-{d[6:]}', 'generated': datetime.datetime.utcnow().strftime('%Y-%m-%dT%H:%MZ'),
           'source': 'JR West timetable (timetable.jr-odekake.net)', 'trains': trains}
    with open(a.out, 'w') as f:
        f.write('/* Sanyo Shinkansen timetable for one day, built by tools/build_timetable.py. stops: [station, arrival s, departure s] (seconds after midnight JST; after-midnight times run past 86400). */\n')
        f.write('window.SANYO_TT=' + json.dumps(doc, ensure_ascii=False, separators=(',', ':')) + ';\n')
    print('wrote', a.out)


if __name__ == '__main__':
    main()
