# ShinkaViz

A 3D visualiser for the Japanese Shinkansen network in a Tron/Vectrex vector style: glowing edge lines on black, HDR bloom, and real timetables, terrain and train models as the data comes in.

The current test case is the **500 series** on the Sanyo Shinkansen (Shin-Osaka – Hakata). JR West ends its scheduled service on 13 January 2027, so capturing the current Kodama timetable is a priority.

## Status: look test

`index.html` is a self-contained prototype (three.js r128 from cdnjs). Open it in a browser.

What is real so far:
- Station locations and names (Japanese and English)
- Approximate 500 series proportions: 8 cars, 15 m nose, near-circular body, livery stripes

What is placeholder:
- **Track alignment:** a smooth curve through the station coordinates. To be replaced by OpenStreetMap data (see below).
- **Terrain:** procedural noise. To be replaced by GSI DEM elevation tiles.
- **Timetable:** an invented sample. A scheduling pass holds each Kodama at stations so faster trains overtake it there.
- **500 series pantograph type and position:** unverified.
- **Other trains:** simple far-view box shapes.

Controls: Chase / Trackside / Overview cameras, time speed 1×–300×, persistence and glow sliders. Drag to orbit, pinch or scroll to zoom.

## Rendering

- Lines are additive and HDR. Train bodies are black occluders, giving hidden-line removal.
- Train outlines use an inverted hull with constant pixel width. Feature lines are authored: window band, stripes, doors, cab canopy, bogies, pantographs.
- Two render passes: everything, then trains only. The trains-only pass feeds the persistence buffer.
- Bloom uses a 5-level downsample/blur chain, with a narrow core and a wide halo.
- Per-channel exponential tone map, so bright saturated lines go white-hot.
- Falls back to 8-bit render targets with scaled values when half-float targets aren't available.

## Data pipeline

`osm_sanyo.py` queries the Overpass API for Sanyo Shinkansen track ways (with tunnel and bridge flags) and stations. It writes `sanyo.json`, which holds the ways, the stations, and a 50 m centreline ordered Shin-Osaka → Hakata. It is untested so far.

```
python3 osm_sanyo.py sanyo.json
```

OpenStreetMap data is © OpenStreetMap contributors under the ODbL; the attribution must be shown wherever the data is displayed.

## Plan

1. Replace the placeholder track with the OSM centreline and tunnel/bridge flags.
2. Scrape the real Sanyo timetable, including which trains run as 500 series (before January 2027).
3. Replace the terrain with GSI DEM contours and coastlines.
4. Draw persistence trails as world-space lines, so orbiting doesn't smear.
5. Add higher-detail N700 / N700S models and correct consists.
6. Extend to the Tokaido line, then the rest of the network.
