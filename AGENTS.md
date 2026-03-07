You are a senior geospatial software architect and DevOps engineer.

Design a **minimal, robust, reproducible Docker architecture** that allows a coding agent (LLM-coder) to perform *spatial data ingestion and analysis* using standard GIS tooling and PostGIS.

The goal is **not** a web GIS and **not** a QGIS desktop environment.
The goal is a headless geospatial analysis backend that an AI coding agent can control through the filesystem, Python, and SQL.

The agent must be able to:

* ingest shapefile, geopackage, geojson, and raster datasets
* inspect CRS and geometry types
* reproject datasets safely
* load them into PostGIS
* run spatial SQL queries
* export results to GeoPackage/GeoJSON
* compute intersections, buffers, exposure, zonal statistics, and distance-based queries
* run repeatable workflows

Constraints:

* No GUI
* No PyQGIS
* Must run reliably in a container
* Must be deterministic across machines
* Must tolerate incorrect CRS input and detect it
* Must not require manual database preparation
* The LLM will later be given “skills” describing workflows (e.g. confirm CRS, choose projection, validate geometries)

### Required output

Produce a **step-by-step implementation plan**, not a conceptual explanation.

Your plan must include:

1. Folder structure
2. docker-compose architecture
3. Containers and their responsibilities
4. Exact base images to use and why
5. Required system packages (GDAL/PROJ/etc.)
6. Required Python libraries
7. Database initialization strategy
8. How PostGIS extensions are created automatically
9. How ingestion should work (ogr2ogr vs Python)
10. How the agent should call ingestion
11. How datasets should be staged before import
12. How CRS detection and validation should be handled
13. How geometry validity should be enforced
14. How schema naming should work
15. How to safely run spatial queries from an agent
16. How results should be exported
17. Where temporary files should live
18. Logging strategy
19. Failure recovery strategy
20. How to make the environment discoverable by an LLM (what metadata files to expose)

### Important design requirements

Prefer:

* PostGIS + GDAL as the core engine
* SQL spatial analysis over heavy Python operations
* Reusable command entrypoints callable by the LLM
* A workspace directory the agent can read/write
* A read-only “data drop” directory for raw inputs

Avoid:

* Jupyter notebooks
* manual SQL setup
* interactive terminals
* desktop GIS dependencies

The final system should behave like this:

I drop a dataset into `/data/incoming`
The agent inspects it
Confirms CRS
Loads it into PostGIS
Runs analysis
Exports results into `/data/outgoing`
Use uv as package manager. Never python or python 3 or pip or uv pip.
