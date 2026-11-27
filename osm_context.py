#!/usr/bin/env python3
"""Fetch context layers along the Sanyo Shinkansen from OpenStreetMap.

Layers: coastline, rivers, motorway + trunk roads, conventional railways
(JR and others; Shinkansen excluded). The corridor is split into ~40 km
tiles, each queried separately so public Overpass servers don't time out.
Finished tiles are cached in .cache/, so a re-run only fetches what failed.

Needs data/sanyo-line.js (from build_line.py) for the corridor.
Writes osm-context.json (raw, large; not committed). Then run build_context.py.

Data (c) OpenStreetMap contributors, ODbL.
Usage: python3 osm_context.py [osm-context.json]
"""
import json, math, os, sys, time

from osm_sanyo import overpass, log  # mirrors, retries, progress output

LINE_JS = "data/sanyo-line.js"
CACHE = ".cache"
TILE_KM = 40
MARGIN_KM = 16
KEEP = ("natural", "waterway", "highway", "railway", "name", "name:en", "operator", "usage", "service", "highspeed", "ref")

QUERY = """
[out:json][timeout:180][bbox:{s},{w},{n},{e}];
(
  way["natural"="coastline"];
  way["waterway"="river"];
  way["highway"~"^(motorway|trunk)$"];
  way["railway"="rail"]["highspeed"!="yes"][!"service"];
);
out tags geom;
"""


def load_line():
    txt = open(LINE_JS, encoding="utf-8").read()
    data = json.loads(txt[txt.index("=") + 1: txt.rindex(";")])
    lat0, lon0 = data["origin"]
    kx, kz = 111320 * math.cos(math.radians(lat0)), 110574
    xz = data["xz"]
    return [(xz[i] / kx + lon0, -xz[i + 1] / kz + lat0) for i in range(0, len(xz), 2)], data["step"]


def tiles(pts, step):
    per = int(TILE_KM * 1000 / step)
    dlat = MARGIN_KM / 110.574
    out = []
    for i in range(0, len(pts) - 1, per):
        chunk = pts[i: i + per + 1]
        lat_mid = sum(p[1] for p in chunk) / len(chunk)
        dlon = MARGIN_KM / (111.32 * math.cos(math.radians(lat_mid)))
        out.append((round(min(p[1] for p in chunk) - dlat, 4), round(min(p[0] for p in chunk) - dlon, 4),
                    round(max(p[1] for p in chunk) + dlat, 4), round(max(p[0] for p in chunk) + dlon, 4)))
    return out


def main(dst):
    if not os.path.exists(LINE_JS):
        sys.exit(f"{LINE_JS} not found; run build_line.py first.")
    pts, step = load_line()
    boxes = tiles(pts, step)
    os.makedirs(CACHE, exist_ok=True)
    log(f"{len(boxes)} tiles of ~{TILE_KM} km, {MARGIN_KM} km either side of the line")
    ways, t0 = {}, time.monotonic()
    for i, (s, w, n, e) in enumerate(boxes):
        cache = os.path.join(CACHE, f"context_{i:02d}_{s}_{w}_{n}_{e}.json")
        if os.path.exists(cache):
            data = json.load(open(cache, encoding="utf-8"))
            log(f"[tile {i + 1}/{len(boxes)}] cached, {len(data['elements'])} ways")
        else:
            data = overpass(QUERY.format(s=s, w=w, n=n, e=e), f"tile {i + 1}/{len(boxes)}")
            json.dump(data, open(cache, "w", encoding="utf-8"))
        new = 0
        for el in data["elements"]:
            if el.get("type") == "way" and "geometry" in el and el["id"] not in ways:
                tags = {k: v for k, v in el.get("tags", {}).items() if k in KEEP}
                ways[el["id"]] = {"id": el["id"], "tags": tags,
                                  "coords": [[round(g["lon"], 7), round(g["lat"], 7)] for g in el["geometry"]]}
                new += 1
        log(f"    {new} new ways, {len(ways)} total, {time.monotonic() - t0:.0f}s elapsed")

    counts = {}
    for w in ways.values():
        t = w["tags"]
        k = "coastline" if t.get("natural") == "coastline" else "river" if t.get("waterway") else \
            t.get("highway") or ("rail" if t.get("railway") else "other")
        counts[k] = counts.get(k, 0) + 1
    log("ways by type: " + ", ".join(f"{k} {v}" for k, v in sorted(counts.items())))
    json.dump({"source": "© OpenStreetMap contributors (ODbL)", "ways": list(ways.values())},
              open(dst, "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
    log(f"wrote {dst} ({os.path.getsize(dst) / 1e6:.1f} MB). Next: python3 build_context.py")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "osm-context.json")
