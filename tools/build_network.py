#!/usr/bin/env python3
"""Build data/lines/<id>.js for every Shinkansen line in tools/lines.json, from OpenStreetMap (Overpass API).

For each line:
  1. Fetch its track ways (by route relation and way name, inside the line's bounding box) and its stations.
  2. Order the track along the line using the station-to-station polyline, and average both running lines into
     a rough centreline.
  3. Pull that onto the real rails with a few mean-shift passes, resample to STEP metres, flag each sample as
     tunnel / bridge, and give each station its chainage (metres along the line).
Lines that fail are reported and skipped; the others are still written. data/lines/index.js lists what was built.

Usage: python3 tools/build_network.py [line ids...]      (all lines if none given; standard library only)
Data © OpenStreetMap contributors, ODbL.
"""
import json, math, os, statistics, sys, time
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE); sys.path.insert(0, os.path.dirname(HERE))
from geo import PROJ, to_xz                       # noqa: E402
import osm_sanyo                                   # noqa: E402  (Overpass client with mirrors and retries)

STEP, CELL = 50.0, 100.0
OUT = os.path.join(os.path.dirname(HERE), 'data', 'lines')


def log(m=''):
    print(m, file=sys.stderr, flush=True)


def resample(pts, step):
    out, carry = [pts[0]], 0.0
    for a, b in zip(pts, pts[1:]):
        seg = math.dist(a, b)
        if seg == 0: continue
        d = step - carry
        while d <= seg:
            t = d / seg; out.append((a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t)); d += step
        carry = seg - (d - step)
    if math.dist(out[-1], pts[-1]) > step * .25: out.append(pts[-1])
    return out


def smooth(pts, w):
    out = []
    for i in range(len(pts)):
        win = pts[max(0, i - w): i + w + 1]
        out.append((sum(p[0] for p in win) / len(win), sum(p[1] for p in win) / len(win)))
    out[0], out[-1] = pts[0], pts[-1]
    return out


def queries(L):
    s, w, n, e = L['bbox']; bb = f'{s},{w},{n},{e}'
    rx = '^(' + '|'.join(L['osm']) + ')'
    tracks = f'''[out:json][timeout:240];
(
  relation["route"~"^(railway|train)$"]["name"~"{rx}"]({bb});
)->.rel;
(
  way(r.rel)["railway"="rail"];
  way["railway"="rail"]["name"~"{rx}"]({bb});
);
out tags geom;'''
    names = '|'.join(st[0] for st in L['stations'])
    stations = f'''[out:json][timeout:120];
nwr["railway"~"^(station|halt)$"]["name"~"^({names})$"]({bb});
out tags center;'''
    return tracks, stations


