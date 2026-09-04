# Oberstdorf ancillary-data availability

Status checked: 2026-08-06

Purpose: identify ancillary datasets available from official Bavarian portals that a service provider can use to screen, support, and quality-control remote-sensing products for the Oberstdorf debris-flow / landslide request. This is not a hazard analysis and does not assess event causation.

AOI reference: Markt Oberstdorf, approximately 41.371 km2, working CRS EPSG:25832.

## Priority availability matrix

| Dataset | Portal availability | Access and burden | Use for service provider | Important limitation |
|---|---|---|---|---|
| DGM5 terrain model | Available for download | 1 km tiles, ASCII XYZ, about 0.2 MB/tile; polygonal selection available | First-choice terrain context, slope, drainage and broad geomorphology | 5 m grid may miss small scarps or narrow channels |
| DGM1 terrain model | Available for download | 1 km GeoTIFF/XYZ tiles, about 4 MB/tile; polygonal selection available | Detailed terrain, slope, flow-path and orthorectification support | Full AOI can reach hundreds of MB; select exact tiles only |
| DOP20 RGB orthophoto | Download and WMS available | 1 km GeoTIFF tiles, about 20-50 MB/tile; WMS for screening | High-resolution reference imagery, interpretation and positional QA | Not event-specific; acquisition date must be checked before change interpretation |
| DOP20 CIR / DOP40 RGB | Available | Tiled download and service options | Vegetation interpretation or lighter reference-imagery alternative | Not event-specific; tile volumes can still be high |
| Georisk objects | Available for direct download | Statewide EPSG:25832 Shapefile ZIP, measured 13.39 MiB | Existing landslide, rockfall, detachment and deposition inventory for interpretation context | Inventory is not proof of August 2026 activity |
| Geohazard indication maps | Download and WMS available | Statewide Shapefile ZIP measured 394.24 MiB; use WMS for initial screening | Regional susceptibility / hazard context | Bulk archive is unnecessarily large for this AOI; indication map, not event mapping |
| Drinking-water protection areas (`twsg`) | Available for direct download and map viewing | Statewide EPSG:25832 Shapefile ZIP, measured 4.31 MiB | Exposure and drinking-water protection context | Public data show area outlines, not individual legal zones; legally binding information comes from the competent authority |
| Heilquellenschutzgebiete (`hqsg`) | Available for direct download | Statewide EPSG:25832 Shapefile ZIP, measured 0.14 MiB | Additional protected-water screening where relevant | Relevance to this request should be checked before use |
| Surface runoff and flash-flood indications | Download and WMS available | WMS is practical; statewide downloads measured about 452 MiB to 1.00 GiB compressed | Potential flow paths, depressions and ponding context | Topographic screening only; no event probability, flow depth, velocity or building-level accuracy |
| Rivers and catchments | WMS available | `Grundlagen Fliessgewaesser` WMS, 4096 px maximum; river axes and catchments at 1:25,000 | Hydrographic context and catchment orientation | Catchments are dated 2016 and river basis is dated 2023; WMS is mainly for screening |
| Soil map ÜBK25 | Download and WMS available | Statewide GeoPackage download; WMS available | Soil / infiltration / erodibility context at regional scale | Reference scale 1:25,000; statements are not reliable beyond about 1:10,000 |
| Soil water-retention functions | WMS available | BFK25 thematic WMS | Screening of water-retention and soluble-substance residence characteristics | Coverage and thematic derivation must be checked; not a direct event product |
| Geological and engineering-geological maps | WMS available; selected LfU downloads available | dGK25 / dIGK25 WMS; LfU download catalog includes geological products | Lithology, superficial material and engineering-geology context | Overview mapping; inspect coverage and scale before production use |
| ATKIS Basis-DLM | WFS and statewide downloads available | AOI-filterable WFS preferred; statewide downloads are about 1.5-2 GB | Roads, hydrography, land cover and other exposure/reference features | Do not download statewide packages for this AOI |
| LoD2 buildings | Tiled and polygon download available | 2 km CityGML tiles, about 10-100 MB/tile | Building exposure and 3D context where required | Potentially large; building footprints from an AOI-filtered service may be more efficient |

