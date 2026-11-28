#!/usr/bin/env python3
"""Quick look at a few JR East train pages (log only): page text, the calendar's day cells, and a coupled train."""
import re, sys, os
from urllib.parse import urljoin
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from build_timetable import fetch, text_lines
B = 'https://timetables.jreast.co.jp/'
top = fetch(B + 'timetable/list1039.html'); ed = max(re.findall(r'/(\d{4})/timetable', top))
ttu = f'{B}{ed}/timetable/tt1039/1039021.html'; tt = fetch(ttu)        # Tokyo, Tohoku down, weekend
links = re.findall(r'href="([^"]*/train/[^"]+\.html)"', tt)
print('== train links', len(links))
picked = []
for h in links[:60]:
    u = urljoin(ttu, h)
    p = fetch(u); txt = '\n'.join(text_lines(p))
    if not picked or ('こまち' in txt and len(picked) < 2) or ('◆' in txt and len(picked) < 3):
        picked.append(u)
        j = txt.find('時刻詳細'); print(f'\n== {u}\n' + txt[:txt.find('\n') + 1] + txt[j:j + 1600])
        k = p.find('calendar-month'); cal = p[k:k + 30000]
        cells = re.findall(r'<td([^>]*)>(.*?)</td>', cal, re.S)
        sig = [(a.strip(), re.sub(r'\s+', ' ', c).strip()) for a, c in cells if re.search(r'\d', re.sub(r'<[^>]+>', '', c))]
        print('== day cells:', sig[:45])
        q = p.find('時刻詳細'); raw = re.sub(r'\s+', ' ', re.sub(r'<script.*?</script>', '', p[q:q + 40000], flags=re.S))
        print('== raw:', raw[raw.find('駅名') - 200:][:5000])
    if len(picked) >= 3: break
