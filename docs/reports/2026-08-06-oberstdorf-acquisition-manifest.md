# Oberstdorf data acquisition manifest

Date: 2026-08-06

## Scope

- Source AOI: `data/incoming/activation_4f77819b-694b-40f8-ae8c-f1bf9fe02251.kml`
- AOI layer: `Layer #0` (one polygon)
- AOI area: approximately 41.371 km2
- Working CRS: EPSG:25832 (ETRS89 / UTM zone 32N)
- Purpose: recovery-mapping feasibility for debris-flow and landslide effects near Markt Oberstdorf
- The controlled first batch has been downloaded; no large product has been acquired.

## Resource controls

- Automatic per-file ceiling: 25 MiB
- Automatic batch ceiling: 50 MiB
- Metadata response ceiling: 2 MiB
- Network timeout per request: 25 seconds
- Size discovery: one-byte HTTP range request where `HEAD` is unsupported
- Unknown-size files: blocked
- Statewide raster or imagery bundles: blocked
- Duplicate URLs: download once, then use the local cached copy
- Analysis and clipping: local only, after acquisition

## Measured official downloads

Sizes below were obtained from `Content-Range` using a one-byte request on 2026-08-06.

| Priority | Dataset | Format / CRS | Compressed size | Decision |
|---|---|---|---:|---|
| 1 | Georisk objects | Shapefile / EPSG:25832 | 13.39 MiB | Downloaded; integrity verified; kept compressed |
| 1 | Drinking-water protection areas (`twsg`) | Shapefile / EPSG:25832 | 4.31 MiB | Downloaded; integrity verified; kept compressed |
| 2 | Heilquellenschutzgebiete (`hqsg`) | Shapefile / EPSG:25832 | 0.14 MiB | Defer unless the metadata indicates relevance to this AOI |
| 2 | Geohazard indication maps | Shapefile / EPSG:25832 | 394.24 MiB | Blocked; statewide archive is too large |
| 2 | Surface-runoff hazard areas | GML ZIP | 451.96 MiB | Blocked; statewide archive is too large |
| 2 | Surface-runoff depressions/ponding | GeoPackage ZIP | 500.24 MiB | Blocked; statewide archive is too large |
| 2 | Potential runoff flow paths | GeoPackage ZIP | 1021.21 MiB | Blocked; statewide archive is too large |

Proposed first batch: 17.70 MiB compressed across two files.

## Acquired files

| Local file | Bytes | SHA-256 | Uncompressed archive content |
|---|---:|---|---:|
| `data/work/oberstdorf-acquisition/downloads/georisk-objekte_epsg25832_shp.zip` | 14,035,461 | `abbe5b8fa97fe4b495228279912e05ff81044e1a079d095f6729bce49a807374` | 119,698,251 bytes |
| `data/work/oberstdorf-acquisition/downloads/twsg_epsg25832_shp.zip` | 4,517,879 | `a10364e3efc7e5ebe490c42dc943080cac2876be7117f385eebb06121bde68da` | 8,050,183 bytes |

Both archives passed `unzip -t`. They were not extracted. The georisk ZIP contains three EPSG:25832 shapefiles (`ablagerung`, `anbruch`, and `objekt`); the water-protection ZIP contains one (`twsg`).

## Official URLs

- Georisk objects: <https://www.lfu.bayern.de/gdi/dls/daten/georisiken/georisk-objekte_epsg25832_shp.zip>
- Drinking-water protection areas: <https://www.lfu.bayern.de/gdi/dls/daten/wsg/twsg_epsg25832_shp.zip>
- Heilquellenschutzgebiete: <https://www.lfu.bayern.de/gdi/dls/daten/wsg/hqsg_epsg25832_shp.zip>
- Geohazard indication maps: <https://www.lfu.bayern.de/gdi/dls/daten/georisiken/gefahrenhinweiskarten_epsg25832_shp.zip>
- Surface-runoff feed: <https://www.lfu.bayern.de/gdi/dls/oberflaechenabfluss.xml>
- Georisk feed: <https://www.lfu.bayern.de/gdi/dls/georisiken.xml>
- Water-protection feed: <https://www.lfu.bayern.de/gdi/dls/wsg.xml>

