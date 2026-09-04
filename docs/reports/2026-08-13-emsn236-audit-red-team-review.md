# Red-team review of the EMSN236 delivery audit

Date: 2026-08-13

Subject: independent re-verification of `docs/reports/2026-08-12-emsn236-final-delivery-audit.md`.

Every quantitative claim in the prior audit was re-derived from scratch against the
same source files, using a separate script path (GDAL Python bindings rather than
OGR SQL) and three GDAL versions (3.8.4 host, 3.9.3, 3.10.3, 3.12.2 containers).
No source data were modified. The geodatabase was copied to a scratchpad only for
the write-mode reader experiment; `data/incoming/` was untouched.

## Verdict

The audit's **substantive data findings are correct and reproduce exactly**. Every
feature count, geometry-validity count, attribute null count, area, and raster
statistic matched to the last reported digit.

Three problems, in decreasing order of importance:

1. **Finding 5 is wrong on its central fact**, and its stated root cause is
   disproven. This changes the recommended remedy.
2. **A "clean" claim in Product 1 is false** — the audit reports a field as
   populated that is 98.3% empty.
3. Several report-vs-data contradictions of equal or greater severity were missed,
   including one that invalidates every AOI-relative percentage in the report.

The audit's overall acceptance recommendation still stands. The corrections below
change what the producer must be asked to fix.

---

## 1. Finding 5 is wrong: the reader boundary is GDAL 3.10, not 3.9.3

The audit states that "the repository's pinned GDAL 3.9.3 environment reads them
successfully" and that older readers fail.

**GDAL 3.9.3 does not read them.** It returns zero features for all four P3/P4
layers, silently, with no error:

| Layer | 3.8.4 (host) | 3.9.3 | 3.10.3 | 3.12.2 |
|---|---:|---:|---:|---:|
| `P01_Landslide_Map_A` | 2,289 | 2,289 | 2,289 | 2,289 |
| `P03_LandDisplacement_A` | 0 | **0** | 5,019 | 5,019 |
| `P03_LandDisplacement_Horiz_P` | 0 | **0** | 266,433 | 266,433 |
| `P03_LandDisplacement_Vertic_P` | 0 | **0** | 323,626 | 323,626 |
| `P04_Erosion_Prone_A` | 0 (+error) | **0** | 3,426 | 3,426 |

The audit's own numbers therefore cannot have come from GDAL 3.9.3. They are
correct — they match 3.10.3 and 3.12.2 exactly — but the "Verification method"
section misattributes them. The likely explanation: `docker/agent/Dockerfile` was
pinned to `gdal:ubuntu-small-3.9.3` at the last commit, but the built
`llm-gis-agent:latest` image is **GDAL 3.12.2**, and the Dockerfile now carries an
uncommitted bump to 3.12.2. The audit read the pin, not the image.

### Root cause, which the audit did not establish

The FileGDB table header version byte separates the layers cleanly:

```
a000000b4.gdbtable  ver=3   EMSN236_data_source
a000000bc.gdbtable  ver=3   EMSN236_AOI_UTM29N
a000000bd.gdbtable  ver=3   P01_Landslide_Map_A
a000000be.gdbtable  ver=4   P03_LandDisplacement_A
a000000bf.gdbtable  ver=4   P03_LandDisplacement_Horiz_P
a000000c0.gdbtable  ver=4   P03_LandDisplacement_Vertic_P
a000000c1.gdbtable  ver=4   P04_Erosion_Prone_A
```

The four unreadable layers are stored in **FileGDB table format version 4**
(ArcGIS Pro 3.2+); the readable ones are version 3. OpenFileGDB gained version-4
support in GDAL 3.10. This is a format-version boundary, not a corruption or a
packaging accident.

### The `_temp` file hypothesis is disproven

The audit speculated that the `_temp.gdbtable`/`_temp.gdbtablx` files "may
contribute to compatibility differences." I removed all four `_temp.gdbtable`
files from a working copy and re-read with GDAL 3.9.3:

```
P01_Landslide_Map_A       Feature Count: 2289
P03_LandDisplacement_A    Feature Count: 0
P04_Erosion_Prone_A       Feature Count: 0
```

