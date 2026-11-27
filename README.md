# ShinkaViz

A 3D visualiser for the Japanese Shinkansen network in a Tron/Vectrex vector style: glowing edge lines on black, HDR bloom, and real timetables, terrain and train models as the data comes in.

The current test case is the **500 series** on the Sanyo Shinkansen (Shin-Osaka – Hakata). JR West ends its scheduled service on 13 January 2027, so capturing the current Kodama timetable is a priority.

## Status: look test

`index.html` is a self-contained prototype (three.js r128 from cdnjs). Open it in a browser.

What is real so far:
- Track alignment, tunnels (51%) and viaducts (36%) from OpenStreetMap, 553.5 km Shin-Osaka – Hakata
- Station locations and names (Japanese and English)
- 500 series end-car shape fitted to a JR West V-set elevation drawing: nose plan and side profiles, canopy and glazing position, body section, livery band heights, door and bogie positions (tables in `index.html`)

What is placeholder:
- **Track layout at stations:** passing loops and platforms are generic, not the real layouts.
- **Terrain:** procedural noise. To be replaced by GSI DEM elevation tiles.
- **Timetable:** an invented sample. A scheduling pass holds each Kodama at stations so faster trains overtake it there.
- **500 series pantograph type and position:** unverified.
- **N700 family (all other trains):** fitted to an N700 Sakura design drawing (side and front views and dimensions). The nose contours are traced in the front view and projected onto the nose. Nozomi (N700A) is white with a blue stripe; Sakura and Kodama (7000/8000 series) are navy with a gold stripe. Trains within 3.5 km of the camera are drawn at full detail with instanced geometry; farther ones are simple boxes.

Controls:
- **Chase / Overview:** one continuous orbit camera. Zoom out from the train and it carries on into the overview. Close in, it turns with the train; far out, it's fixed to the map and its centre drifts from the train to the whole line. The buttons fly between the two.
- **Cinematic:** an automatic director that cuts between shots: a short flyby, tracking alongside, aerial orbit, aerial catching up and aerial left behind, nose, overhead, and tunnel entrance. It cuts to the platform as the 500 series arrives at each stop, and holds there while it stands.
- **Train selector:** follow any running train. The cameras, the cinematic director and the info panel all switch to it.
- **Platform:** stand on any station's platform, in either direction. Drag to look around and pinch to zoom. A departure board lists the next trains and whether each stops or passes through.
- **View menu:** persistence and glow sliders, plus layer toggles (terrain, coastline, rivers, motorways, trunk roads, JR lines, other railways).
- Time speed 1×–300×. Drag to orbit, pinch or scroll to zoom.

## Running it

```
python3 -m http.server 8000      # in the repo folder, then open http://localhost:8000
```

When the page can reach them, it streams **live map tiles**:
- **Map features:** [OpenFreeMap](https://openfreemap.org) vector tiles (OpenMapTiles schema) for coastline, lakes, rivers, motorway and trunk roads, and conventional railways.
- **Elevation:** [AWS Terrain Tiles](https://registry.opendata.aws/terrain-tiles/) (Terrarium) for contours, ground under the camera and viaducts, and the track's height profile.

Tiles are picked around the camera, fine near and coarse far, and turned into line work per tile. The decoder for the vector tile format is built in, so there's nothing to install. Add `#offline` to the URL to force the built-in data. The claude.ai published page can't reach outside hosts, so it always uses the built-in data (`data/*.js`).

## Rendering

- Lines are additive and HDR. Train bodies are black occluders, giving hidden-line removal.
- Train outlines use an inverted hull with constant pixel width. Feature lines are authored: window band, stripes, doors, cab canopy, bogies, pantographs.
- Two render passes: everything, then trains only. The trains-only pass feeds the persistence buffer.
- Bloom uses a 5-level downsample/blur chain, with a narrow core and a wide halo.
- Per-channel exponential tone map, so bright saturated lines go white-hot.
- Falls back to 8-bit render targets with scaled values when half-float targets aren't available.

## Data pipeline

1. `osm_sanyo.py` queries the Overpass API (it tries several mirrors) for Sanyo Shinkansen track ways with tunnel and bridge flags, plus the stations. It writes `sanyo.json`.
2. `build_line.py` re-centres the rough centreline on the real running rails, resamples it to 50 m, flags each sample as tunnel or viaduct, and gives each station its distance along the line. It writes `data/sanyo-line.js`, which the page loads with a plain `<script>` tag so it also works when opened from disk.

```
python3 osm_sanyo.py sanyo.json
python3 build_line.py sanyo.json data/sanyo-line.js
```

Context layers (coastline, rivers, motorway and trunk roads, JR and other conventional railways) come the same way. The corridor is fetched in ~40 km tiles, each cached in `.cache/` so a re-run only fetches what failed. Then the layers are clipped to 12–20 km either side of the line and simplified:

```
python3 osm_context.py osm-context.json        # needs data/sanyo-line.js
python3 build_context.py osm-context.json data/sanyo-context.js
```

If `data/sanyo-line.js` is missing, the page falls back to a smooth curve through the stations.

OpenStreetMap data is © OpenStreetMap contributors under the ODbL; the page shows that credit.

## Plan

1. ~~Replace the placeholder track with the OSM centreline and tunnel/bridge flags.~~ Done.
2. Scrape the real Sanyo timetable, including which trains run as 500 series (before January 2027).
3. Replace the terrain with GSI DEM contours and coastlines.
4. Draw persistence trails as world-space lines, so orbiting doesn't smear.
5. Add higher-detail N700 / N700S models and correct consists.
6. Extend to the Tokaido line, then the rest of the network.

## Timetable

`data/sanyo-timetable.js` holds the real timetable for one day: every Sanyo Shinkansen train with its stops, times, rolling stock and car count. It is rebuilt every morning (Japan time) by the **Timetable** GitHub Action (`.github/workflows/timetable.yml`), which runs `tools/build_timetable.py` against JR West's timetable site and commits the result. Run it by hand from the Actions tab to refresh now, optionally for a given date.

The app runs on Japan time when the timetable is present, and works out each train's position between stops from the scheduled times (it is not live tracking). Without the file it falls back to an invented sample day.

```
python3 tools/build_timetable.py              # today in Japan
python3 tools/build_timetable.py --date 20261204 --dump tools/.cache/pages   # a given day, keeping the raw pages
```
