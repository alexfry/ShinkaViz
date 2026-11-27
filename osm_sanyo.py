#!/usr/bin/env python3
"""Pull the Sanyo Shinkansen from OpenStreetMap (Overpass API) and write sanyo.json.

Output:
  ways        every track way: coords [lon, lat], tunnel / bridge flags, service tag
  stations    name_ja, name_en, lat, lon (one per station, the node nearest the line)
  centreline  50 m spaced [lon, lat, tunnel] averaged from the main tracks,
              ordered Shin-Osaka -> Hakata, for the motion model's chainage

Data (c) OpenStreetMap contributors, ODbL. Show that credit wherever it is displayed.
Usage: python3 osm_sanyo.py [out.json]       (standard library only)
"""
import json, math, sys, urllib.parse, urllib.request

OVERPASS = "https://overpass-api.de/api/interpreter"
STATIONS = ["新大阪", "新神戸", "西明石", "姫路", "相生", "岡山", "新倉敷", "福山", "新尾道", "三原",
            "東広島", "広島", "新岩国", "徳山", "新山口", "厚狭", "新下関", "小倉", "博多"]
BBOX = "33.4,130.2,35.0,135.7"
STEP = 50.0  # metres between centreline samples

QUERY = f"""
[out:json][timeout:300];
(
  relation["route"="railway"]["name"="山陽新幹線"];
)->.rel;
(
  way(r.rel)["railway"="rail"];
  way["railway"="rail"]["name"="山陽新幹線"]({BBOX});
)->.tracks;
.tracks out tags geom;
nwr["railway"="station"]["name"~"^({'|'.join(STATIONS)})$"]({BBOX});
out tags center;
"""


def fetch():
    body = urllib.parse.urlencode({"data": QUERY}).encode()
    req = urllib.request.Request(OVERPASS, data=body, headers={"User-Agent": "shinkansen-visualiser/0.1"})
    with urllib.request.urlopen(req, timeout=400) as r:
        return json.load(r)


# Local equirectangular projection, metres. Same origin as the page.
LAT0, LON0 = 34.2, 133.0
KX, KZ = 111320 * math.cos(math.radians(LAT0)), 110574
to_xy = lambda lon, lat: ((lon - LON0) * KX, (lat - LAT0) * KZ)
to_ll = lambda x, y: (x / KX + LON0, y / KZ + LAT0)


def main(out_path):
    data = fetch()
    ways, cands = [], {}
    for el in data["elements"]:
        t = el.get("tags", {})
        if el["type"] == "way" and "geometry" in el:
            ways.append({
                "id": el["id"],
                "tunnel": t.get("tunnel") in ("yes", "building_passage"),
                "bridge": t.get("bridge") in ("yes", "viaduct"),
                "service": t.get("service"),
                "coords": [[round(g["lon"], 7), round(g["lat"], 7)] for g in el["geometry"]],
            })
        elif t.get("railway") == "station":
            c = el.get("center") or {"lat": el.get("lat"), "lon": el.get("lon")}
            if c["lat"] is not None:
                cands.setdefault(t["name"], []).append({
                    "name_ja": t["name"], "name_en": t.get("name:en", ""),
                    "lat": c["lat"], "lon": c["lon"]})
    if not ways:
        sys.exit("No track ways returned; check the query or tag names.")

    main_pts = [(to_xy(lon, lat), w["tunnel"]) for w in ways if not w["service"] for lon, lat in w["coords"]]

    def nearest_track_dist(lon, lat):
        x, y = to_xy(lon, lat)
        return min((px - x) ** 2 + (py - y) ** 2 for (px, py), _ in main_pts[::5])

    stations = []
    for name in STATIONS:
        c = cands.get(name)
        if not c:
            print(f"warning: no station found for {name}", file=sys.stderr)
            continue
        stations.append(min(c, key=lambda s: nearest_track_dist(s["lon"], s["lat"])))

    # Order track points by projecting them onto the station-to-station polyline,
    # then average every point in each 50 m bin (merges both directions' tracks).
    guide = [to_xy(s["lon"], s["lat"]) for s in stations]
    seg_start = [0.0]
    for a, b in zip(guide, guide[1:]):
        seg_start.append(seg_start[-1] + math.dist(a, b))

    def chain(p):
        best = (1e30, 0.0)
        for i, (a, b) in enumerate(zip(guide, guide[1:])):
            dx, dy = b[0] - a[0], b[1] - a[1]
            L2 = dx * dx + dy * dy or 1.0
            t = max(0.0, min(1.0, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / L2))
            qx, qy = a[0] + t * dx, a[1] + t * dy
            d = (p[0] - qx) ** 2 + (p[1] - qy) ** 2
            if d < best[0]:
                best = (d, seg_start[i] + t * math.sqrt(L2))
        return best[1]

    bins = {}
    for (p, tun) in main_pts:
        k = int(chain(p) // STEP)
        b = bins.setdefault(k, [0.0, 0.0, 0, 0])
        b[0] += p[0]; b[1] += p[1]; b[2] += 1; b[3] += tun
    keys = sorted(bins)
    raw = [(bins[k][0] / bins[k][2], bins[k][1] / bins[k][2], bins[k][3] * 2 > bins[k][2]) for k in keys]

    # Light smoothing; OSM node spacing is uneven so bins jitter a little.
    W, line = 3, []
    for i in range(len(raw)):
        win = raw[max(0, i - W): i + W + 1]
        x = sum(r[0] for r in win) / len(win)
        y = sum(r[1] for r in win) / len(win)
        lon, lat = to_ll(x, y)
        line.append([round(lon, 7), round(lat, 7), int(raw[i][2])])

    out = {"source": "© OpenStreetMap contributors (ODbL)", "ways": ways, "stations": stations, "centreline": line}
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, separators=(",", ":"))
    tun = sum(r[2] for r in line) / max(1, len(line))
    print(f"{len(ways)} ways, {len(stations)} stations, centreline {len(line)} samples "
          f"(~{len(line) * STEP / 1000:.0f} km, {tun:.0%} tunnel) -> {out_path}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "sanyo.json")
