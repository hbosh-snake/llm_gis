# Design and implement the next evolution of `llm_gis`

You are working on `llm_gis`, a headless geospatial analysis backend designed primarily for use by LLM/coding agents.

The existing project already has a useful core philosophy:

* deterministic GIS operations rather than asking the LLM to perform GIS calculations itself;
* GDAL and PostGIS as trusted geospatial engines;
* CLI-oriented tools suitable for calling from an agent;
* machine-readable outputs;
* explicit handling of CRS, ingestion, validation and provenance;
* separation from desktop GIS and web-map UI concerns.

Preserve these strengths.

The goal of this branch is to evolve `llm_gis` from a primarily:

`local files → ingest → PostGIS → analyse → export`

workflow into a more general:

`discover → inspect → access → decide execution strategy → analyse → validate → export`

geospatial agent backend.

Do not attempt to implement every possible geospatial technology at once. Prioritise changes according to impact, architectural cleanliness and ability to support later extensions.

The implementation should remain modular and allow features below to be added incrementally.

---

# 1. Highest priority: introduce a clear data-source / asset abstraction

Before adding many integrations, refactor or extend the architecture so the analytical layer does not assume that all input data begins as a local file.

Conceptually distinguish:

1. **Discovery**

   * What datasets exist?
   * What catalogue/service contains them?

2. **Inspection**

   * What is this dataset?
   * Geometry/raster type, CRS, spatial extent, temporal extent, attributes, resolution, size, metadata, etc.

3. **Access**

   * Can it be queried remotely?
   * Must it be downloaded?
   * Can only the AOI/subset be fetched?

4. **Materialisation**

   * Does it need to become a local file?
   * Does it need to be ingested into PostGIS?

5. **Analysis**

   * Which engine should execute the operation?

6. **Validation / QC**

7. **Export**

Avoid tightly coupling discovery/access mechanisms with PostGIS.

Introduce an abstraction along the lines of:

```text
DataSource
Asset
DatasetDescriptor
```

Names are flexible.

Possible source types should eventually include:

```text
LocalFileSource
HttpSource
StacSource
PortolanSource
OgcApiFeaturesSource
WfsSource
ArcGISFeatureServiceSource
```

Do NOT implement all of these immediately if doing so produces poor abstractions.

First design the interfaces so they can support them cleanly.

An `Asset` or equivalent should ideally be able to describe:

* source URI;
* source type;
* media/format type;
* vector/raster/point-cloud/etc.;
* CRS, if known;
* bbox;
* spatial and temporal extent;
* approximate size, if available;
* metadata/provenance;
* whether remote range/subset access is possible;
* whether it is already local;
* whether it is already materialised into an analytical engine;
* candidate execution engines.

Maintain provenance through the full workflow.

---

# 2. Add first-class STAC support

This is the first major functional addition.

Do NOT implement Portolan as a proprietary standalone integration first.

Implement generic STAC support, so Portolan and many other catalogues can use the same machinery.

Use a mature STAC client such as `pystac-client` unless repository constraints give a compelling reason not to.

Support the essential workflow:

```text
register/use STAC endpoint
        ↓
inspect catalogue capabilities
        ↓
search collections/items
        ↓
inspect item/assets
        ↓
select appropriate asset
        ↓
pass Asset into llm_gis processing
```

Design CLI/API commands appropriate for the current project style. For example, conceptually:

```bash
bin/catalog-add <name> <url>

bin/catalog-search <name> \
    --bbox ... \
    --datetime ... \
    --collection ...

bin/catalog-collections <name>

bin/catalog-item <name> <item-id>

bin/catalog-assets <name> <item-id>
```

Do not treat these exact command names as mandatory.

Requirements:

* JSON/machine-readable output consistent with existing tools;
* good error messages;
* expose STAC conformance/capabilities where useful;
* support bbox and datetime search;
* collection filtering;
* asset discovery;
* preserve full source provenance;
* do not download an asset merely because it has been discovered.

If practical, support remote STAC assets without materialising them first.

Test against at least one public STAC endpoint.

Prefer tests that do not rely entirely on live network availability; use fixtures/mocked STAC responses for core behaviour.

---

# 3. Add DuckDB + Spatial as a lightweight vector execution path

This is probably the most important analytical improvement.

