#!/usr/bin/env python3
"""Look at JR East's timetable site (timetables.jreast.co.jp) and print its structure: which line tables exist for the
Shinkansen, how they link to train pages, and what a train page's text looks like. Output goes to the Action log, to write
the JR East parser from. Standard library only."""
import re, sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from build_timetable import fetch, text_lines

BASE = 'https://timetables.jreast.co.jp'
top = fetch(BASE + '/')
links = sorted(set(re.findall(r'href="([^"]+)"', top)))
print('== top page: %d links' % len(links))
for l in links:
    if re.search(r'timetable|train|shinkansen|sk|/\d{4}/', l): print('  ', l)
ed = re.findall(r'/(\d{4})/', ' '.join(links))
ed = max(ed) if ed else None
print('== edition', ed)
cands = [l for l in links if 'timetable-v' in l] or ([f'/{ed}/timetable-v/'] if ed else [])
for c in cands[:3]:
    url = c if c.startswith('http') else BASE + (c if c.startswith('/') else '/' + c)
    try:
        page = fetch(url)
    except Exception as e:
        print('!!', url, e); continue
    hs = sorted(set(re.findall(r'href="([^"]+)"', page)))
    print(f'== {url}: {len(hs)} links'); [print('  ', h) for h in hs[:80]]
# a known line table and a known train page (from search results)
for url in [f'{BASE}/{ed}/timetable-v/004d1.html', f'{BASE}/{ed}/timetable/tt1039/1039010.html']:
    try:
        page = fetch(url)
    except Exception as e:
        print('!!', url, e); continue
    hs = re.findall(r'href="([^"]+)"', page)
    print(f'== {url}: {len(hs)} links, first train links:'); [print('  ', h) for h in [h for h in hs if '/train/' in h][:12]]
    print('  other links:', [h for h in hs if '/train/' not in h][:40])
    tr = [h for h in hs if '/train/' in h]
    if tr:
        u = tr[0] if tr[0].startswith('http') else BASE + '/' + tr[0].lstrip('./').replace('../', '')
        if '../' in tr[0]: u = BASE + '/' + ed + '/' + tr[0].split('../')[-1]
        try:
            t = fetch(u); print(f'== train page {u}\n' + '\n'.join(l for l in text_lines(t) if not re.fullmatch(r'\d{1,2}|[日月火水木金土]', l))[:3000])
        except Exception as e:
            print('!!', u, e)