No change. The `_temp` files are unrelated to the read failure. They are still a
real housekeeping defect — leftovers from an interrupted ArcGIS compact/compress
(their mtimes post-date the tables they shadow, e.g. `a000000c0_temp.gdbtable`
18:44 vs `a000000c0.gdbtable` 17:57), and they inflate the package by ~46 MB — but
deleting them fixes nothing.

### Consequence for recommendation 6

Removing the temp artifacts will not broaden compatibility. The producer must
either declare **GDAL ≥ 3.10 / ArcGIS Pro ≥ 3.2** as the minimum, or re-export the
four layers in FileGDB table format version 3.

The severity is also understated. A silent zero-feature read is worse than an
error: a recipient on GDAL 3.9.x, QGIS 3.34–3.38, or ArcGIS Pro < 3.2 sees four
empty layers with no warning and may conclude the delivery is incomplete rather
than that their reader is too old.

---

## 2. Finding: `kmz_file` is 98.3% empty — the audit calls it populated

The audit states (Product 1 section): "The required thematic fields are present and
populated: `instability_level`, `main_evidence`, `confidence_level`,
`field_evidence_distance_m`, and `kmz_file`."

Measured on all 2,289 records:

- `kmz_file`: **39 populated, 2,250 blank (98.3%)**
- `geom_Length`: **null in all 2,289 records**
- `geom_Area`: **null in all 2,289 records**

`field_evidence_distance_m` is genuinely non-null in all 2,289 records, but the
values run from 0 to **81,540 m**. Exactly 39 records have distance 0 — the same 39
that carry a `kmz_file`. The field is a distance-to-nearest-evidence measure, and
for 98.3% of the layer that distance is non-zero, reaching 81 km.

### This exposes a report contradiction the audit missed

Final report, section on Product 1 confidence: the High Confidence tier was
"exclusively assigned to 90 critical structures ... confirmed simultaneously by at
least two concurrent SAR parameters ... **that directly intersect with a
user-provided field observation polygon**."

Cross-tabulating confidence against field evidence (`field_evidence_distance_m = 0`
and `kmz_file` set):

| Confidence | With field evidence | Without |
|---|---:|---:|
| High | **7** | **83** |
| Medium | 0 | 628 |
| Low | 32 | 1,539 |

Only 7 of the 90 High-confidence polygons intersect a field observation, and 32
Low-confidence polygons do. The stated assignment rule does not describe the
delivered data at all. This is a harder, more directly falsifiable contradiction
than several the audit did report, and it belongs in the acceptance actions.

---

## 3. Missed finding: the delivered AOI is 13,954 km²; the report cites 9,080 km²

`EMSN236_AOI_UTM29N` has one MultiPolygon with `Shape_Area = 13,953,869,786.7 m²`
= **13,953.87 km²** (geometry area agrees).

The final report cites the AOI twice, with two different values, neither matching:

- "the entire AoI, which encompasses a total surface of **9086.36 km2**"
- "9.38% of the total AoI surface (**9,079.01 km2**)"

Every AOI-relative percentage in the report is computed against a denominator that
is neither stated nor consistent with itself nor equal to the delivered AOI layer.
Recomputed against the delivered AOI polygon:

| Claim | Report | Against delivered AOI |
|---|---:|---:|
| P1 instability, all classes, share of AOI | 16.97% | 10.98% |
| P1 Very High, share of AOI | 7.96% | 5.15% |
| P3 deformation polygons, share of AOI | 9.38% | 6.10% |

The ~9,080 km² figure is close to the P4 raster's valid extent (8,971 km²), so the
report is plausibly using a land-only or data-extent denominator. That may be
legitimate — but it is never stated, the two cited values differ from each other,
and the reader cannot reproduce any of the percentages from the delivered AOI.

Also unreported: P1 area by class measures **719.06 km²** for Very High against the
report's 723.57 km² (-0.6%), and total mapped instability **1,532.27 km²**. The
internal *ratios* reproduce exactly (46.93% of mapped area), so the report's
absolute areas appear to come from a slightly earlier geometry version.

---

## 4. Finding 4 is right, but understates the problem

The audit says the report "contains two incompatible P2 classification
definitions." There are **three**, inside a single subsection:

1. Prose lead-in: "classified into five categories based on the percentiles of the
   observed distribution **(P75, P90, P99, P99.9)**".
2. The bullet list immediately after: fixed thresholds `<0.001 / 0.001–0.01 /
   0.01–0.1 / 0.1–1.0 / >1.0 ton/ha`, with shares ~75/16/8/1/0.05%.
3. Table 11 "Erosion categories": **quartiles** — `0 / <Q25 / Q25–Q50 / Q50–Q75 /
   >Q75`.

P75/P90/P99/P99.9 and Q25/Q50/Q75 are different schemes, and neither is the fixed-
threshold list. The delivered raster matches only Table 11, and the audit's
reasoning there is sound and worth preserving: 2.00% of eroded cells are exactly
zero ("No Change"), the remainder of the first quartile is 23.00%, so classes 1+2
sum to 25.00% and classes 3/4/5 are 25.00% each — an exact quartile split.

For contrast, Product 4 is internally consistent: the report's Stone & Hilborn
fixed thresholds (6.7 / 11.2 / 22.4 / 33.6 ton/ha/yr) produce 87.4/7.4/4.2/0.7/0.3%,
and the delivered raster gives 87.434/7.400/4.160/0.684/0.321%.

---

## 5. Finding 3 is right, and there is a direct quote that proves it

The audit says the P3 conditional null model "is not explained in the report and
conflicts with the general description." There is a sharper, explicitly
falsifiable statement in the P3 QC section:

> "Attribute-geometry conformance: **each polygon contains at least three
> measurement points (npoints >= 3)**, ensuring that the velocity statistics are
> derived from a valid sample."

1,750 of 5,019 polygons (34.87%) have `n_points` **null**. The claim is false for
more than a third of the layer. Confirmed: the 3,269 non-null values do run from
3 to 1,806, so the `>= 3` rule holds wherever the attribute exists.

One audit nit to drop: it flags `n_points` being stored as Real/Double as a defect.
Annex 1 documents `N_points` as `Double`. The data matches the documentation; this
is a schema design preference, not an inconsistency.

---

## 6. Smaller corrections to the audit

| Audit claim | Measured | Status |
|---|---|---|
| "both P2 rasters are LZW-compressed" | Only `P02_MOD_ERO.tif` is LZW. `P02_MOD_ERO_Class.tif`, and both P4 rasters, are uncompressed | **Wrong.** 1 of 4, not 2 |
| Embedded media 47 / 55 | **45 / 53** (`word/media/`, both counts) | Off by 2 each; the +8 delta is unaffected |
| "contradicts the report's statement that no invalid geometries were detected" (P1) | No P1-specific statement exists. The only such prose is in the **P3** section, and it is true of P3 | **Mis-sourced.** The real support is Table 36, "Topological consistency of vector layers → Pass" (delivery-wide), plus Table 35 listing "Empty, unknown or invalid geometry" as an automatic rule. Conclusion holds; attribution does not |
| "the report's QC claim that invalid-geometry checks passed" (P4) | Same. P4-QC8/P4-QC32 are *listed* without a per-check result column | Same correction |
| "Both the P3 and P4 QC summaries are labelled Table 30" | True — but so are **Table 11** ("Batch Job list applied" and "Erosion categories") and **Table 19** ("Distribution of coherent deformation polygons" and "Event erosion statistics"). Tables 3, 20, 21, 33 are absent from the sequence | **Incomplete.** Caveat: these are cached Word `SEQ` field results and would renumber on a field update, so the fix is "update fields", not "edit the captions" |