Current architecture is PostGIS-centric. Keep PostGIS, but stop treating ingestion into PostgreSQL as mandatory for every analytical operation.

Introduce DuckDB, including its Spatial capabilities, as a lightweight execution engine particularly for:

* GeoParquet;
* Parquet;
* remote/cloud-hosted tabular/vector datasets;
* temporary analytical queries;
* filtering large datasets before materialisation;
* simple spatial joins/aggregations where DuckDB is sufficient.

The desired conceptual decision is:

```text
Asset
  │
  ├── cheap/direct operation possible?
  │         ↓
  │      DuckDB
  │
  └── persistent/complex/heavy spatial workflow?
            ↓
         PostGIS
```

Do not attempt to hide all engine differences behind an overly clever abstraction.

A small explicit execution planner is preferable to magic.

Support remote GeoParquet where possible, including HTTP/S3-compatible access if DuckDB supports it appropriately in the chosen environment.

Example target capability:

```text
STAC/Portolan asset
      ↓
remote GeoParquet
      ↓
bbox/attribute query in DuckDB
      ↓
small result
```

without:

```text
download entire dataset
→ ogr2ogr
→ PostGIS
→ index
→ query
```

Implement:

* format detection;
* schema inspection;
* spatial metadata inspection;
* SQL execution through controlled wrappers;
* bbox filtering;
* attribute filtering;
* spatial predicate support where robust;
* result export/materialisation.

Security matters: if exposing arbitrary SQL to the LLM, constrain it appropriately or make the architecture explicitly aware that SQL is a privileged low-level operation.

Prefer deterministic higher-level commands for common operations, with SQL available as an advanced mechanism.

---

# 4. Add an explicit execution/materialisation decision layer

Once DuckDB exists, formalise the distinction between:

```text
query remotely
query locally without persistent ingestion
materialise subset
ingest into PostGIS
```

The agent should not automatically choose the heaviest route.

Implement a simple, explainable decision mechanism.

Potential inputs:

* asset format;
* remote/local;
* approximate size;
* operation requested;
* persistence requirements;
* number of expected operations;
* raster vs vector;
* whether spatial indexing/persistent relational joins are needed;
* engine capability.

The result could be machine-readable, for example:

```json
{
  "strategy": "duckdb_remote",
  "reason": "Remote GeoParquet supports the requested bbox and aggregation without persistent ingestion.",
  "fallback": "postgis"
}
```

This is especially useful to an LLM agent because it exposes why a path was chosen.

Do not over-engineer an optimiser.

A conservative deterministic rule-based planner is sufficient initially.

Allow explicit user/agent override:

```text
--engine duckdb
--engine postgis
--materialise
--no-materialise
```

or equivalent.

---

# 5. Add Portolan support through the generic STAC/asset architecture

After STAC + GeoParquet/DuckDB support exists, add Portolan.

Treat Portolan primarily as:

* a discoverable STAC-based source;
* a set of conventions;
* useful agent-readable metadata/documentation;
* a source of cloud-native assets.

Do not fork the architecture for it unnecessarily.

Implement support for relevant Portolan conventions and metadata where these improve the agent experience.

Investigate the current Portolan specification and `portolan-skills` rather than relying on assumptions.

Useful capabilities may include:

* recognising a Portolan catalogue;
* exposing catalogue/collection documentation;
* reading `README.md`, `AGENTS.md`, or analogous agent-facing documentation when provided by the catalogue;
* presenting metadata alongside datasets;
* using GeoParquet, COG, PMTiles, COPC, GeoZarr or other assets through their appropriate generic handlers;
* maintaining Portolan provenance.

A command might conceptually look like:

```bash
bin/catalog-add-portolan <url>
```

but if Portolan can simply be handled by:

```bash
bin/catalog-add <url>
```

with automatic capability detection, prefer the generic implementation.

Do not tightly bind `llm_gis` to Portolan's current pre-1.0 specification.

---

# 6. Improve raster architecture: COG-first and windowed access

Review the current raster workflow.

Do not remove PostGIS raster support if it already works and is useful, but stop assuming `raster2pgsql` is the default destination for every raster.

Introduce a raster access path based on GDAL/Rasterio or an equivalent proven library that supports:

