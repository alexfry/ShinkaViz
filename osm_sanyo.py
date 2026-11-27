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
import json, math, sys, threading, time, urllib.error, urllib.parse, urllib.request

MIRRORS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://maps.mail.ru/osm/tools/overpass/api/interpreter",
]
STATIONS = ["新大阪", "新神戸", "西明石", "姫路", "相生", "岡山", "新倉敷", "福山", "新尾道", "三原",
            "東広島", "広島", "新岩国", "徳山", "新山口", "厚狭", "新下関", "小倉", "博多"]
BBOX = "33.4,130.2,35.0,135.7"
STEP = 50.0  # metres between centreline samples

# Two smaller queries instead of one big one: public Overpass servers often
# answer large or long-running requests with 502/504.
Q_TRACKS = f"""
[out:json][timeout:180];
relation["route"="railway"]["name"="山陽新幹線"]->.rel;
(
  way(r.rel)["railway"="rail"];
  way["railway"="rail"]["name"="山陽新幹線"]({BBOX});
);
out tags geom;
"""
Q_STATIONS = f"""
[out:json][timeout:120];
nwr["railway"="station"]["name"~"^({'|'.join(STATIONS)})$"]({BBOX});
out tags center;
"""


UA = {"User-Agent": "ShinkaViz/0.1 (github.com/alexfry/shinkaviz)"}
READ_TIMEOUT = 120  # seconds of silence before giving up on a server


def log(msg=""):
    print(msg, file=sys.stderr, flush=True)


class Ticker:
    """Prints elapsed time (and bytes received, once downloading) every 5 s."""
    def __init__(self):
        self.t0, self.phase, self.bytes = time.monotonic(), "waiting for server", 0
        self.stop = threading.Event()
        threading.Thread(target=self._run, daemon=True).start()

    def _run(self):
        while not self.stop.wait(5):
            extra = f", {self.bytes / 1024:.0f} KB so far" if self.bytes else ""
            log(f"    … {self.phase}, {self.elapsed():.0f}s{extra}")

    def elapsed(self):
        return time.monotonic() - self.t0


def server_status(url):
    """Overpass /api/status: free query slots and rate limit. Not every mirror has it."""
    try:
        req = urllib.request.Request(url.replace("/interpreter", "/status"), headers=UA)
        with urllib.request.urlopen(req, timeout=3) as r:
            lines = r.read(4000).decode("utf-8", "replace").splitlines()
        keys = ("Rate limit", "slots available", "Slot available after", "Currently running")
        shown = [l.strip() for l in lines if any(k in l for k in keys)]
        return "; ".join(shown[:4]) or "status page has no slot info"
    except Exception as e:
        return f"status unavailable ({e.__class__.__name__})"


def overpass(query, label):
    """POST a query, trying each mirror with backoff. Busy servers return 429/502/503/504."""
    body = urllib.parse.urlencode({"data": query}).encode()
    last = None
    for attempt in range(3):
        for url in list(MIRRORS):
            host = urllib.parse.urlparse(url).netloc
            log(f"[{label}] {host}, round {attempt + 1}/3")
            log(f"    server: {server_status(url)}")
            tick = Ticker()
            try:
                req = urllib.request.Request(url, data=body, headers=UA)
                with urllib.request.urlopen(req, timeout=READ_TIMEOUT) as r:
                    log(f"    HTTP {r.status} after {tick.elapsed():.1f}s, downloading")
                    tick.phase, chunks = "downloading", []
                    while chunk := r.read(65536):
                        chunks.append(chunk)
                        tick.bytes += len(chunk)
                tick.stop.set()
                data = json.loads(b"".join(chunks))
                remark = data.get("remark", "")
                if remark:
                    log(f"    server remark: {remark}")
                if "runtime error" in remark:
                    raise RuntimeError(remark)
                n = len(data.get("elements", []))
                log(f"    received {tick.bytes / 1024:.0f} KB, {n} elements in {tick.elapsed():.1f}s")
                MIRRORS.remove(url)
                MIRRORS.insert(0, url)  # stick with the server that last worked
                return data
            except urllib.error.HTTPError as e:
                detail = e.read(300).decode("utf-8", "replace").strip().replace("\n", " ")
                last = f"{host}: HTTP {e.code} {detail[:200]}"
            except (urllib.error.URLError, TimeoutError, OSError, RuntimeError, json.JSONDecodeError) as e:
                last = f"{host}: {e.__class__.__name__}: {e}"
            finally:
                tick.stop.set()
            log(f"    failed after {tick.elapsed():.0f}s: {last}")
        if attempt < 2:
            wait = 15 * (attempt + 1)
            log(f"all mirrors failed this round; waiting {wait}s")
            time.sleep(wait)
    sys.exit(f"All Overpass mirrors failed. Last error: {last}")


