#!/usr/bin/env python3
"""JR East Shinkansen trains for one day, from timetables.jreast.co.jp (Tohoku, Hokkaido, Akita, Yamagata, Joetsu, Hokuriku).

Each station's list page links its Shinkansen timetables (weekday and weekend/holiday editions), which link every train
departing there to a train page with its stops and a calendar of the days it runs (bold). We crawl from the stations linked on
the site's front page, follow each train's stops to further stations, and keep the trains whose calendar includes the date.
(The line-wide "digital timetables" fill in with script, so they hold no links.) Used by build_timetable.py; standard library only."""
import re, sys, os, time, datetime, unicodedata
from urllib.parse import urljoin
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from build_timetable import fetch, text_lines, secs, TYPES, NAMES, SERIES

BASE = 'https://timetables.jreast.co.jp/'


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
    """The train page's calendar: one table per month, each day's cell classed "ok" (runs) or "none". None if unreadable."""
    for cap in re.finditer(r'<caption>\s*(\d{4})年\s*(\d{1,2})月\s*</caption>(.*?)</table>', page, re.S):
        if (int(cap.group(1)), int(cap.group(2))) != (date.year, date.month): continue
        for cls, inner in re.findall(r'<td[^>]*class="([^"]*)"[^>]*>(.*?)</td>', cap.group(3), re.S):
            n = re.sub(r'<[^>]+>|\s', '', inner)
            if n.isdigit() and int(n) == date.day:
                return 'ok' in cls.split()
    return None