* Cloud Optimised GeoTIFF;
* HTTP range requests;
* reading only the AOI/window required;
* reprojection where needed;
* raster metadata inspection;
* statistics;
* raster/vector clipping;
* zonal statistics where sensible;
* materialisation only when necessary.

Target architecture:

```text
COG
 ↓
inspect
 ↓
window/subset read
 ↓
analyse
 ↓
optional derived COG
```

rather than:

```text
COG
 ↓
download whole raster
 ↓
PostGIS raster
```

Make engine choice explicit.

Consider whether raster analyses belong in:

* GDAL;
* Rasterio;
* NumPy;
* Xarray;
* PostGIS raster;

depending on operation.

Avoid introducing a huge raster framework unless justified.

---

# 7. Add OGC and common SDI access adapters

Once the source abstraction is stable, expand discovery/access beyond STAC.

Prioritise what is useful in real operational GIS environments.

Suggested order:

1. OGC API - Features
2. ArcGIS REST Feature Services
3. WFS
4. OGC API - Records
5. WCS / other raster services if clearly useful

Do not implement all simultaneously.

For each adapter, expose the source as the same generic `Asset`/dataset descriptor used elsewhere.

Capabilities should include, where supported:

* inspect service;
* list collections/layers;
* metadata;
* CRS;
* bbox;
* schema/fields;
* spatial query/subsetting;
* attribute filters;
* pagination;
* materialise returned data;
* preserve request/source provenance.

For ArcGIS REST, account for realistic constraints such as:

* `maxRecordCount`;
* pagination;
* service capabilities;
* layer IDs;
* output spatial reference;
* geometry filters.

For WFS/OGC APIs, avoid downloading an entire national dataset if the server supports spatial filtering.

---

# 8. Add visual preview / QC capability

The backend should remain headless.

Do NOT turn `llm_gis` into QGIS or build a general-purpose web-map application.

However, an LLM with vision should be able to inspect analytical output.

Add a deterministic preview capability such as:

```bash
bin/preview <dataset>
```

producing:

* PNG/JPEG preview;
* bbox;
* CRS;
* rendering parameters;
* feature/raster summary;
* warnings.

For vectors, generate a simple but legible map with:

* geometry;
* optional AOI/context;
* sensible extent;
* basic legend if categories are relevant;
* deterministic rendering.

For rasters, generate a sensible preview using metadata/statistics.

Potentially investigate TiTiler or related tooling for COG/STAC previewing, but avoid introducing a server dependency if a simpler library-based solution satisfies the requirement.

The purpose is:

```text
analysis
   ↓
output
   ↓
preview
   ↓
vision-capable LLM checks obvious spatial problems
```

Examples of problems visual QC could expose:

* incorrect CRS;
* features thousands of kilometres from AOI;
* empty intersection;
* swapped coordinates;
* massive slivers;
* unexpected geometry outside AOI;
* implausible raster extent;
* wrong layer selected.

Visual QC should supplement, not replace, numeric/geometric validation.

---

# 9. Strengthen automated geospatial QC

In parallel with previews, add or improve deterministic validation.

For every derived vector result where applicable, provide metrics such as:

```text
feature count
geometry types
empty geometry count
invalid geometry count
bbox
CRS
area/length statistics
null key attributes
duplicate IDs
unexpected Z/M dimensions
```

For rasters:

```text
dimensions
bands
CRS
resolution
bbox
nodata
min/max/mean where reasonable
percentage nodata
```

Add plausibility checks where they are generic enough to be reliable.

Examples:

* output bbox does not overlap input bbox;
* intersection result larger than source geometry when impossible;
* operation produced zero features unexpectedly;
* geographic CRS used for metric buffer;
* suspicious latitude/longitude reversal;
* area calculation performed directly in EPSG:4326.

Return warnings in structured form:

```json
{
  "status": "ok_with_warnings",
  "warnings": [
    {
      "code": "GEOGRAPHIC_CRS_FOR_METRIC_OPERATION",
      "message": "...",
      "severity": "high"
    }
  ]
}
```

Where feasible, require high-risk warnings to be explicitly acknowledged before executing an unsafe operation.

---

# 10. Add operation plans before execution

A useful LLM-facing feature is the ability to produce a deterministic execution plan before modifying data.

For example:

