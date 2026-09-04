# EMSN236 Final Report and Geodata Delivery Audit

Date: 2026-08-12
Revised: 2026-08-13 after independent re-verification. See
`2026-08-13-emsn236-audit-red-team-review.md` for the correction log. All figures
below have been reproduced twice through independent code paths.

## Scope

This note compares:

- `data/incoming/reports/EMSN236_Final_Report_v01.docx`
- `data/incoming/reports/EMSN236_Technical_Report_v01.docx`
- `data/incoming/geodata/GDB/EMSN236_FLEX_EPSG32629_v2.gdb`
- the four GeoTIFFs in `data/incoming/geodata/Raster/`

The geodata checks were read-only. The v2 geodatabase and rasters were treated as
the source of truth. Checks covered file readability, layer presence, feature
counts, schemas, attribute domains and nulls, geometry validity and duplication,
CRS, raster grids, checksums, statistics, class distributions, and agreement with
the final report.

## Executive conclusion

The final report is materially more complete than the first technical report and
contains the previously absent Product 3 and Product 4 descriptions, methods,
results, quality-control sections, figures, tables, and annex entries.

The delivery contains every **final geospatial deliverable identifiable from the
final report**: P1 polygons, the three P3 vector layers, the P4 secondary-process
polygons, and continuous and classified rasters for P2 and P4. The principal
feature counts and continuous-raster statistics agree with the report.

The delivery should nevertheless **not be accepted as fully quality-controlled
without correction or clarification**. The most important issues, in order of
severity:

1. **Four of the seven layers are silently unreadable on common GIS software.**
   `P03_LandDisplacement_A`, `P03_LandDisplacement_Horiz_P`,
   `P03_LandDisplacement_Vertic_P` and `P04_Erosion_Prone_A` are stored in FileGDB
   table format version 4 (ArcGIS Pro 3.2+). Any reader built on GDAL earlier than
   3.10 returns **zero features with no error message**. A recipient on an older
   QGIS or ArcGIS Pro sees four empty layers and has no way to know why.
2. `P04_Erosion_Prone_A` contains 622 invalid geometries out of 3,426 (18.16%).
3. `P01_Landslide_Map_A` contains 9 invalid geometries out of 2,289 (0.39%).
4. The report defines the Product 2 classification **three different and mutually
   incompatible ways** in a single subsection. The delivered classified raster
   matches only one of them.
5. All 1,750 P3 polygons classified as `newly triggered` have null `n_points`,
   vertical velocity, horizontal velocity, and displacement direction. This
   directly contradicts the report's stated quality check that "each polygon
   contains at least three measurement points (npoints >= 3)".
6. The `kmz_file` field of `P01_Landslide_Map_A` is blank in 2,250 of 2,289 records
   (98.3%), and the report's stated rule for assigning High confidence does not
   describe the delivered data: only 7 of the 90 High-confidence polygons intersect
   a field observation.
7. The delivered AOI polygon measures 13,953.87 km². The report cites the AOI as
   9,086.36 km² in one place and 9,079.01 km² in another. Every AOI-relative
   percentage in the report is therefore unreproducible from the delivered data.

## Report comparison

| Measure | Technical report | Final report |
|---|---:|---:|
| Words recorded in DOCX metadata | 17,374 | 28,114 |
| Tables in document XML | 26 | 46 |
| Embedded media files | 45 | 53 |
| P3 result and QC sections | Missing | Present |
| P4 result and QC sections | Missing | Present |

The final report adds, among other material:

- P3 SBAS methodology and processing phases;
- P3 vertical and East-West point results;
- P3 deformation-area polygon results;
- P3 processing, topology, attribution, accuracy, and validation checks;
- P4 RUSLE methodology and susceptibility results;
- P4 secondary-process analysis and vector output;
- P4 quality-control content;
- P3 and P4 entries in the data-model annex.

### Editorial and internal-consistency issues in the final report

- The data-source section still says P3 and P4 "remain under development," despite
  their completed sections and delivered datasets.
