#!/usr/bin/env python3
"""Look at JR East's timetable site and print its structure to the Action log: a station's list page (Tokyo, 1039), its
Shinkansen timetables, a train page's text. Standard library only."""
import re, sys, os
from urllib.parse import urljoin
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from build_timetable import fetch, text_lines

BASE = 'https://timetables.jreast.co.jp/'
def links(url, page):
    out = []
    for m in re.finditer(r'<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>', page, re.S):
        out.append((urljoin(url, m.group(1)), re.sub(r'<[^>]+>|\s+', ' ', m.group(2)).strip()))
    return out
def show(url, n=60):
    page = fetch(url); L = links(url, page)
    print(f'\n== {url}: {len(L)} links'); [print('  ', h, '|', t[:40]) for h, t in L[:n]]
    return page, L
for st in ['1039', '0039']:          # Tokyo; and another (Omiya?) to see the pattern
    try:
        page, L = show(BASE + f'timetable/list{st}.html', 80)
        print('  text:', ' / '.join(text_lines(page))[:1500])
    except Exception as e:
        print('!!', st, e); continue
    tts = [h for h, t in L if '/timetable/tt' in h]
    shk = [h for h, t in L if '/timetable/tt' in h and '新幹線' in t] or tts
    for u in shk[:2]:
        try:
            p2, L2 = show(u, 30)
        except Exception as e:
            print('!!', u, e); continue
        print('  text:', ' / '.join(text_lines(p2))[:1200])
        tr = [h for h, t in L2 if '/train/' in h]
        print('  train links', len(tr), tr[:5])
        if tr:
            try:
                t = fetch(tr[0]); print(f'== train page {tr[0]}\n' + '\n'.join(text_lines(t))[:2500])
                print('  raw snippet:', re.sub(r'\s+', ' ', t[t.find('時刻'):])[:1500])
            except Exception as e:
                print('!!', tr[0], e)
    break