def build(L):
    qt, qs = queries(L)
    tr = osm_sanyo.overpass(qt, L['id'] + ' tracks')
    time.sleep(2)
    sta = osm_sanyo.overpass(qs, L['id'] + ' stations')
    ways, cands = [], defaultdict(list)
    for el in tr['elements']:
        t = el.get('tags', {})
        if el['type'] == 'way' and 'geometry' in el and not t.get('service'):
            ways.append({'tunnel': t.get('tunnel') in ('yes', 'building_passage'), 'bridge': t.get('bridge') in ('yes', 'viaduct'),
                         'xz': [to_xz(g['lon'], g['lat']) for g in el['geometry']]})
    for el in sta['elements']:
        t = el.get('tags', {}); c = el.get('center') or {'lat': el.get('lat'), 'lon': el.get('lon')}
        if c.get('lat') is not None: cands[t.get('name')].append(to_xz(c['lon'], c['lat']))
    if not ways: raise RuntimeError('no track ways')
    # rails densified to 5 m in a 100 m grid, carrying tunnel/bridge flags
    grid = defaultdict(list); pts = []
    for w in ways:
        f = 1 if w['tunnel'] else 2 if w['bridge'] else 0
        for a, b in zip(w['xz'], w['xz'][1:]):
            k = max(1, math.ceil(math.dist(a, b) / 5))
            for i in range(k):
                t = i / k; p = (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t)
                grid[(int(p[0] // CELL), int(p[1] // CELL))].append((p[0], p[1], f)); pts.append(p)

    def near(p, r):
        cx, cz, k = int(p[0] // CELL), int(p[1] // CELL), int(r // CELL) + 1
        for dx in range(-k, k + 1):
            for dz in range(-k, k + 1):
                for q in grid.get((cx + dx, cz + dz), ()):
                    if (q[0] - p[0]) ** 2 + (q[1] - p[1]) ** 2 <= r * r: yield q

    def dist_to_rail(p, r=3000):
        return min((math.dist(p, q[:2]) for q in near(p, r)), default=1e9)
    # stations: the candidate nearest the track
    guide, names = [], []
    for ja, en in L['stations']:
        c = cands.get(ja)
        if not c: raise RuntimeError(f'station {ja} not found')
        best = min(c, key=dist_to_rail); guide.append(best); names.append((ja, en))
        d = dist_to_rail(best)
        if d > 2000: raise RuntimeError(f'station {ja} is {d:.0f} m from the track')
    seg0 = [0.0]
    for a, b in zip(guide, guide[1:]): seg0.append(seg0[-1] + math.dist(a, b))

    def chain(p):
        best = (1e30, 0.0, 0.0)
        for i, (a, b) in enumerate(zip(guide, guide[1:])):
            dx, dz = b[0] - a[0], b[1] - a[1]; L2 = dx * dx + dz * dz or 1.0
            t0 = ((p[0] - a[0]) * dx + (p[1] - a[1]) * dz) / L2; t = max(0.0, min(1.0, t0))
            q = (a[0] + t * dx, a[1] + t * dz); d = math.dist(p, q)
            over = (t0 < 0 and i == 0) or (t0 > 1 and i == len(guide) - 2)
            if d < best[0]: best = (d, seg0[i] + t * math.sqrt(L2), over)
        return best
    # order rail points along the guide (dropping track beyond the end stations and far-off branches), 50 m bins
    lim = 6000 if L.get('mini') else 12000
    bins = {}
    for n, p in enumerate(pts[::2]):
        d, s, over = chain(p)
        if over or d > lim: continue
        b = bins.setdefault(int(s // STEP), [0.0, 0.0, 0]); b[0] += p[0]; b[1] += p[1]; b[2] += 1
    keys = sorted(bins)
    if len(keys) < 20: raise RuntimeError('too little track near the stations')
    gaps = [(a, b) for a, b in zip(keys, keys[1:]) if b - a > 10]
    for a, b in gaps[:8]: log(f'    gap {a * STEP / 1000:.1f}-{b * STEP / 1000:.1f} km')
    line = [(bins[k][0] / bins[k][2], bins[k][1] / bins[k][2]) for k in keys]
    line = [guide[0]] + smooth(line, 3) + [guide[-1]]
    line = resample(line, 25)
    for radius, sigma, w in [(120, 50, 3), (60, 20, 3), (20, 8, 2), (8, 4, 2), (8, 4, 2)]:
        moved = []
        for p in line:
            sx = sz = sw = 0.0
            for q in near(p, radius):
                wt = math.exp(-((q[0] - p[0]) ** 2 + (q[1] - p[1]) ** 2) / (sigma * sigma)); sx += q[0] * wt; sz += q[1] * wt; sw += wt
            moved.append((sx / sw, sz / sw) if sw > 1e-9 else p)
        line = resample(smooth(moved, w), 25)
    line = resample(line, STEP)
    ds = sorted(dist_to_rail(p, 200) for p in line[::4])
    log(f'  {L["id"]}: {len(line) * STEP / 1000:.1f} km, rail offset median {statistics.median(ds):.1f} m, p99 {ds[int(.99 * len(ds))]:.0f} m')
    flags = []
    for p in line:
        c = [0, 0, 0]
        for q in near(p, 8): c[q[2]] += 1
        flags.append(max(range(3), key=lambda i: c[i]) if sum(c) else 0)
    for i in range(1, len(flags) - 1):
        if flags[i - 1] == flags[i + 1] != flags[i]: flags[i] = flags[i - 1]
    stations, last = [], -1
    for (ja, en), g in zip(names, guide):
        lo = max(0, last + 1)
        i = min(range(lo, len(line)), key=lambda k: (line[k][0] - g[0]) ** 2 + (line[k][1] - g[1]) ** 2)
        stations.append({'ja': ja, 'en': en, 's': round(i * STEP)}); last = i
    return {'id': L['id'], 'ja': L['ja'], 'en': L['en'], 'mini': bool(L.get('mini')), 'proj': PROJ, 'step': STEP,
            'source': '© OpenStreetMap contributors (ODbL)',
            'xz': [v for p in line for v in (round(p[0], 1), round(p[1], 1))], 'flags': ''.join(map(str, flags)), 'stations': stations}


def main():
    cfg = json.load(open(os.path.join(HERE, 'lines.json'), encoding='utf-8'))['lines']
    want = set(sys.argv[1:])
    os.makedirs(OUT, exist_ok=True)
    done, failed = [], []
    for L in cfg:
        if want and L['id'] not in want: continue
        log(f'== {L["id"]} {L["en"]}')
        try:
            d = build(L)
        except (Exception, SystemExit) as e:
            failed.append(L['id']); log(f'  FAILED {L["id"]}: {e}'); continue
        with open(os.path.join(OUT, L['id'] + '.js'), 'w', encoding='utf-8') as f:
            f.write('// Generated by tools/build_network.py from OpenStreetMap data (© OpenStreetMap contributors, ODbL)\n')
            f.write(f'(window.SHINKA_LINES=window.SHINKA_LINES||{{}})["{L["id"]}"]=' + json.dumps(d, ensure_ascii=False, separators=(',', ':')) + ';\n')
        done.append(L['id']); time.sleep(3)
    # the index lists every line file present (built now or earlier), in config order
    have = [L for L in cfg if os.path.exists(os.path.join(OUT, L['id'] + '.js'))]
    idx = {'proj': PROJ, 'lines': [{'id': L['id'], 'ja': L['ja'], 'en': L['en'], 'mini': bool(L.get('mini')),
                                    'stations': [s[0] for s in L['stations']]} for L in have]}
    with open(os.path.join(OUT, 'index.js'), 'w', encoding='utf-8') as f:
        f.write('// Lines in data/lines, written by tools/build_network.py\nwindow.SHINKA_NET=' + json.dumps(idx, ensure_ascii=False, separators=(',', ':')) + ';\n')
    log(f'built: {", ".join(done) or "none"}; failed: {", ".join(failed) or "none"}')
    if not done: sys.exit('no lines built')


if __name__ == '__main__':
    main()