def clean(h):
    return unicodedata.normalize('NFKC', re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', ' ', h))).strip()


def parse(page):
    """A train page: a table with a column per train (two when they run coupled, e.g. Hayabusa+Komachi). Returns a list of
    trains. A coupled train's column is blank where it shares the lead train's times; those are copied over."""
    q = page.find('時刻詳細')
    if q < 0: return []
    rows = re.findall(r'<tr[^>]*>(.*?)</tr>', page[q:], re.S)
    names, nums, table = [], [], []
    for r in rows:
        th = re.search(r'<th[^>]*>(.*?)</th>', r, re.S)
        if not th: continue
        head = clean(th.group(1))
        tds = re.findall(r'<td([^>]*)>(.*?)</td>', r, re.S)
        if head == '列車名': names = [clean(c) for a, c in tds]
        elif head == '列車番号': nums = [clean(c) for a, c in tds]
        elif 'class="time"' in r and tds:
            cells = [c for a, c in tds if 'time' in a and 'platform' not in a]
            if not cells: cells = [tds[k][1] for k in range(0, len(tds), 2)]
            table.append((clean(th.group(1)), [clean(c) for c in cells]))
        elif head.startswith('備考'): break
    trains = []
    for c, nm in enumerate(names):
        m = re.search(r'(' + NAMES + r')\s*(\d+)\s*号', nm)
        if not m: continue
        trains.append({'name': m.group(1), 'type': TYPES[m.group(1)], 'num': int(m.group(2)), 'stock': None, 'cars': None,
                       'dest': None, 'col': c, 'cells': [], 'stops': []})
    if not trains: return []
    def times(cell):
        a = re.search(r'(\d{1,2}):(\d{2})\s*着', cell); d = re.search(r'(\d{1,2}):(\d{2})\s*発', cell)
        return [secs(int(a.group(1)), int(a.group(2))) if a else None, secs(int(d.group(1)), int(d.group(2))) if d else None]
    for t in trains:
        t['cells'] = [(st, cells[t['col']] if t['col'] < len(cells) else '') for st, cells in table]
    has = lambda t: [any(x is not None for x in times(c)) for st, c in t['cells']]
    lead = max(trains, key=lambda t: sum(has(t)))
    for t in trains:
        H = has(t); own = [i for i, h in enumerate(H) if h]
        if not own: continue
        lo, hi = own[0], own[-1]
        for i, (st, c) in enumerate(t['cells']):
            tm = times(c)
            if t is not lead:
                L = times(lead['cells'][i][1])
                shared_before = i < lo and c == '' and all(t['cells'][k][1] == '' for k in range(i, lo))
                shared_after = i > hi and c == '' and all(t['cells'][k][1] == '' for k in range(hi + 1, i + 1))
                if shared_before or shared_after:
                    tm = L
                elif i == lo and tm[0] is None and lo > 0 and t['cells'][lo - 1][1] == '': tm[0] = L[0]     # 分割: arrives with the lead
                elif i == hi and tm[1] is None and hi < len(H) - 1 and t['cells'][hi + 1][1] == '': tm[1] = L[1]  # 併合: leaves with it
            if tm[0] is not None or tm[1] is not None:
                t['stops'].append([st, tm[0], tm[1]])
        last = -1
        for s_ in t['stops']:
            for k in (1, 2):
                if s_[k] is not None:
                    while s_[k] < last - 6 * 3600: s_[k] += 86400
                    last = s_[k]
        if t['stops']: t['dest'] = t['stops'][-1][0]
    out = [t for t in trains if len(t['stops']) >= 2]
    if len(out) > 1:
        for t in out:
            o = next(x for x in out if x is not t); t['couple'] = [o['type'], o['num']]
    for t in out: del t['cells']; del t['col']
    return out


def shinkansen_tts(url, page, suffix):
    """A station's list page: the timetable pages of its JR East Shinkansen lines for one edition (suffix 0 weekday, 1 weekend)."""
    out = []
    for m in re.finditer(r'href="([^"]*/timetable/tt\d+/\d+' + suffix + r'\.html)"', page):
        before = re.findall(r'>\s*([^<>]*?(?:新幹線|線|ライン)[^<>]{0,12}?)\s*<', page[max(0, m.start() - 3000):m.start()])
        before = [b for b in before if '番線' not in b and 'きっぷ' not in b]
        if before and '新幹線' in before[-1] and '東海道' not in before[-1]:
            out.append(urljoin(url, m.group(1)))
    return sorted(set(out))


def collect(date_s, delay=0.7, show=0, max_stations=200):
    """Crawl: station list pages -> their Shinkansen timetables -> train pages, whose stops link to more stations."""
    d = datetime.date(int(date_s[:4]), int(date_s[4:6]), int(date_s[6:]))
    suffix = '1' if d.weekday() >= 5 or holiday(d) else '0'
    print(f'JR East: {"weekend/holiday" if suffix == "1" else "weekday"} timetables', flush=True)
    top = fetch(BASE); time.sleep(delay)
    lists = [urljoin(BASE, h) for h in re.findall(r'href="([^"]*timetable/list\d+\.html)"', top)]
    lists.insert(0, BASE + 'timetable/list1039.html')
    seen_l, seen_tt, trains = set(), set(), {}
    def do_list(u):
        if u in seen_l or len(seen_l) >= max_stations: return
        seen_l.add(u)
        try:
            page = fetch(u); time.sleep(delay)
        except RuntimeError as e:
            print('  ', e, flush=True); return
        for tt in shinkansen_tts(u, page, suffix):
            if tt in seen_tt: continue
            seen_tt.add(tt)
            try:
                p2 = fetch(tt); time.sleep(delay)
            except RuntimeError as e:
                print('  ', e, flush=True); continue
            new = 0
            for h in re.findall(r'href="([^"]*/train/[^"]+\.html)"', p2):
                h = urljoin(tt, h)
                if h not in trains: trains[h] = None; new += 1
            print(f'  {tt.rsplit("/", 1)[1]}: +{new} trains ({len(trains)} total)', flush=True)
    for u in dict.fromkeys(lists): do_list(u)
    out, skipped, off, done = [], 0, 0, set()
    while True:
        todo = [u for u in trains if u not in done]
        if not todo: break
        for u in todo:
            done.add(u)
            try:
                page = fetch(u); time.sleep(delay)
            except RuntimeError as e:
                print('  ', e, flush=True); skipped += 1; continue
            for h in re.findall(r'href="([^"]*timetable/list\d+\.html)"', page): do_list(urljoin(u, h))
            if len(done) <= show:
                print(f'--- JR East train {u}: runs {runs_on(page, d)}', [(t['name'], t['num'], t['stops'], t.get('couple')) for t in parse(page)], flush=True)
            r = runs_on(page, d)
            if r is False: off += 1; continue
            ts = parse(page)
            if not ts: skipped += 1; print('  skip', u, file=sys.stderr); continue
            for c, t in enumerate(ts):
                t['id'] = 'E' + re.sub(r'\D', '', u.rsplit('/', 2)[-2] + u.rsplit('/', 1)[-1]) + ('' if c == 0 else '-%d' % c)
                t['cal'] = r
                out.append(t)
            if len(done) % 25 == 1: print(f'  {len(done)}/{len(trains)} ' + ' + '.join(f'{t["name"]}{t["num"]} {len(t["stops"])} stops' for t in ts) + f', runs {r}', flush=True)
    print(f'JR East: {len(seen_l)} stations, {len(seen_tt)} timetables, {len(out)} trains run today, {off} not today, {skipped} unreadable', flush=True)
    return out


if __name__ == '__main__':
    ts = collect(sys.argv[1] if len(sys.argv) > 1 else datetime.datetime.utcnow().strftime('%Y%m%d'), show=3)
    for t in ts[:5]: print(t)