```bash
bin/plan intersection \
    --left buildings \
    --right flood_extent
```

might return:

```json
{
  "steps": [
    "Inspect inputs",
    "Reproject buildings from EPSG:4326 to EPSG:32632",
    "Validate geometries",
    "Intersect datasets in PostGIS",
    "Calculate affected building count",
    "Validate result",
    "Export GeoPackage"
  ],
  "engine": "postgis",
  "estimated_materialisation": true,
  "warnings": []
}
```

This has several advantages:

* LLM can inspect the workflow before executing;
* easier debugging;
* easier audit trail;
* easier approval workflows;
* eventual support for more autonomous agents.

Do not create an elaborate DAG/workflow engine yet.

A serial structured plan is sufficient.

---

# 11. Improve provenance and reproducibility

Every analysis should be reproducible.

Extend provenance so a final output can answer:

* Which source datasets were used?
* Where did they come from?
* Which catalogue/service?
* Which STAC item/asset?
* Which URL?
* Which versions/timestamps were available?
* Were remote datasets subsetted?
* Which CRS transformations occurred?
* Which commands were executed?
* Which parameters?
* Which software/library versions?
* Which output files correspond to the analysis?

Consider producing a machine-readable analysis manifest, for example:

```text
analysis.json
```

alongside outputs.

Potential structure:

```json
{
  "inputs": [...],
  "operations": [...],
  "outputs": [...],
  "warnings": [...],
  "software": {...}
}
```

Prefer open/simple structures over an elaborate proprietary provenance schema.

---

# 12. Add efficient caching

Remote data access makes caching important.

Implement a modest cache layer for:

* downloaded assets;
* HTTP/STAC metadata where reasonable;
* materialised subsets;
* potentially expensive deterministic intermediate products.

Cache keys should derive from source + query/subset parameters.

Requirements:

* inspectable cache;
* ability to clear cache;
* avoid silent reuse of stale assets where timestamp/version matters;
* maintain provenance;
* distinguish immutable versioned assets from mutable service requests.

Do not build a distributed cache.

A local filesystem cache is enough.

---

# 13. Make the CLI strongly agent-oriented

Review all commands from the perspective of an LLM tool caller.

Every command should ideally:

* support JSON output;
* use stable field names;
* provide meaningful exit codes;
* avoid mixing logs with JSON stdout;
* send diagnostics to stderr;
* expose warnings explicitly;
* make destructive actions explicit;
* support dry-run/plan modes where applicable;
* avoid interactive prompts;
* expose help that is concise and machine-readable where useful.

Errors should explain:

```text
what failed
why
what the likely corrective action is
```

Avoid vague messages such as:

```text
Operation failed.
```

Prefer:

```json
{
  "status": "error",
  "code": "CRS_REQUIRED_FOR_METRIC_BUFFER",
  "message": "Input is EPSG:4326. Buffer distance 500 is ambiguous because the CRS unit is degrees.",
  "suggested_action": "Reproject to an appropriate projected CRS before buffering."
}
```

---

# 14. Consider an engine capability registry

As functionality grows, avoid hard-coded assumptions scattered throughout commands.

Create a lightweight capability description such as:

```text
DuckDB:
    GeoParquet: yes
    remote Parquet: yes
    persistent spatial workspace: no/limited
    complex topology workflow: limited

PostGIS:
    persistent vector workspace: yes
    spatial indexing: yes
    complex relational analysis: yes

GDAL/Rasterio:
    COG window access: yes
    reprojection: yes
```

This could support execution planning.

Keep it simple.

Do not turn this into a generic plugin framework unless the current architecture clearly benefits from one.

---

# 15. Support modern output formats

Keep GeoPackage/GeoJSON support, but add formats appropriate to the new architecture where useful.

Priority:

### Vector

* GeoParquet
* GeoPackage
* GeoJSON

### Raster

* COG

Potential later:

* PMTiles;
* COPC;
* GeoZarr.

Output format should be selected according to intended use rather than one universal default.

GeoJSON should not be the default for very large datasets.

---

# 16. Optional later phase: expose `llm_gis` as a standard geospatial processing service

Do NOT prioritise this over the previous capabilities.

Investigate exposing selected `llm_gis` operations via:

* OGC API - Processes;
* possibly `pygeoapi`.

Potential architecture:

```text
                   ┌── CLI
                   │
llm_gis engine ────┼── agent/MCP interface
                   │
                   └── OGC API Processes
```

The processing logic should remain independent from the interface.

Only implement this once the internal execution model is stable.

---

# 17. Optional: MCP/tool interface

Evaluate whether exposing `llm_gis` through MCP would materially improve integration with coding/LLM agents.

Do not replace the deterministic CLI.

If implemented, MCP should wrap existing operations rather than creating a second analytical implementation.

Conceptually:

```text
LLM
 ↓
MCP tool
 ↓
llm_gis operation
 ↓
GDAL / DuckDB / PostGIS
```

The CLI should remain useful independently.

---

# 18. Avoid these architectural traps

Do NOT:

* turn the LLM itself into the GIS calculation engine;
* implement spatial mathematics in prompts where GDAL/PostGIS/DuckDB can do it deterministically;
* require PostGIS ingestion for every operation;
* require downloading entire cloud datasets when range/subset access exists;
* create Portolan-specific architecture when STAC/general asset abstractions suffice;
* build a desktop GIS;
* build a full web GIS;
* invent a proprietary geospatial data format;
* introduce Kubernetes/distributed infrastructure without a demonstrated requirement;
* create a huge generic plugin system prematurely;
* create a complex workflow/DAG engine before simple operation plans are proven insufficient;
* rely on the LLM to detect CRS errors without deterministic safeguards.

---

# 19. Suggested implementation order

Prioritise approximately as follows.

## Phase A — architectural foundation

1. Inspect current repository and tests.
2. Define DataSource / Asset / DatasetDescriptor abstractions.
3. Separate inspect/access/materialise/analyse concepts where currently conflated.
4. Preserve backwards compatibility for existing local-file workflows.

This phase should not become a large refactor for its own sake.

## Phase B — highest-value functionality

5. Generic STAC client.
6. STAC search/inspect/select asset.
7. DuckDB + Spatial.
8. GeoParquet local and remote querying.
9. Explicit execution/materialisation planner.

At the end of this phase, demonstrate:

```text
public STAC
→ discover remote GeoParquet
→ query only AOI
→ produce result
```

without PostGIS ingestion.

## Phase C — cloud raster capability

10. COG inspection.
11. Remote/windowed COG access.
12. Raster subset/clip/basic processing.
13. COG export where appropriate.

## Phase D — Portolan

14. Test Portolan catalogues through generic STAC support.
15. Add only the Portolan-specific metadata/documentation handling actually needed.
16. Test GeoParquet/COG workflows against Portolan assets.

## Phase E — operational SDIs

17. OGC API - Features.
18. ArcGIS REST Feature Services.
19. WFS.
20. OGC API - Records.

Prioritise working spatial filters/subsets over broad protocol completeness.

## Phase F — autonomy and QC

21. Structured operation planning.
22. Stronger deterministic QC.
23. Preview/render output.
24. Analysis manifest/provenance.
25. Cache.

## Phase G — interfaces

26. MCP wrapper if useful.
27. OGC API - Processes / pygeoapi if useful.

---

# 20. Required demonstration workflows

When the branch is mature enough, create integration examples demonstrating these cases.

## Example 1 — current workflow remains functional

```text
local GeoPackage
→ inspect
→ PostGIS
→ spatial analysis
→ GeoPackage
```

No regression.

## Example 2 — remote GeoParquet

```text
STAC
→ find dataset
→ remote GeoParquet
→ DuckDB bbox filter
→ aggregate/query
→ GeoParquet or GeoPackage result
```

No full dataset ingestion.

## Example 3 — cloud raster

```text
STAC
→ COG
→ inspect remotely
→ AOI window read
→ calculate statistics
→ derived output
```

No full raster download unless required.

## Example 4 — complex multi-dataset GIS

```text
remote dataset A
remote dataset B
↓
subset both
↓
materialise useful subsets
↓
PostGIS
↓
reprojection + spatial join/intersection
↓
QC
↓
preview
↓
GeoPackage
```

## Example 5 — Portolan

```text
Portolan catalogue
→ read catalogue/agent documentation
→ discover dataset through STAC
→ inspect asset
→ use generic GeoParquet/COG processing path
→ result
```

