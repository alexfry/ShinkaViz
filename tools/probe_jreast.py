#!/usr/bin/env python3
"""Quick look at a few JR East train pages (log only): page text, the calendar's day cells, and a coupled train."""
import re, sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from build_timetable import fetch, text_lines
B = 'https://timetables.jreast.co.jp/'
top = fetch(B + 'timetable/list1039.html'); ed = max(re.findall(r'/(\d{4})/timetable', top))
tt = fetch(f'{B}{ed}/timetable/tt1039/1039021.html')        # Tokyo, Tohoku down, weekend
i = tt.find('<table'); print('== tt page table sample:', re.sub(r'\s+', ' ', tt[i:i + 2500]))
links = re.findall(r'href="([^"]*/train/[^"]+\.html)"', tt)
print('== train links', len(links))
picked = []
for h in links[:60]:
    u = h if h.startswith('http') else B + h.lstrip('./')
    p = fetch(u); txt = '\n'.join(text_lines(p))
    if not picked or ('こまち' in txt and len(picked) < 2) or ('◆' in txt and len(picked) < 3):
        picked.append(u)
        j = txt.find('時刻詳細'); print(f'\n== {u}\n' + txt[:txt.find('\n') + 1] + txt[j:j + 900])
        k = p.find('calendar-month'); cal = p[k:k + 30000]
        cells = re.findall(r'<td([^>]*)>(.*?)</td>', cal, re.S)
        sig = [(a.strip(), re.sub(r'\s+', ' ', c).strip()) for a, c in cells if re.search(r'\d', re.sub(r'<[^>]+>', '', c))]
        print('== day cells:', sig[:45])
    if len(picked) >= 3: break