## Access gaps

| Needed information | Public portal status | Provider action |
|---|---|---|
| Individual drinking-water protection zones and legally binding restrictions | Not contained in the public WSG outline download | Request authoritative information from the competent district authority |
| Water abstraction points / water-supply facilities | Not publicly accessible through the listed portal data | Obtain from the water supplier, LfU/WWA or competent authority as appropriate |
| Detailed drinking-water catchment delineations | Not guaranteed as a public download | Follow the LfU catchment-data guidance and submit a data request where no download exists |
| Event-specific post-disaster imagery | Not supplied by ordinary Bavarian DOP products | Service provider must source suitable post-event satellite/aerial imagery and verify acquisition date, cloud and terrain effects |
| Event rainfall | Not identified as a Bavarian geodata-portal download | Use DWD station/radar products or data supplied by the requester/provider |

## Recommended provider package

The minimum useful ancillary package is:

1. AOI KML and request PDF supplied with the activation.
2. DGM5 tiles for the AOI and a small context buffer; DGM1 only for priority locations or where detailed terrain is required.
3. Georisk objects and WSG outlines as lightweight vectors.
4. Surface-runoff, hydrography/catchments, geology and soils initially through WMS screening; download vectors only if they materially support production.
5. DOP imagery only after checking acquisition date and required tile volume; it should be treated as reference imagery, not assumed post-event evidence.
6. AOI-filtered ATKIS / building data only if the requested exposure product requires those features.
7. Authoritative water-supply zones, facilities and catchments from the responsible authorities where public portal data are insufficient.

## Resource guidance

- Prefer polygonal selection, exact tiles, WFS bounding-box filters or WMS previews.
- Avoid all statewide raster and exposure packages.
- Cache each acquired file and perform clipping and analysis locally.
- Record acquisition date, CRS, license, source URL and data vintage in the provider handoff.
- EPSG:25832 is directly supported by the principal Bavarian products and is appropriate for metric processing in this AOI.

## Official entry points

- Bavarian OpenData catalog: <https://geodaten.bayern.de/opengeodata/index.html>
- DGM5: <https://geodaten.bayern.de/opengeodata/OpenDataDetail.html?pn=dgm5>
- DGM1: <https://geodaten.bayern.de/opengeodata/OpenDataDetail.html?pn=dgm1>
- DOP20 RGB: <https://geodaten.bayern.de/opengeodata/OpenDataDetail.html?active=SERVICE&pn=dop20rgb>
- LoD2 buildings: <https://geodaten.bayern.de/opengeodata/OpenDataDetail.html?active=MASSENDOWNLOAD&pn=lod2>
- ATKIS Basis-DLM: <https://geodaten.bayern.de/opengeodata/OpenDataDetail.html?pn=atkis_basis_dlm>
- LfU download services: <https://www.lfu.bayern.de/umweltdaten/geodatendienste/index_download.htm>
- LfU WMS services: <https://www.lfu.bayern.de/umweltdaten/geodatendienste/index_wms.htm>
- Georisk feed: <https://www.lfu.bayern.de/gdi/dls/georisiken.xml>
- WSG feed: <https://www.lfu.bayern.de/gdi/dls/wsg.xml>
- Surface-runoff feed: <https://www.lfu.bayern.de/gdi/dls/oberflaechenabfluss.xml>
- Surface-runoff WMS: <https://www.lfu.bayern.de/gdi/wms/wasser/oberflaechenabfluss?>
- Rivers and catchments WMS: <https://www.lfu.bayern.de/gdi/wms/wasser/grundlagen_fliessgewaesser?>
- ÜBK25 feed: <https://www.lfu.bayern.de/gdi/dls/uebk25.xml>
- Drinking-water catchment data guidance: <https://www.lfu.bayern.de/wasser/trinkwassereinzugsgebieteverordnung/beschreibung_einzugsgebiet/index.htm>
- OpenData terms: <https://www.geodaten.bayern.de/odd/m/3/html/nutzungsbedingungen.html>
