#!/usr/bin/env python3
"""Turn sanyo.json (from osm_sanyo.py) into data/sanyo-line.js for the page.

- Re-centres the rough centreline on the real main-line rails (mean-shift passes)
- Resamples it to exactly STEP metres along its length
- Flags each sample as tunnel / bridge from the nearest OSM way
- Gives each station a chainage (metres from Shin-Osaka)

Output is a plain <script> file (window.SANYO_LINE = {...}) so the page also
works when opened straight from disk, where fetch() of local files is blocked.
Coordinates are local metres: x east, z south (the page's three.js convention),
from the origin LAT0/LON0 below.

Usage: python3 build_line.py [sanyo.json] [data/sanyo-line.js]   (standard library only)
"""
import json, math, os, statistics, sys
from collections import defaultdict

LAT0, LON0 = 34.2, 133.0
KX, KZ = 111320 * math.cos(math.radians(LAT0)), 110574
STEP = 50.0
CELL = 100.0


def log(msg=""):
    print(msg, file=sys.stderr, flush=True)


def to_xz(lon, lat):
    return ((lon - LON0) * KX, -(lat - LAT0) * KZ)


def resample(pts, step):
    """Points every `step` metres along a polyline."""
    out, carry = [pts[0]], 0.0
    for a, b in zip(pts, pts[1:]):
        seg = math.dist(a, b)
        d = step - carry
        while d <= seg:
            t = d / seg
            out.append((a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t))
            d += step
        carry = seg - (d - step)
    if math.dist(out[-1], pts[-1]) > step * 0.25:
        out.append(pts[-1])
    return out


def smooth(pts, w):
    out = []
    for i in range(len(pts)):
        win = pts[max(0, i - w): i + w + 1]
        out.append((sum(p[0] for p in win) / len(win), sum(p[1] for p in win) / len(win)))
    out[0], out[-1] = pts[0], pts[-1]
    return out


def main(src, dst):
    d = json.load(open(src, encoding="utf-8"))
    main_ways = [w for w in d["ways"] if not w["service"]]
    log(f"{len(main_ways)} main-line ways, {len(d['centreline'])} rough centreline samples")

    # Rails densified to 5 m, in a 100 m grid, each point carrying its way's flags.
    grid = defaultdict(list)
    for w in main_ways:
        flag = 1 if w["tunnel"] else 2 if w["bridge"] else 0
        xz = [to_xz(*c) for c in w["coords"]]
        for a, b in zip(xz, xz[1:]):
            n = max(1, math.ceil(math.dist(a, b) / 5))
            for k in range(n):
                t = k / n
                p = (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t)
                grid[(int(p[0] // CELL), int(p[1] // CELL))].append((p[0], p[1], flag))

    def near(p, r):
        cx, cz, k = int(p[0] // CELL), int(p[1] // CELL), int(r // CELL) + 1
        for dx in range(-k, k + 1):
            for dz in range(-k, k + 1):
                for q in grid.get((cx + dx, cz + dz), ()):
                    if (q[0] - p[0]) ** 2 + (q[1] - p[1]) ** 2 <= r * r:
                        yield q

    def stats(line, label):
        ds = []
        for p in line:
            best = min((math.dist(p, q[:2]) for q in near(p, 120)), default=999)
            ds.append(best)
        s = sorted(ds)
        log(f"  {label}: distance to nearest rail median {statistics.median(s):.2f} m, "
            f"p99 {s[int(.99 * len(s))]:.1f} m, max {s[-1]:.1f} m, >8 m: {sum(x > 8 for x in s)}")

    line = resample([to_xz(p[0], p[1]) for p in d["centreline"]], 25)
    stats(line, "rough")

    # Mean-shift: move each sample to the weighted mean of nearby rail points.
    # Wide first (fixes the badly-ordered patches), then tight (centres between
    # the two running lines without being pulled onto station loops).
    for radius, sigma, w in [(120, 50, 3), (60, 20, 3), (20, 8, 2), (8, 4, 2), (8, 4, 2)]:
        moved = []
        for p in line:
            sx = sz = sw = 0.0
            for q in near(p, radius):
                wt = math.exp(-((q[0] - p[0]) ** 2 + (q[1] - p[1]) ** 2) / (sigma * sigma))
                sx += q[0] * wt; sz += q[1] * wt; sw += wt
            moved.append((sx / sw, sz / sw) if sw > 1e-9 else p)
        line = resample(smooth(moved, w), 25)
        stats(line, f"pass r={radius}")

    line = resample(line, STEP)
    length = (len(line) - 1) * STEP
    log(f"final: {len(line)} samples, {length / 1000:.1f} km")

    # Flags: majority of rail points within 8 m of each sample.
    flags = []
    for p in line:
        c = [0, 0, 0]
        for q in near(p, 8):
            c[q[2]] += 1
        flags.append(max(range(3), key=lambda i: c[i]) if sum(c) else 0)
    # Fill 1-sample holes so short gaps don't flicker tunnel/open.
    for i in range(1, len(flags) - 1):
        if flags[i - 1] == flags[i + 1] != flags[i]:
            flags[i] = flags[i - 1]
    n = len(flags)
    log(f"  tunnel {flags.count(1) / n:.0%}, bridge/viaduct {flags.count(2) / n:.0%}, other {flags.count(0) / n:.0%}")

    stations = []
    for s in d["stations"]:
        p = to_xz(s["lon"], s["lat"])
        i = min(range(len(line)), key=lambda k: (line[k][0] - p[0]) ** 2 + (line[k][1] - p[1]) ** 2)
        off = math.dist(line[i], p)
        stations.append({"ja": s["name_ja"], "en": s["name_en"], "s": round(i * STEP)})
        log(f"  {s['name_ja']} {s['name_en'] or '-'}: {i * STEP / 1000:.1f} km, station node {off:.0f} m from line")
    if any(b["s"] <= a["s"] for a, b in zip(stations, stations[1:])):
        sys.exit("Station chainages are not increasing; check the centreline order.")

    out = {
        "source": d.get("source", "© OpenStreetMap contributors (ODbL)"),
        "origin": [LAT0, LON0], "step": STEP,
        "xz": [v for p in line for v in (round(p[0], 1), round(p[1], 1))],
        "flags": "".join(map(str, flags)),
        "stations": stations,
    }
    os.makedirs(os.path.dirname(dst) or ".", exist_ok=True)
    with open(dst, "w", encoding="utf-8") as f:
        f.write("// Generated by build_line.py from OpenStreetMap data (© OpenStreetMap contributors, ODbL)\n")
        f.write("window.SANYO_LINE=" + json.dumps(out, ensure_ascii=False, separators=(",", ":")) + ";\n")
    log(f"wrote {dst} ({os.path.getsize(dst) / 1024:.0f} KB)")


if __name__ == "__main__":
    a = sys.argv[1:]
    main(a[0] if a else "sanyo.json", a[1] if len(a) > 1 else "data/sanyo-line.js")
