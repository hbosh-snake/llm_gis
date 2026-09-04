# Pre-event vegetation product: input-access and feasibility assessment

Assessment date: 2026-09-03  
Target event start: 2026-07-17  
Inputs reviewed:

- `data/incoming/Product 1 Pre event Vegetation.txt`
- `data/incoming/relevant_datasets.txt`
- `data/incoming/activation_363642ba-2983-47be-a17c-7e0d5263ab2c.kml`

## Executive conclusion

The requested product is technically feasible. The subsequently supplied AOI has been validated, FKB-AR5 portrayal coverage has been confirmed, and suitable pre-event Sentinel-2 imagery exists. Production still depends on obtaining an editable FKB-AR5 extract with adequate reuse/delivery rights and, if individual trees and narrow vegetation features are mandatory, appropriately licensed very-high-resolution (VHR) imagery.

The recommended data architecture is:

1. Obtain an editable/vector extract of FKB-AR5 for the AOI and use its attributes and code lists as the primary semantic reference.
2. Use atmospherically corrected Sentinel-2 Level-2A imagery acquired before 2026-07-17 as the open baseline for quantitative vegetation indicators and broad vegetation updates. Select the closest acceptably cloud-free acquisition only after receiving the AOI.
3. If the requirement truly includes hedges, shrubs, individual trees, and vegetation immediately around buildings, procure suitably licensed very-high-resolution (VHR) multispectral imagery close to the event date. Sentinel-2's 10/20 m pixels cannot reliably resolve individual trees or narrow features.
4. Use Copernicus Land Monitoring Service (CLMS) layers as ancillary/comparison evidence only. The suggested layers are valuable but their reference dates do not describe conditions immediately before the July 2026 fire.

## Area of Interest

- Source of truth: `data/incoming/activation_363642ba-2983-47be-a17c-7e0d5263ab2c.kml`
- Selected layer: `Layer #0` (the file contains only one layer)
- Content: one valid inspectable `PolygonZ`
- CRS: EPSG:4326, status `ok`
- Bounding box: 10.0243023125–10.0534193590°E, 59.7557153437–59.7685412617°N
- Projected footprint: approximately 1,725,249 m² (172.5 ha), calculated in EPSG:3035
- CLMS/EEA 100 km reference-grid cell: `100kmE43N40`

EPSG:25832 (ETRS89 / UTM zone 32N) is the natural local projected CRS for metric production at this longitude. EPSG:3035 remains appropriate for comparison with pan-European CLMS grids and area statistics.

## Access verification

### Dedicated NIBIO FKB-AR5 WMS

- Catalogue: https://kartkatalog.geonorge.no/metadata/fkb-ar5-wms/b1966b1e-8920-4405-bf0e-b8e7394ec8d5
- GetCapabilities: https://wms.nibio.no/cgi-bin/ar5?SERVICE=WMS&VERSION=1.3.0&REQUEST=GetCapabilities
- Live result on 2026-09-03: HTTP 200; valid WMS 1.3.0 XML; anonymous access; CORS enabled.
- The capabilities document advertises `Fees: no conditions apply` and `AccessConstraints: none` for this portrayal service.
- The service exposes queryable AR5 portrayals including `Arealtype`, `Bonitet`, `Skogbonitet`, and `Jordbruksareal`; it supports Norwegian ETRS89/UTM zones and common geographic/web CRSs.
- A real `GetMap` request at a Norwegian large-scale test extent returned a non-empty PNG.
- An AOI-specific `GetMap` request returned complete, non-empty coverage across the supplied polygon extent.
- Suitability: useful for visual interpretation, legend/style checking, and spot queries. It is a rendered WMS, not a dependable replacement for an editable polygon dataset with complete AR5 attributes, topology, stable identifiers, and metadata.

### General FKB WMS

- Catalogue: https://kartkatalog.geonorge.no/metadata/fkb-wms/84178e68-f40d-4bb4-b9f6-9bfdee2bcc7a
- GetCapabilities: https://wms.geonorge.no/skwms1/wms.fkb?service=wms&request=getcapabilities
- Live result on 2026-09-03: HTTP 200; valid WMS 1.3.0 XML; anonymous access; CORS enabled.
- The capabilities document declares `Fees: Norge digital` and `AccessConstraints: Copyright Statens kartverk`.
- Its `ar5` portrayal has a maximum scale denominator of 1:12,000. A real large-scale `GetMap` request returned a non-empty PNG.
- An AOI-specific request returned non-empty AR5 portrayal over approximately 94% of the rectangular request image; transparent pixels may represent uncategorised/background portions and do not establish a gap in the underlying vector data.
- Suitability: useful supplementary backdrop/reference at large scales. It must not be treated as permission to extract, redistribute, or derive a deliverable from restricted FKB components. Project-specific rights must be confirmed with the data owner/provider.

