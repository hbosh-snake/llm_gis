# Nepal Flood-Affected Municipalities AOI Design

## Goal

Create a reproducible AOI representing the flood-affected municipalities shown in `data/incoming/image (2).png`, and calculate its area in square kilometres.

## Approach

Use a documented Nepal administrative level 3/local-unit boundary dataset rather than tracing the screenshot. Identify the light-blue municipalities from the image using visible labels, district membership, adjacency, and boundary-shape comparison. Preserve the selected source polygons as an audit layer, dissolve them into a single multipart AOI, and calculate area in a suitable equal-area CRS.

## Outputs

Store deliverables under `data/outgoing/2026-09-01_nepal-flood-aoi/`:

- `nepal_flood_affected_municipalities.gpkg`, containing selected municipalities and the dissolved AOI.
- A GeoJSON copy of the dissolved AOI.
- A JSON manifest containing the boundary source, download URL, source date/version, selected municipality names and identifiers, CRS, matching notes, and total `area_km2`.

## Validation

Confirm every selected polygon against the screenshot using name, district, adjacency, and outline. Flag any municipality that cannot be matched confidently. Validate geometry, dissolve count, CRS, and independent area calculations before delivery.