def fetch():
    tracks = overpass(Q_TRACKS, "tracks")
    stations = overpass(Q_STATIONS, "stations")
    return {"elements": tracks["elements"] + stations["elements"]}


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

    def way_km(w):
        xy = [to_xy(*c) for c in w["coords"]]
        return sum(math.dist(a, b) for a, b in zip(xy, xy[1:])) / 1000
    main_w = [w for w in ways if not w["service"]]
    log()
    log(f"ways: {len(ways)} total, {len(main_w)} main line, {len(ways) - len(main_w)} service/siding")
    log(f"  main-line track: {sum(map(way_km, main_w)):.0f} km (both directions, so roughly 2 x route length)")
    log(f"  tunnel: {sum(way_km(w) for w in main_w if w['tunnel']):.0f} km, bridge/viaduct: {sum(way_km(w) for w in main_w if w['bridge']):.0f} km")
    services = sorted({w["service"] for w in ways if w["service"]})
    if services:
        log(f"  service tags seen: {', '.join(services)}")

    # OSM only places nodes where track bends, so long straights can have km
    # between nodes. Resample every main-line way to <= 20 m before binning.
    main_pts = []
    for w in main_w:
        xy = [to_xy(*c) for c in w["coords"]]
        for a, b in zip(xy, xy[1:]):
            n = max(1, math.ceil(math.dist(a, b) / 20.0))
            for i in range(n):
                t = i / n
                main_pts.append(((a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t), w["tunnel"]))
        if xy:
            main_pts.append((xy[-1], w["tunnel"]))

    def nearest_track_dist(lon, lat):
        x, y = to_xy(lon, lat)
        return min((px - x) ** 2 + (py - y) ** 2 for (px, py), _ in main_pts[::25])

    stations = []
    for name in STATIONS:
        c = cands.get(name)
        if not c:
            print(f"warning: no station found for {name}", file=sys.stderr)
            continue
        best = min(c, key=lambda s: nearest_track_dist(s["lon"], s["lat"]))
        stations.append(best)
        d = math.sqrt(nearest_track_dist(best["lon"], best["lat"]))
        log(f"  station {name} {best['name_en'] or '(no name:en)'}: {len(c)} candidate(s), chosen one ~{d:.0f} m from track")

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

    log(f"ordering {len(main_pts)} track points along the route")
    bins = {}
    for n, (p, tun) in enumerate(main_pts):
        if n and n % 20000 == 0:
            log(f"    {n}/{len(main_pts)}")
        k = int(chain(p) // STEP)
        b = bins.setdefault(k, [0.0, 0.0, 0, 0])
        b[0] += p[0]; b[1] += p[1]; b[2] += 1; b[3] += tun
    keys = sorted(bins)
    raw = [(bins[k][0] / bins[k][2], bins[k][1] / bins[k][2], bins[k][3] * 2 > bins[k][2]) for k in keys]
    gaps = [(a, b) for a, b in zip(keys, keys[1:]) if b - a > 10]
    log(f"{len(keys)} bins of {STEP:.0f} m; {len(gaps)} gap(s) over 500 m")
    for a, b in gaps[:10]:
        log(f"    gap {a * STEP / 1000:.1f}-{b * STEP / 1000:.1f} km ({(b - a) * STEP:.0f} m) - missing or mis-tagged track?")
    if len(gaps) > 10:
        log(f"    ... and {len(gaps) - 10} more")

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