### Editable FKB-AR5 data and licensing

The current FKB-AR5 5.1 product specification describes a vector dataset and the AR5 schema, including `arealtype`, `treslag`, `skogbonitet`, `grunnforhold`, `klassifiseringsmetode`, and `verifiseringsdato`. Its specification text is published under NLOD, but that does not by itself establish that every production-data download is open to this service provider. Older official product material explicitly states that downloads require a licence and are restricted to Geovekst/Norge digital parties; the live general FKB WMS still advertises Norge digital restrictions.

Therefore:

- WMS viewing is confirmed.
- Unauthenticated editable-vector access was not established from the URLs in the email.
- Before production, obtain written confirmation that the contractor may download, process, create derivatives from, and deliver the AOI extract, including the exact attribution and redistribution conditions.
- If entitlement cannot be secured, AR5 WMS, its public specification, and code lists can guide the semantic design, but a WMS-only workflow will not meet the request to update FKB-AR5 geometry and produce class statistics with adequate traceability.

## Satellite imagery feasibility

### Sentinel-2 Level-2A: recommended open baseline

Copernicus Sentinel-2 L2A is available through the Copernicus Data Space Ecosystem, with catalogue and processing/download APIs. It provides bottom-of-atmosphere reflectance, visible/NIR bands at 10 m, vegetation red-edge and SWIR bands at 20 m, plus scene classification/cloud information. This supports NDVI and red-edge/SWIR indicators, vegetation/non-vegetation separation, broad condition assessment, and some forest/grassland/cropland discrimination.

An anonymous STAC query for the AOI and 2026-06-17 through 2026-07-17 returned 18 intersecting L2A products, all in MGRS tile `32VNM`. Catalogue discovery and preview access worked without authentication. Direct full-product download returned HTTP 401, consistent with the need for a free Copernicus Data Space account/token rather than a data-licensing restriction.

Closest candidates:

| Acquisition (UTC) | Days before fire | Tile cloud metadata | AOI preview assessment | Role |
|---|---:|---:|---|---|
| 2026-07-15 10:36:21 | 2 | 69.11% | Cloud-obscured over the AOI | Reject as primary |
| 2026-07-13 10:46:19 | 4 | 37.44% | AOI appears clear despite tile-wide cloud | Primary candidate |
| 2026-07-10 10:36:19 | 7 | 5.40% | AOI appears clear; small nearby clouds | Supporting candidate |
| 2026-07-10 10:50:51 | 7 | 5.68% | AOI appears clear; small nearby clouds | Supporting candidate |

The 13 July scene is presently the best primary candidate because it is closest to the event while visually clear over the AOI. This is a preview-level assessment; final selection must use the native-resolution SCL/cloud-probability bands and reflectance imagery clipped to the AOI.

Limitations:

- Tile-level cloud percentage is only a first filter; cloud and shadow must be assessed over the AOI.
- A single acquisition close to 2026-07-17 may be cloudy. The method should allow a short pre-event window and document whether the primary reference is one scene or a carefully controlled composite.
- Individual trees, narrow hedges, small shrubs, and building-edge vegetation are below or near the practical detection limit. Resampling does not create detail.

Suggested selection order after AOI receipt:

1. Query all L2A acquisitions before 2026-07-17, initially over approximately 30 days.
2. Rank by temporal proximity, AOI-level usable-pixel percentage, haze, cloud shadow, snow, view geometry, and radiometric completeness.
3. Prefer one closest high-quality scene as the stated product reference date. Use additional recent acquisitions only to fill cloud gaps or strengthen interpretation, documenting the temporal logic.
4. If no acceptable optical observation exists, add Sentinel-1 SAR as cloud-independent supporting evidence, while retaining an optical image for spectral vegetation characterization where possible.

### VHR imagery: required for the finest requested detail

The product wording asks for smaller vegetation elements, potentially including individual trees around buildings. That is not a defensible guaranteed output from 10 m Sentinel-2 imagery. A sub-metre to roughly 2 m, orthorectified, multispectral acquisition close to 2026-07-17 is needed for reliable crown/hedge delineation. Access, acquisition date, cloud cover, cost, derived-product rights, and redistribution terms must be checked against an identified commercial or authorised national source once the AOI is known.

### CLMS comparison layers

