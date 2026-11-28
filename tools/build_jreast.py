#!/usr/bin/env python3
"""JR East Shinkansen trains for one day, from timetables.jreast.co.jp (Tohoku, Hokkaido, Akita, Yamagata, Joetsu, Hokuriku).

Each station's list page links its Shinkansen timetables (weekday and weekend/holiday editions), which link every train
departing there to a train page with its stops and a calendar of the days it runs (bold). We crawl from the stations linked on
the site's front page, follow each train's stops to further stations, and keep the trains whose calendar includes the date.
(The line-wide "digital timetables" fill in with script, so they hold no links.) Used by build_timetable.py; standard library only."""
import re, sys, os, time, datetime
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
                i = page.find('運行日'); print(f'--- JR East train {u}\n calendar: ' + re.sub(r'\s+', ' ', page[i:i + 1800]) + '\n---', flush=True)
            r = runs_on(page, d)
            if r is False: off += 1; continue
            t = parse(page)
            if not t or len(t['stops']) < 2: skipped += 1; print('  skip', u, file=sys.stderr); continue
            t['id'] = 'E' + re.sub(r'\D', '', u.rsplit('/', 2)[-2] + u.rsplit('/', 1)[-1])
            t['cal'] = r
            out.append(t)
            if len(done) % 25 == 1: print(f'  {len(done)}/{len(trains)} {t["name"]}{t["num"]} {t["stock"]} {len(t["stops"])} stops, runs {r}', flush=True)
    print(f'JR East: {len(seen_l)} stations, {len(seen_tt)} timetables, {len(out)} trains run today, {off} not today, {skipped} unreadable', flush=True)
    return out


if __name__ == '__main__':
    ts = collect(sys.argv[1] if len(sys.argv) > 1 else datetime.datetime.utcnow().strftime('%Y%m%d'), show=3)
    for t in ts[:5]: print(t)