This should demonstrate that Portolan integration mostly composes existing generic functionality rather than requiring an isolated subsystem.

---

# 21. Testing expectations

Tests should cover:

* data-source abstractions;
* STAC parsing/search;
* malformed/unavailable catalogues;
* asset selection;
* remote/local GeoParquet;
* DuckDB spatial queries;
* execution planner rules;
* CRS safety;
* vector QC;
* raster metadata;
* COG window access;
* provenance;
* caching;
* Portolan compatibility;
* backwards compatibility.

Prefer deterministic fixtures for unit tests.

Use a small number of live-service smoke tests, clearly separated from normal tests.

The normal test suite should not fail merely because an external catalogue is offline.

---

# 22. Documentation

Update the project documentation to explain the conceptual model:

```text
DISCOVER
   ↓
INSPECT
   ↓
ACCESS
   ↓
PLAN
   ↓
ANALYSE
   ↓
VALIDATE
   ↓
EXPORT
```

Document when each engine is preferred:

```text
GDAL       file conversion / inspection / reprojection
DuckDB     lightweight/local/remote GeoParquet analytics
PostGIS    persistent and complex vector analysis
Rasterio   windowed raster/cloud-raster processing
```

Document that these are defaults rather than rigid rules.

Give the LLM agent examples showing good decision-making.

Example:

Bad:

```text
Download 40 GB global buildings dataset and import into PostGIS.
```

Better:

```text
Query the remote GeoParquet for the AOI with DuckDB and materialise only the matching features.
```

Another:

Bad:

```text
Buffer EPSG:4326 geometries by 500.
```

Better:

```text
Identify an appropriate projected CRS, reproject, then buffer by 500 metres.
```

---

# 23. Maintain the project's main design philosophy

The project should increasingly behave like a **geospatial execution environment for an intelligent agent**, not like an AI chatbot with GIS functions.

The division of labour should remain:

```text
LLM:
    understand intent
    discover data
    choose tools
    construct workflow
    interpret results

llm_gis:
    enforce geospatial correctness
    inspect data
    manage CRS
    retrieve/subset data
    execute deterministic GIS operations
    validate results
    preserve provenance
```

The LLM may decide **what** to do.

`llm_gis` should remain responsible for correctly determining **how the GIS operation is executed**.

---

# 24. Use judgement rather than blindly following this specification

This is a design direction, not a mandatory feature checklist.

Before implementing each substantial feature:

1. inspect the current code;
2. determine whether existing abstractions already solve part of the problem;
3. check the current upstream documentation/specifications;
4. choose mature libraries rather than reimplementing standards;
5. minimise dependencies;
6. preserve backwards compatibility where reasonable;
7. prefer a small general capability over several special-case implementations.

If you find a better architecture than the one described here, use it, but explain the reasoning.

If a proposed feature has little benefit relative to its complexity, defer it.

If implementation reveals that a later phase should move earlier, adjust the sequence.

Do not optimise for completing the largest number of bullet points.

Optimise for making `llm_gis` substantially more capable, reliable and composable for autonomous geospatial analysis.

---

# 25. Deliverables for this design branch

Produce:

1. the implemented code;
2. tests;
3. updated documentation;
4. migration/backwards-compatibility notes if needed;
5. several concrete example workflows;
6. a short architectural document explaining:

   * new components;
   * execution-engine selection;
   * data lifecycle;
   * provenance model;
   * intentionally deferred features.

Also maintain a short decision log for important choices.

For each major proposed feature, classify it as:

```text
IMPLEMENTED
PARTIALLY IMPLEMENTED
DEFERRED
REJECTED
```

with a one- or two-sentence rationale.

Do not leave partially implemented integrations appearing production-ready.

---

# Definition of success

The most important success criterion is not the number of integrations.

A successful version of `llm_gis` should be able to receive a geospatial task and intelligently move between:

```text
local files
STAC catalogues
cloud-native datasets
government GIS services
DuckDB
GDAL/Rasterio
PostGIS
```

while minimising unnecessary downloads and ingestion, enforcing GIS correctness, maintaining provenance, and returning deterministic, auditable outputs suitable for inspection by an LLM agent.

The key architectural change is:

**PostGIS remains a major analytical engine, but it is no longer the mandatory gateway through which every dataset must pass.**