The email does not identify a specific CLMS dataset. The most relevant candidates are:

- Small Woody Features 2021: downloadable vector and 5 m raster data for Europe, intended for hedgerows, shrubs, and woody patches outside forest. It is valuable as a detection prior/comparison, but it is five years too old to establish pre-fire 2026 condition. The AOI lies in EEA reference-grid cell `100kmE43N40`. The two Norwegian gaps (`NO116` and `NO119`) documented by CLMS apply to the 2015 product; the current CLMS technical table reports full EEA38 + UK coverage for the 2018 and 2021 versions. Exact downloadable-file selection should therefore be checked by grid cell/account, but the AOI is not excluded by the published 2021 coverage statement.
- Tree Cover Density / Dominant Leaf Type / Forest Type: 10 m pan-European status layers with useful forest structure/leaf-type information. These can support cross-checking and model features, but their annual/reference-year products are not substitutes for a near-event image.
- European Image Mosaic: useful visually, but VHR editions are provided as web map services and are not downloadable because they primarily use commercial imagery. They are unsuitable as the sole reproducible analysis input.

CLMS products are generally free of charge, but each selected product's data policy, citation, coverage, version, and temporal reference must be recorded in the final report.

## Proposed product method

After data rights and download credentials are resolved:

1. Acquire the latest permissible FKB-AR5 vector extract and retain original IDs, AR5 codes, source, capture method, positional quality, and verification date.
2. Select the closest usable pre-event Sentinel-2 L2A scene; perform AOI-level cloud/shadow/snow masking and retain native reflectance values.
3. Calculate at least NDVI and complementary red-edge/SWIR vegetation indicators; use multitemporal context to distinguish persistent land cover from short-lived phenological/radiometric variation.
4. Treat AR5 as the semantic hierarchy, not as infallible ground truth. Flag spatial or thematic disagreements and preserve provenance for unchanged, modified, and newly delineated objects.
5. Use object-based or supervised classification plus manual photo-interpretation/QC. Do not automatically transfer a spectral cluster into an AR5 class where the AR5 definition depends on field-observed or production-capacity properties that imagery cannot prove.
6. Add VHR-derived subclasses/features only where imagery and validation support them. Store each additional class's parent AR5 class and detection confidence.
7. Define MMU only after imagery selection: it must reflect native resolution, positional uncertainty, feature type, and intended mapping scale. Use a coarser MMU for Sentinel-2-derived polygons and a smaller, separately documented MMU for VHR features.
8. Validate geometry and semantics with stratified samples, confusion/error reporting, boundary checks, and expert review. Explicitly mark uncertain interpretations.
9. Produce class-area statistics, change/update statistics, source-date metadata, confidence/quality fields, and a limitations report.

## Decision

Status: **feasible with identified inputs; production access conditions remain**.

The AOI is now valid and covered by both AR5 portrayals. A viable Sentinel-2 primary candidate exists on 2026-07-13, four days before the fire, with two clear-looking 2026-07-10 supporting acquisitions. The product can proceed if (a) editable FKB-AR5 reuse and delivery rights are confirmed or a legally adequate alternative is agreed, (b) Copernicus credentials are provided/created for native product download, and (c) imagery expectations are aligned with resolution: Sentinel-2 for quantitative broad vegetation condition, VHR imagery for individual/small vegetation features. CLMS adds context and comparison but cannot supply the required near-event reference date.

## Primary references

- FKB-AR5 5.1 product specification: https://dokument.geonorge.no/produktspesifikasjoner/fkb-ar5/Versjon%205.1/index.html
- NIBIO AR5 classification system: https://www.nibio.no/tema/jord/arealressurser/arealressurskart-ar5/klassifikasjonssystem-ar5
- Copernicus Data Space Sentinel-2 L2A documentation: https://documentation.dataspace.copernicus.eu/APIs/SentinelHub/Data/S2L2A.html
- Copernicus Data Space STAC catalogue documentation: https://documentation.dataspace.copernicus.eu/APIs/STAC.html
- Copernicus Data Space terms: https://dataspace.copernicus.eu/terms-and-conditions
- CLMS Small Woody Features 2021: https://land.copernicus.eu/en/products/high-resolution-layer-small-woody-features/small-woody-features-2021
- CLMS Tree Cover Density 2021: https://land.copernicus.eu/en/products/high-resolution-layer-forests-and-tree-cover/tree-cover-density-2021-raster-10-m-100-m-europe-yearly
- CLMS European Image Mosaic: https://land.copernicus.eu/en/products/european-image-mosaic