- The P4 QC caption says `P4-QC01 to P3-QC32`; the ending code should be `P4-QC32`.
- Three table numbers are duplicated: **Table 11** ("Batch Job list applied" and
  "Erosion categories"), **Table 19** ("Distribution of coherent deformation
  polygons by activity status" and "Event erosion statistics"), and **Table 30**
  (the P3 and P4 QC summaries). Tables 3, 20, 21 and 33 are absent from the
  sequence. These are cached Word `SEQ` field results, so the fix is to update the
  document fields rather than to edit the captions by hand.
- P4 QC headings include duplicated numbering such as `4.1.4.1 4.1.2.1` (and
  likewise `4.1.4.2 4.1.2.2`, `4.1.4.3 4.1.2.3`).
- The P3 independent-validation heading is hardcoded as `4.1.3.4.2` although it
  appears under section 4.1.3.5 and is absent from the table of contents.
- The deliverables overview names the P2 classified raster as
  `EMSN236_FLEX_AOI01_P01_MOD_ERO_Class.tif`; the delivered file uses `P02`, which
  is logically correct.
- The overview describes the P4 continuous raster as 10 m; the annex and the
  delivered raster are 20 m.
- The annex documents only the P2 continuous raster and only the P4 classified
  raster, rather than both continuous/classified files for each product.
- The annex describes raster compression as `None`. This is correct for three of
  the four files, but `EMSN236_FLEX_AOI01_P02_MOD_ERO.tif` — the one continuous
  raster the annex actually documents — is LZW-compressed.
- The P4 annex says the classified raster is float; the delivered classified raster
  is Byte, which is more appropriate for classes 1–5.
- The P4 annex assigns the unit `ton/ha/yr` to the classified raster, which holds
  class codes 1–5 and has no physical unit.
- The P4 total-estimated-soil-loss figure is written as `2.44 x 10^6 ton/ha/yr`; a
  total derived from pixel area should be expressed as tonnes/year, while pixel
  values remain tonnes/ha/year.
- The annex documents the P4 vector thematic field as `Class`; the delivered field
  is named `Clase`.

## Delivered data inventory and readability

### File geodatabase v2

All seven tables/layers are present and, with a sufficiently recent reader, fully
readable:

| Layer/table | Geometry | Records | Report status |
|---|---|---:|---|
| `EMSN236_data_source` | None | 5 | Supporting metadata |
| `EMSN236_AOI_UTM29N` | MultiPolygon | 1 | Supporting AOI |
| `P01_Landslide_Map_A` | MultiPolygon | 2,289 | Count matches |
| `P03_LandDisplacement_A` | MultiPolygon | 5,019 | Count matches |
| `P03_LandDisplacement_Horiz_P` | Point | 266,433 | Count matches |
| `P03_LandDisplacement_Vertic_P` | Point | 323,626 | Count matches |
| `P04_Erosion_Prone_A` | MultiPolygon | 3,426 | Count matches |

All spatial layers use EPSG:32629 (WGS 84 / UTM zone 29N), matching the report and
the filenames. Their extents fall within the delivered AOI bounding box.

#### Reader compatibility — the most serious delivery defect

The seven tables are not stored in a uniform format. Reading the version byte from
each `.gdbtable` header:

```
a000000b4.gdbtable  ver=3   EMSN236_data_source
a000000bc.gdbtable  ver=3   EMSN236_AOI_UTM29N
a000000bd.gdbtable  ver=3   P01_Landslide_Map_A
a000000be.gdbtable  ver=4   P03_LandDisplacement_A
a000000bf.gdbtable  ver=4   P03_LandDisplacement_Horiz_P
a000000c0.gdbtable  ver=4   P03_LandDisplacement_Vertic_P
a000000c1.gdbtable  ver=4   P04_Erosion_Prone_A
```

Format version 4 is written by ArcGIS Pro 3.2 and later. Support for reading it
landed in GDAL 3.10, which means QGIS 3.40 and later. Behaviour across readers:

| Layer | GDAL 3.8.4 | GDAL 3.9.3 | GDAL 3.10.3 | GDAL 3.12.2 |
|---|---:|---:|---:|---:|
| `P01_Landslide_Map_A` | 2,289 | 2,289 | 2,289 | 2,289 |
| `P03_LandDisplacement_A` | 0 | 0 | 5,019 | 5,019 |
| `P03_LandDisplacement_Horiz_P` | 0 | 0 | 266,433 | 266,433 |
| `P03_LandDisplacement_Vertic_P` | 0 | 0 | 323,626 | 323,626 |
| `P04_Erosion_Prone_A` | 0 (with error) | 0 | 3,426 | 3,426 |

The failure mode matters as much as the failure: GDAL 3.9.x reports the four layers
as **empty and raises no error at all**. A recipient has no signal that anything is
wrong, and will reasonably conclude that P3 and P4 were not delivered.

The v2 directory also contains four orphaned pairs of `_temp.gdbtable` /
`_temp.gdbtablx` files (`a000000be` through `a000000c1`), absent from v1. Their
modification times post-date the tables they shadow, which is the signature of an
interrupted ArcGIS compact or compress operation. They add roughly 46 MB to the
package. Testing confirmed they are **not** the cause of the read failures —
removing them does not change the result on GDAL 3.9.3 — but they should not ship.

The project `bin/inspect` command currently fails on this geodatabase because
`EMSN236_data_source` is non-spatial and `llm_gis/inspect.py` assumes every
enumerated layer has at least one geometry field. `ogrinfo -json` emits
`"geometryFields": []` for that table, and `llm_gis/inspect.py:19` indexes
`layer.get("geometryFields", [{}])[0]`, where the default never fires on an empty
list. Same pattern at `llm_gis/inspect.py:77` and `:90`. This is an inspector
implementation limitation, not evidence that the geodatabase is unreadable.

### Rasters

All four GeoTIFFs are readable through both `bin/inspect` and full GDAL
checksum/statistics scans.

| Raster | Type | NoData | Size | Pixel | Compression | Valid coverage | Range |
|---|---|---:|---:|---:|---|---:|---:|
| `EMSN236_FLEX_AOI01_P02_MOD_ERO.tif` | Float32 | -9999 | 5,913 × 6,760 | 20 m | LZW | 35.66% | 0 to 47.6143 |
| `EMSN236_FLEX_AOI01_P02_MOD_ERO_Class.tif` | Int16 | -9999 | 5,913 × 6,760 | 20 m | None | 35.66% | 1 to 5 |
| `EMSN236_FLEX_AOI01_P04_MOD_EROSUSC.tif` | Float32 | -9999 | 5,913 × 6,760 | 20 m | None | 56.11% | 0.000198 to 329.4135 |
| `EMSN236_FLEX_AOI01_P04_MOD_EROSUSC_Class.tif` | Byte | 0 | 5,913 × 6,760 | 20 m | None | 56.11% | 1 to 5 |

All four rasters have EPSG:32629, the same origin, dimensions, extent, and
effectively identical 20 m geotransforms. Each continuous/classified pair has
identical valid coverage. This is a coherent raster grid model suitable for direct
overlay, and it is the strongest part of the delivery.

## Product-by-product checks

### Product 1

The delivered feature count (2,289) and the four instability classes match the
report:

- Low: 778
- Moderate: 701
- High: 431
- Very High: 379

Confidence values use the expected High/Medium/Low domain (90 / 628 / 1,571), and
the 90 High-confidence features match the report. Common identifiers are
consistently populated as EMSN236, FLEX, AOI 01, Portugal, and Flood.
`instability_level`, `main_evidence` and `confidence_level` are fully populated.

Findings:

- **9 polygons fail GEOS validity** due to ring self-intersections. There are no
  null or empty geometries.
- **`kmz_file` is blank in 2,250 of 2,289 records (98.3%)**; only 39 polygons carry
  a field-evidence reference.
- `field_evidence_distance_m` is non-null everywhere, but values run from 0 to
  **81,540 m**. Exactly 39 records have distance 0 — the same 39 that carry a
  `kmz_file`. For 98.3% of the layer the nearest field observation is elsewhere,
  in some cases 81 km away.
- **The report's High-confidence rule does not describe the delivered data.** The
  report states that High confidence was "exclusively assigned to 90 critical
  structures ... confirmed simultaneously by at least two concurrent SAR parameters
  ... that directly intersect with a user-provided field observation polygon."
  Cross-tabulating confidence against field evidence:

  | Confidence | With field evidence | Without |
  |---|---:|---:|
  | High | 7 | 83 |
  | Medium | 0 | 628 |
  | Low | 32 | 1,539 |

  Only 7 of 90 High-confidence polygons intersect a field observation, while 32
  Low-confidence polygons do.
- `geom_Length` and `geom_Area` are **null in all 2,289 records**.
- Measured areas differ slightly from the report: Very High covers 719.06 km²
  against the reported 723.57 km² (-0.6%); total mapped instability is 1,532.27 km².
  The internal ratios reproduce exactly (Very High = 46.93% of mapped area), which
  suggests the report's absolute areas were taken from a marginally earlier
  geometry version.

### Product 2

Both a continuous and a classified raster are delivered and readable, although the
annex lists only the continuous raster.

The continuous raster reproduces the report's key statistics:

- valid/eroded cells: 14,252,573 exactly;
- valid area: 570,102.92 ha, reported as 570,103 ha;
- mean: 0.007191 ton/ha, reported as 0.0072 ton/ha;
- maximum: 47.6143 ton/ha, reported as 47.61 ton/ha;
- area-weighted total: approximately 4,099.73 tonnes, reported as 4,100 tonnes.

The classified raster contains only values 1–5, distributed as:

| Class value | Cells | Share |
|---:|---:|---:|
| 1 | 285,052 | 2.000% |
| 2 | 3,278,092 | 23.000% |
| 3 | 3,563,143 | 25.000% |
| 4 | 3,563,144 | 25.000% |
| 5 | 3,563,142 | 25.000% |

**The report defines this classification three incompatible ways within a single
subsection:**

1. The prose lead-in: "classified into five categories based on the percentiles of
   the observed distribution **(P75, P90, P99, P99.9)**".
2. The bullet list immediately following: fixed thresholds `<0.001 / 0.001–0.01 /
   0.01–0.1 / 0.1–1.0 / >1.0 ton/ha`, with shares of roughly 75% / 16% / 8% / 1% /
   0.05%. The executive summary repeats these shares.
3. Table 11 "Erosion categories": **quartiles** — `0 / <Q25 / Q25–Q50 / Q50–Q75 /
   >Q75`.

The delivered raster matches only definition 3, and matches it exactly: 2.00% of
eroded cells are exactly zero ("No Change"), the remainder of the first quartile is
23.00%, so classes 1 and 2 sum to 25.00% and classes 3, 4 and 5 are 25.00% each.

The intended authoritative classification must be identified, and either the raster
regenerated or the prose, executive summary, category table and symbology revised so
they all agree.

### Product 3

The three expected vector layers are present, readable (on GDAL 3.10+), have no
duplicate point coordinates or duplicate polygon geometries, and contain no invalid,
null, or empty geometries.

The principal report claims are reproduced:

- vertical points: 323,626; velocity -5.10 to +0.66 mm/year; mean -1.2524 mm/year;
- horizontal points: 266,433; velocity -2.81 to +0.51 mm/year; mean -1.2195 mm/year;
- polygons: 5,019 covering 851.2469 km²;
- activity status: 2,512 pre-existing, 757 reactivated, 1,750 newly triggered;
- confidence: 946 High, 2,378 Medium, 1,695 Low.

The point-layer schemas match the annex, and **every field of both point layers is
non-null across all 590,059 records**. The published distributions also reproduce
exactly: vertical displacement direction 88.74% subsidence / 10.48% stable / 0.78%
uplift; vertical confidence 41.17% Medium and 28.98% High; horizontal deformation
class 96.52% Low and 3.48% Moderate (9,259 points); horizontal confidence 46.38%
Medium and 21.89% High. Domains are coherent with the report:
Stable/Subsidence/Uplift for vertical direction, Stable/Eastward/Westward movement
for horizontal direction, Low/Moderate/High deformation, and Low/Medium/High
confidence.

The polygon layer, however, contradicts a stated quality check. The report's P3 QC
section asserts:

> "Attribute-geometry conformance: each polygon contains at least three measurement
> points (npoints >= 3), ensuring that the velocity statistics are derived from a
> valid sample."

Measured:

- **all 1,750 `newly triggered` polygons (34.87% of the layer) have null
  `n_points`, `velocity_vertical`, `velocity_horizontal`, and
  `displacement_direction`** — the `npoints >= 3` claim is false for more than a
  third of the layer;
- an additional 413 polygons lack vertical velocity and 2,360 additional polygons
  lack horizontal velocity;
- overall, 2,163 polygons lack vertical velocity and 4,110 lack horizontal velocity;
- where `n_points` is populated (3,269 records) it does run from 3 to 1,806, so the
  rule holds wherever the attribute exists.

Null component velocities can be legitimate where one orbital component is
unavailable, but the complete absence of measurement attribution for every newly
triggered polygon indicates that these features follow a different derivation path,
apparently from P1 footprints. The report should define this conditional model
explicitly and correct the conformance claim. If newly triggered polygons are meant
to be measurement-derived P3 deformation areas, the null records require correction.

Note: `n_points` is stored as Real/Double, which matches Annex 1. This is a schema
design preference, not an inconsistency.

### Product 4

The continuous and classified susceptibility rasters reproduce the report closely,
and unlike Product 2 the classification is internally consistent — the report's
Stone and Hilborn (2015) fixed thresholds (6.7 / 11.2 / 22.4 / 33.6 ton/ha/yr) yield
the delivered distribution:

- continuous mean: 2.71598 ton/ha/year, reported as 2.72;
- continuous maximum: 329.4135 ton/ha/year, reported as 329.41;
- valid area: 897,113.88 ha;
- implied total annual loss: approximately 2.437 million tonnes/year, consistent
  with the reported 2.44 million after correcting the report's unit;
- class shares: 87.434%, 7.400%, 4.160%, 0.684%, and 0.321%, matching the reported
  87.4%, 7.4%, 4.2%, 0.7%, and 0.3%.

The vector layer contains 3,426 polygons with a stored area of 22,703.88 ha,
matching the report's 3,426 zones and 22,704 ha. Computed geometry area agrees with
the stored value. No fields are null.

Data-model findings:

- **622 of the 3,426 polygons are invalid**, mainly from ring self-intersections
  and disconnected interiors;
- the only product-specific thematic field is named `Clase` rather than the annex's
  `Class`, and uses Spanish naming in an otherwise English/lowercase model;
- every record has `Clase = 1`, so the field does not distinguish process type,
  susceptibility, or severity and adds little information.

### Area of interest

`EMSN236_AOI_UTM29N` contains a single MultiPolygon with
`Shape_Area = 13,953,869,786.7 m²` = **13,953.87 km²**; the computed geometry area
agrees. The final report cites the AOI twice, with two different values, neither of
which matches:

- "the entire AoI, which encompasses a total surface of **9086.36 km2**";
- "9.38% of the total AoI surface (**9,079.01 km2**)".

Consequently no AOI-relative percentage in the report can be reproduced from the
delivered data:

| Claim | Report | Against delivered AOI |
|---|---:|---:|
| P1 instability, all classes, share of AOI | 16.97% | 10.98% |
| P1 Very High, share of AOI | 7.96% | 5.15% |
| P3 deformation polygons, share of AOI | 9.38% | 6.10% |

The ~9,080 km² figure is close to the P4 raster's valid extent (8,971 km²), so the
report may be using a land-only or data-extent denominator. That would be
defensible, but it is never stated, and the two cited values differ from each other.

### Geometry-validity claims in the QC documentation

The report contains one explicit prose statement of geometry cleanliness, in the
Product 3 section — "no self-intersections, null geometries, or dangling vertices
were detected ... the layer is GDB-valid" — and that statement is **true** of the
P3 polygon layer.

For Products 1 and 4 the report lists the checks performed (`P1-QC6`, `P1-QC19`,
`P4-QC8`, `P4-QC32`, all "Invalid geometries" / "Invalid geometry checks") without a
per-check result column. The pass claim that the delivered data contradicts is the
delivery-wide one in Table 36, "Topological consistency of vector layers → Vector
data topology → **Pass**", supported by Table 35 listing "Empty, unknown or invalid
geometry" as an automatic GDB topology rule. That declared Pass is inconsistent with
9 invalid P1 polygons and 622 invalid P4 polygons.

## Availability boundary

All **final deliverables** in the report are present. The incoming delivery does not
include intermediate or source datasets discussed in the methodology, such as
Sentinel-1/Sentinel-2 stacks, R/K/LS/C/RH factor rasters, EGMS validation points,
municipality KMZ observations, DEM, land-cover masks, or intermediate
coherence/backscatter products. `EMSN236_data_source` contains five metadata records
but not the source datasets themselves and does not list all sources discussed in
the report.

If the contract requires reproducibility or delivery of intermediate/validation
data — not only final products — those materials are missing from this incoming
package and must be requested separately.

## Recommended acceptance actions

1. **Resolve the reader-compatibility defect.** Either re-export
   `P03_LandDisplacement_A`, `P03_LandDisplacement_Horiz_P`,
   `P03_LandDisplacement_Vertic_P` and `P04_Erosion_Prone_A` in FileGDB table format
   version 3, or state a minimum supported reader of GDAL 3.10 / QGIS 3.40 / ArcGIS
   Pro 3.2 prominently in the delivery documentation. Removing the `_temp` files
   does not address this.
2. Repair and revalidate the 9 invalid P1 polygons and 622 invalid P4 polygons, then
   rerun duplicate, topology, extent, and attribute checks. Reconcile the result
   with the declared Pass in Table 36.
3. Decide which of the three P2 classification definitions is authoritative.
   Regenerate the class raster or revise the prose, executive summary, category
   table, and symbology so they all agree.
4. Document or correct the P3 polygon nullability model, especially the 1,750 newly
   triggered records with no measurement attributes, and correct the
   "npoints >= 3" conformance claim.
5. Explain or correct `kmz_file`, blank in 98.3% of P1 records, and reconcile the
   stated High-confidence assignment rule with the 7 of 90 High-confidence polygons
   that actually intersect a field observation. Populate or drop the all-null
   `geom_Length` and `geom_Area` fields.
6. Reconcile the AOI area. State the denominator used for every AOI-relative
   percentage, and correct the two conflicting figures (9,086.36 and 9,079.01 km²)
   against the delivered 13,953.87 km² AOI polygon.
7. Rename `P04_Erosion_Prone_A.Clase` to the documented `Class` (or document the
   actual field) and define a meaningful domain; confirm whether a constant value of
   1 is intentional.
8. Correct the final-report editorial, filename, table-number, pixel-size,
   data-type, compression, and unit issues listed above. Table renumbering should be
   done by updating the Word `SEQ` fields, not by editing captions.
9. Remove the four orphaned `_temp.gdbtable`/`_temp.gdbtablx` pairs and compact the
   geodatabase through the producing GIS software (~46 MB of dead weight).
10. Fix `bin/inspect` so non-spatial FileGDB tables do not cause an `IndexError`;
    this is a tooling issue on our side, separate from delivery acceptance.
11. If reproducibility is in scope, request the intermediate factor layers, source
    imagery references, KMZ/EGMS validation inputs, and processing
    metadata/checksums.

## Verification method

- DOCX text and package metadata extraction by direct ZIP/XML inspection of
  `word/document.xml` and `docProps/app.xml`.
- Layer and schema enumeration with `ogrinfo` across GDAL 3.8.4 (host), 3.9.3,
  3.10.3 and 3.12.2 (containers).
- Geometry validity, attribute nulls, domains and aggregates computed two ways
  independently: OGR SQLite SQL with GEOS `ST_IsValid`, and feature-by-feature
  iteration through the GDAL Python bindings using `IsValid()`, `IsEmpty()` and
  `IsFieldNull()`. Both passes agree.
- Duplicate-coordinate and duplicate-geometry checks by coordinate rounding and WKB
  hashing.
- FileGDB table format versions read from the first four bytes of each `.gdbtable`
  header.
- Reader root cause isolated by removing the `_temp` files from a scratch copy and
  re-reading.
- Raster metadata through `bin/inspect`; full raster statistics, checksums and
  histograms recomputed in NumPy from full-array reads with `GDAL_PAM_ENABLED=NO`,
  not from cached `gdalinfo` statistics.

No source data were modified, ingested, archived, or moved.
