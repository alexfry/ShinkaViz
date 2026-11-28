#!/usr/bin/env python3
"""JR East Shinkansen trains for one day, from timetables.jreast.co.jp (Tohoku, Hokkaido, Akita, Yamagata, Joetsu, Hokuriku).

The site publishes a weekday and a weekend/holiday edition. Its "digital timetables" (timetable-v/NNN{d|u}{1|2}.html: d down,
u up, 1 weekday, 2 weekend/holiday) list every train on a line, each linking to a train page with its stops and a calendar of
the days it runs (bold). We read the tables for the day's edition, follow links to further tables, read each train page and
keep the trains whose calendar includes the date. Used by build_timetable.py; standard library only."""
import re, sys, os, time, datetime
from urllib.parse import urljoin
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from build_timetable import fetch, text_lines, secs, TYPES, NAMES, SERIES

BASE = 'https://timetables.jreast.co.jp/'
SEED = ['003', '004']          # Tohoku (with Hokkaido, Akita, Yamagata) and Joetsu/Hokuriku, from Tokyo's station page


def holiday(d):
    """Japanese public holiday (good enough for picking the timetable edition; the train calendars have the last word)."""
    y, m, day, wd = d.year, d.month, d.day, d.weekday()
    nth_mon = lambda mm, n: m == mm and wd == 0 and (day - 1) // 7 == n - 1
    spring = int(20.8431 + 0.242194 * (y - 1980) - (y - 1980) // 4)
    autumn = int(23.2488 + 0.242194 * (y - 1980) - (y - 1980) // 4)
    fixed = {(1, 1), (2, 11), (2, 23), (3, spring), (4, 29), (5, 3), (5, 4), (5, 5), (8, 11), (9, autumn), (11, 3), (11, 23)}
    if (m, day) in fixed or nth_mon(1, 2) or nth_mon(7, 3) or nth_mon(9, 3) or nth_mon(10, 2):
        return True
    if wd != 6:        # substitute holiday: the first non-holiday after a Sunday holiday
        p = d - datetime.timedelta(days=1)
        while holiday(p):
            if p.weekday() == 6: return True
            p -= datetime.timedelta(days=1)
    return False


def runs_on(page, date):
    """The train page's calendar marks running days in bold. True/False, or None when the calendar can't be read."""
    i, j = page.find('運行日'), page.find('時刻詳細')
    if i < 0 or j < i: return None
    cal = page[i:j]
    ym = f'{date.year}年{date.month}月'
    k = cal.find(ym)
    if k < 0: return None
    nxt = re.search(r'\d{4}年\d{1,2}月', cal[k + len(ym):])
    month = cal[k:k + len(ym) + (nxt.start() if nxt else len(cal))]
    cells = re.findall(r'<(td|th|li|span|div)([^>]*)>\s*(?:<(b|strong|span|em)([^>]*)>)?\s*(\d{1,2})\s*<', month)
    bold, seen = set(), set()
    for tag, attrs, inner, iattrs, dn in cells:
        dn = int(dn); seen.add(dn)
        sig = (attrs + ' ' + (inner or '') + ' ' + iattrs).lower()
        if inner in ('b', 'strong') or re.search(r'bold|\bon\b|run|active|unten|operat', sig):
            bold.add(dn)
    if not seen or not bold: return None
    return date.day in bold


def parse(page):
    L = text_lines(page)
    full = '\n'.join(L)
    m = re.search(r'(' + NAMES + r')\s*(\d+)\s*号', full)
    if not m: return None
    t = {'name': m.group(1), 'type': TYPES[m.group(1)], 'num': int(m.group(2)), 'stock': None, 'cars': None, 'dest': None, 'stops': []}
    f = re.search(r'設備(.*?)駅名', full, re.S)
    if f:
        s = re.search(SERIES + r'\s*系', f.group(1)); c = re.search(r'(\d{1,2})\s*両', f.group(1))
        t['stock'] = s.group(1) if s else None; t['cars'] = int(c.group(1)) if c else None
    try:
        a = next(i for i in range(len(L) - 2) if L[i] == '駅名' and L[i + 1] == '時刻')
    except StopIteration:
        return None
    cur = None
    for l in L[a + 3:]:
        if l.startswith('備考') or l.startswith('オンライン'): break
        tm = re.fullmatch(r'(\d{1,2}):(\d{2})\s*(着|発)', l)
        if tm:
            if cur is None: continue
            v = secs(int(tm.group(1)), int(tm.group(2)))
            cur[1 if tm.group(3) == '着' else 2] = v
        elif re.fullmatch(r'[\d\s・,-]+(番線)?|レ|通過|\|', l):
            continue
        else:
            cur = [l, None, None]; t['stops'].append(cur)
    t['stops'] = [s for s in t['stops'] if s[1] is not None or s[2] is not None]
    b = full.find('備考')
    if b >= 0:      # "はやぶさ1号はこまち1号と併結" etc.: the train it runs coupled to
        for m2 in re.finditer(r'(' + NAMES + r')\s*(\d+)\s*号', full[b:b + 400]):
            if (TYPES[m2.group(1)], int(m2.group(2))) != (t['type'], t['num']) and re.search('併結|連結', full[b:b + 400]):
                t['couple'] = [TYPES[m2.group(1)], int(m2.group(2))]; break
    if t['stops']:
        t['dest'] = t['stops'][-1][0]
        # times run on past midnight
        last = -1
        for s in t['stops']:
            for q in (1, 2):
                if s[q] is not None:
                    while s[q] < last - 6 * 3600: s[q] += 86400
                    last = s[q]
    return t


def collect(date_s, delay=0.7, show=0, limit_tables=40):
    d = datetime.date(int(date_s[:4]), int(date_s[4:6]), int(date_s[6:]))
    ed_n = '2' if d.weekday() >= 5 or holiday(d) else '1'
    top = fetch(BASE + 'timetable/list1039.html')
    eds = re.findall(r'/(\d{4})/timetable', top)
    if not eds: print('JR East: no edition found', flush=True); return []
    ed = max(eds)
    print(f'JR East edition {ed}, {"weekend/holiday" if ed_n == "2" else "weekday"} tables', flush=True)
    queue = [f'{BASE}{ed}/timetable-v/{n}{du}{ed_n}.html' for n in SEED for du in 'du']
    done, trains = set(), {}
    while queue and len(done) < limit_tables:
        url = queue.pop(0)
        if url in done: continue
        done.add(url)
        try:
            page = fetch(url); time.sleep(delay)
        except RuntimeError as e:
            print('  ', e, flush=True); continue
        hs = [urljoin(url, h) for h in re.findall(r'href="([^"]+)"', page)]
        tr = [h for h in hs if '/train/' in h]
        more = [h for h in hs if re.search(r'/timetable-v/\d+[du]' + ed_n + r'(_\d+)?\.html$', h) and h not in done and h not in queue]
        for h in tr: trains.setdefault(h.split('#')[0], url)
        print(f'  {url.rsplit("/", 1)[1]}: {len(set(tr))} trains ({len(trains)} total), {len(more)} more tables', flush=True)
        if not tr: print('   sample:', re.sub(r'\s+', ' ', re.sub(r'<script.*?</script>|<style.*?</style>', '', page, flags=re.S))[3000:4500], flush=True)
        queue += more
    out, skipped, off = [], 0, 0
    for n, u in enumerate(sorted(trains)):
        try:
            page = fetch(u); time.sleep(delay)
        except RuntimeError as e:
            print('  ', e, flush=True); skipped += 1; continue
        if n < show:
            i = page.find('運行日'); print(f'--- JR East train {u}\n calendar: ' + re.sub(r'\s+', ' ', page[i:i + 1800]) + '\n---', flush=True)
        r = runs_on(page, d)
        if r is False: off += 1; continue
        t = parse(page)
        if not t or len(t['stops']) < 2: skipped += 1; print('  skip', u, file=sys.stderr); continue
        t['id'] = 'E' + re.sub(r'\D', '', u.rsplit('/', 2)[-1])
        t['cal'] = r
        out.append(t)
        if n % 25 == 0: print(f'  {n + 1}/{len(trains)} {t["name"]}{t["num"]} {t["stock"]} {len(t["stops"])} stops, runs {r}', flush=True)
    print(f'JR East: {len(out)} trains run today, {off} not today, {skipped} unreadable', flush=True)
    return out


if __name__ == '__main__':
    ts = collect(sys.argv[1] if len(sys.argv) > 1 else datetime.datetime.utcnow().strftime('%Y%m%d'), show=3)
    for t in ts[:5]: print(t)