## Elevation and imagery

The Bavarian OpenData portal provides DGM1 as 1 km by 1 km GeoTIFF tiles at approximately 4 MB per tile. The AOI bounding box spans roughly 7 km east-west and 11 km north-south before buffering, so a naive bounding-box request could require about 77 tiles (approximately 308 MB). A 1 km buffer could raise this to roughly 117 tiles (approximately 468 MB). DGM1 therefore remains blocked until exact intersecting tile URLs and their aggregate size are known.

DOP20 imagery is approximately 20-50 MB per 1 km tile. It remains blocked for this limited machine. A small, capped WMS preview may be used later for visual feasibility, but not a tile pyramid or repeated rendering.

Official product pages:

- DGM1: <https://geodaten.bayern.de/opengeodata/OpenDataDetail.html?pn=dgm1>
- DOP20 RGB: <https://geodaten.bayern.de/opengeodata/OpenDataDetail.html?active=SERVICE&pn=dop20rgb>

## Licensing and interpretation

- Bavarian Surveying Administration OpenData products are CC BY 4.0.
- LfU georisk and surface-runoff products require attribution: `Datenquelle: Bayerisches Landesamt fuer Umwelt, www.lfu.bayern.de`.
- The drinking-water protection feed is CC BY-SA 4.0 and is overview information. Legally binding boundaries, zones, and restrictions must be obtained from the competent district authority.
- Surface-runoff indications are topographic screening information, not a parcel- or building-level hydraulic flood model.

## Next controlled action

The recommended local overlap screen is complete. Only `anbruch`, `ablagerung`, and `twsg` were selectively extracted and ingested; `georisk_objekt` remains compressed. No additional portal requests were made.

AOI overlap results:

| Result | Features | Clipped measure |
|---|---:|---:|
| Detachment lines (`anbruch`) | 25 | 6,307.4 m |
| Deposition polygons (`ablagerung`) | 19 | 1.709 km2 |
| Drinking-water protection polygons (`twsg`) | 2 | 1.632 km2 |

Local analysis schema: `analysis_20260806102947_c090725995`

Exports:

- `data/outgoing/2026-08-06_oberstdorf-feasibility/aoi_anbruch.gpkg`
- `data/outgoing/2026-08-06_oberstdorf-feasibility/aoi_ablagerung.gpkg`
- `data/outgoing/2026-08-06_oberstdorf-feasibility/aoi_twsg.gpkg`
- `data/outgoing/2026-08-06_oberstdorf-feasibility/overlap_summary.gpkg`

These are screening results from existing statewide inventory data, not evidence that the mapped features were caused or reactivated by the August 2026 event. The next useful step is to review feature classes and names, then decide whether a narrowly scoped elevation or imagery sample is justified.

## Water-protection proximity screen

The two AOI-intersecting drinking-water protection areas are legally established (`festgesetzt`):

- Oberstdorf Christlesee (`2210862700082`)
- Rubi (`2210852760001`)

Nearest-feature results:

| Georisk type | Total in AOI | Directly intersects TWSG | Within 100 m | Within 500 m |
|---|---:|---:|---:|---:|
| Detachment lines | 25 | 2 | 3 | 4 |
| Deposition polygons | 19 | 1 | 1 | 2 |

Interpretation details:

- Two intersecting detachment line segments in Rubi share object ID `8527GR000058` and class `Anbruchkante`; they should be treated as one mapped object represented by multiple segments, not two independent events.
- Another segment of that object is 51.8 m from Rubi, and object `8527GR000015` is 450.2 m away.
- The deposition polygon intersecting Oberstdorf Christlesee is object `8627GR015169`, class `Doline`; it is not classified as debris-flow deposition.
- A `Sturzablagerung` polygon, object `8627GR000016`, is 457.2 m from Oberstdorf Christlesee.

The complete 44-feature nearest-area table is exported as `data/outgoing/2026-08-06_oberstdorf-feasibility/risk_water_proximity.gpkg`.

This establishes spatial relevance for further investigation, especially at Rubi, but does not establish current activity, event causation, flow direction, or drinking-water impact.
