# asset.py

## What it does

Defines `Asset`, the one dataset-descriptor shape shared by `inspect.py`,
`duck.py` (`describe`) and `catalog.py` (`get_assets`). Three producers used to
grow their own vocabulary for the same facts — this module is the shape they
have in common, extracted from what they actually emit rather than designed
ahead of them.

The key discipline: top-level fields carry **measurements only** — something
opened the source and read what was there. A publisher's claims (STAC item
properties, `file:size`, etc.) live under `advertised` and are never promoted
into a measured field. An asset nobody has opened reports `None` for the facts
nobody has checked; that is the model stating its ignorance, not a gap.

## When you'd call it

Never directly from the CLI — it has no `bin/*` command. It's an internal
dataclass module that `inspect_dataset`, `duck.describe` and
`catalog.get_assets` build instances of, then serialize back out to each
command's own historic JSON keys (so no command's output shape changed when
this landed).

## Key classes

- `Asset` — the top-level descriptor: `uri`, `provenance`, `dataset_kind`,
  `crs`/`crs_status`/`crs_reasons`, `bbox`, `record_count`, `columns`,
  `layers`, `bands`, `size`, `advertised` (publisher claims, quarantined),
  `raw` (the underlying tool's full JSON).
- `Provenance` — where an asset came from: `source_type`
  (`local_file`/`remote_uri`/`stac_asset`), `retrieved_at`, `catalog_url`,
  `item_id`, `asset_key`, `content_hash`. Every field is always present and
  `None` where it doesn't apply, so provenance never changes shape by source
  type.
- `Column`, `Layer`, `Band` — small per-field/per-layer/per-band records.

## How it fits the overall flow

Sits at the bottom of the dependency graph alongside `common.py` and
`errors.py`. `inspect.py`, `duck.py`, and `catalog.py` each build an `Asset`
internally and then flatten it to their own JSON shape — callers of `bin/inspect`,
`bin/duck-describe` and `bin/catalog-assets` never see the dataclass, only the
familiar output keys. `planner.py` reads a small slice of the flattened JSON
(`crs_status`, `record_count`) to attach source-quality warnings to a plan.