Everything else in the audit's editorial list verified verbatim: `P4-QC01 to
P3-QC32`; "remain under development" for both P3 and P4;
`EMSN236_FLEX_AOI01_P01_MOD_ERO_Class.tif` in the deliverables overview; heading
`4.1.4.1 4.1.2.1 Visual Checks` (and .2, .3); hardcoded `4.1.3.4.2` sitting under
section 4.1.3.5; P4 continuous raster described as 10 m in the overview and 20 m in
the annex; annex documenting only the P2 continuous and only the P4 classified
raster; annex compression "None"; annex `.tif(float)` for a Byte raster; and
`2.44 x 106 ton/ha/yr` for a total. One addition: the P4 annex also assigns the unit
`ton/ha/yr` to the **classified** raster, which holds class codes 1–5 and has no
physical unit at all.

## 7. Confirmed unchanged

Reproduced exactly, no correction needed:

- Layer inventory and all seven feature counts; EPSG:32629 throughout; all layer
  extents within the AOI bounding box.
- P1: 9 invalid of 2,289 (0.39%), ring self-intersections, no null/empty geometry;
  classes 778/701/431/379.
- P4: 622 invalid of 3,426 (18.16%); `Clase = 1` for all 3,426 records; stored and
  computed area both 22,703.88 ha.
- P3: 5,019 / 266,433 / 323,626; zero invalid, zero duplicate coordinates, zero
  duplicate polygon geometries; 851.2469 km²; activity 2,512 / 757 / 1,750;
  confidence 946 / 2,378 / 1,695; vertical -5.10 to +0.66, mean -1.2524; horizontal
  -2.81 to +0.51, mean -1.2195; both point layers fully non-null on every field.
- P3 null cascade: 1,750 newly triggered null on all four attributes; 2,163 total
  missing vertical velocity (413 additional), 4,110 missing horizontal (2,360
  additional).
- All four rasters: Float32/Int16/Byte types, nodata -9999/-9999/-9999/0,
  5,913 × 6,760, 20 m, shared origin, EPSG:32629.
- P2: 14,252,573 valid cells, 570,102.92 ha, mean 0.007191, max 47.614342, total
  4,099.73 t; class shares 2.000/23.000/25.000/25.000/25.000%.
- P4: 22,427,847 valid cells, 897,113.88 ha, mean 2.715985, max 329.413513, total
  2,436,547.61 t/yr; class shares 87.434/7.400/4.160/0.684/0.321%.
- `bin/inspect` failure: confirmed real. `ogrinfo -json` emits
  `"geometryFields": []` for the non-spatial `EMSN236_data_source` table, and
  `llm_gis/inspect.py:19` does `layer.get("geometryFields", [{}])[0]` — the default
  never fires on an empty list, so it raises `IndexError`. Same pattern at
  `llm_gis/inspect.py:77` and `:90`.

## 8. Revised acceptance actions

Changes to the audit's list:

- **Replace action 6.** Removing the `_temp` artifacts does not restore
  compatibility. Require either a re-export in FileGDB table format v3, or an
  explicit minimum-reader declaration of GDAL ≥ 3.10 / ArcGIS Pro ≥ 3.2. Keep the
  temp-file removal as a separate housekeeping item (~46 MB of dead weight).
- **Add:** explain or correct `kmz_file`, blank in 98.3% of P1 records, and
  reconcile the High-confidence assignment rule with the 7-of-90 that actually
  intersect field evidence.
- **Add:** reconcile the AOI area. The delivered AOI is 13,953.87 km²; the report
  cites 9,086.36 and 9,079.01 km². State the denominator used for every
  AOI-relative percentage.
- **Add:** populate or drop `geom_Length` / `geom_Area` on P1 (null in all records).
- **Amend action 2:** there are three P2 classification definitions, not two.
- **Amend action 5:** table renumbering should be done by updating Word `SEQ`
  fields; Tables 11 and 19 are duplicated as well as Table 30.

## Method

- GDAL Python bindings, `gdal.OpenEx` read-only, feature-by-feature iteration with
  `OGRGeometry.IsValid()` / `IsEmpty()` and `Feature.IsFieldNull()`. Independent of
  the prior audit's OGR SQLite/`ST_IsValid` path.
- Cross-version reads in `ghcr.io/osgeo/gdal:ubuntu-small-{3.9.3,3.10.3,3.12.2}`
  plus the host's GDAL 3.8.4.
- Raster statistics recomputed in NumPy from full-array reads with
  `GDAL_PAM_ENABLED=NO`, not from `gdalinfo` cached statistics.
- DOCX text and metadata from direct ZIP/XML extraction of `word/document.xml` and
  `docProps/app.xml`.
- FileGDB table format versions read from the first four bytes of each
  `.gdbtable` header.
- Scripts: `scratchpad/verify_{vector,attrs,raster,clean,extent,aoi,x}.py`.

No source data were modified, ingested, archived, or moved.
