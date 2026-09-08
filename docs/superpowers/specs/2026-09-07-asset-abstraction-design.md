# Phase 5 — Extract the asset abstraction: design

**Status:** approved design, not yet implemented.
**Plan reference:** `docs/plans/2026-09-04_improvement_plan_revised.md`, "Phase 5 — Extract the asset abstraction (O1, deferred here by D1)".
**Date:** 2026-09-07.

## Purpose

Three commands describe a dataset today, each with its own vocabulary for the same facts.
Give them one internal type. `llm_gis/asset.py` defines what this workspace means by "a
dataset we can point at": where it is, what it holds, and where it came from. The three
producers build it; each serializes back to the JSON its callers already know. No output
changes in this phase. The type exists so Phase 6's planner has one input shape to route
on instead of three.

The plan defers this abstraction to Phase 5 by D1: do not design it from imagination,
extract it from what the real producers emit. This document records that extraction.

## What the three producers actually emit

Read on 2026-09-07 from `llm_gis/inspect.py:inspect_dataset`, `llm_gis/duck.py:describe`
and `llm_gis/catalog.py:flatten_asset`, cross-checked against their
`docs/llm/OUTPUT_SCHEMA.md` entries.

| Concept | `inspect` | `duck-describe` | `catalog-assets` |
|---|---|---|---|
| Identity | `input_path` | `uri` | `href` (plus `key`) |
| Kind | `dataset_kind` | implicit Parquet | `media_type`, `roles`, `readable_by` |
| CRS | `detected_crs`, `crs_status`, `crs_reasons` | `crs` | `advertised["proj:epsg"]` |
| Extent | `extent` | `bbox` | none |
| Count | `layers[].feature_count` | `row_count` | `advertised["num_rows"]` |
| Schema | `layers` / `bands`, `size` | `columns`, `geometry_column` | none |
| Size | none | none | `advertised["size_bytes"]` |
| Provenance | `created_at`, `raw` | none | `item_url`, `item_id` |

Three names per concept, and the two extent objects already agree on their inner keys
(`minx`, `miny`, `maxx`, `maxy`) while disagreeing on the outer one.

## The finding that shapes this phase

`inspect` and `duck-describe` report **measurements**: something opened the file and read
what was there. `catalog-assets` reports **the publisher's claims**, which Phase 4
deliberately quarantined under `advertised` with a documented warning never to read them
as QC metrics.

Unifying three shapes puts pressure on exactly that distinction, because the obvious
unified model has one `crs` field and three producers with a CRS to offer. The pressure is
resolved in favour of Phase 4's guarantee:

**Top-level fields carry measurements only.** A STAC asset comes back with most top-level
fields `None` and everything real under `advertised`. This is not a gap to be filled
later; it is the model stating that nobody has opened that asset yet. No per-field origin
marker, no `measured: true/false` flag, no confidence score — machinery the three current
producers do not justify.

## Scope

In scope:

- `llm_gis/asset.py`: an `Asset` dataclass, a `Provenance` dataclass, and three record
  types (`Column`, `Layer`, `Band`).
- `inspect`, `duck-describe` and `catalog-assets` each build an `Asset` and serialize back
  to their current JSON, key for key unchanged.
- A `tests/test_asset.py` covering construction and one round-trip per producer.

Out of scope, and deliberately so:

- `stage` and `ingest_vector` / `ingest_raster`. They already hash and are the natural
  fourth and fifth producers, but they write to `meta.ingestions` and carry ingest-id
  semantics that are a phase of their own.
- Any `--hash` flag or new CLI surface.
- Any change to `readable_by`'s logic. Phase 4 reserved that decision for Phase 6's
  planner and it must not grow a second opinion here.
- Phase 6's planner itself.

## The model

A stdlib `@dataclass`, not Pydantic. The hot-start skill names Pydantic 2 in the stack,
but it is imported nowhere in `llm_gis/` and absent from `pyproject.toml`; a type built by
three trusted call sites inside one process needs no validation layer and no new
dependency. (The stale stack line is worth correcting separately.)

Every field is admitted only because a producer populates it today. The "populated by"
column is the admission record.

| Field | Type | Populated by |
|---|---|---|
| `uri` | `str` | all three |
| `dataset_kind` | `str \| None` | `inspect` |
| `media_type` | `str \| None` | `catalog-assets` |
| `roles` | `list[str]`, default `[]` | `catalog-assets` |
| `readable_by` | `list[str]`, default `[]` | `catalog-assets` |
| `crs` | `str \| None` | `inspect`, `duck-describe` |
| `crs_status` | `str \| None` | `inspect` |
| `crs_reasons` | `list[str]`, default `[]` | `inspect` |
| `bbox` | `dict \| None` | `inspect`, `duck-describe` |
| `record_count` | `int \| None` | `duck-describe` |
| `geometry_column` | `str \| None` | `duck-describe` |
| `columns` | `list[Column]`, default `[]` | `duck-describe` |
| `layers` | `list[Layer]`, default `[]` | `inspect`, vector |
| `bands` | `list[Band]`, default `[]` | `inspect`, raster |
| `size` | `list[int] \| None` | `inspect`, raster |
| `advertised` | `dict`, default `{}` | `catalog-assets` |
| `raw` | `dict \| None` | `inspect` |
| `provenance` | `Provenance` | all three |

`Provenance` carries `source_type` (`local_file`, `remote_uri` or `stac_asset`),
`retrieved_at`, `catalog_url`, `item_id`, `asset_key` and `content_hash`.

### Two rulings the field table hides

**`record_count` stays `None` for `inspect`.** `inspect` has no top-level count, only
`layers[].feature_count`. Summing layers would publish a number no consumer sees today.
The per-layer counts stay on `layers`; the top-level field stays null. "The same
descriptor shape" therefore means the same fields, not the same fields filled.

**`uri` lives on the `Asset`, not in `Provenance`.** The plan's wording puts source URI in
provenance. It is the asset's identity, and holding it twice creates two places to
disagree. Deliberate deviation.

## Provenance is present, often empty, and never computed

Every provenance field exists always and defaults to `None`. The block does not change
shape by source type: a `None` `item_id` on a local file reads correctly, whereas an
absent key forces every consumer to guard.

`content_hash` is **not computed by this phase**. `sha256_for_path`
(`llm_gis/common.py:33`) is called today only by `stage` (`stage.py:32`),
`ingest_vector` (`ingest_vector.py:67`) and `ingest_raster` (`ingest_raster.py:44`).
`inspect` does not hash. Reading "hash where local" literally would make `inspect` read
every file a second time to fill a field that, with no output change in this phase,
nothing serializes — real cost on large rasters for no observable benefit. The field is
reserved; producers that already hash fill it when they adopt the model in a later phase.

`retrieved_at` is canonical. `inspect` already emits `created_at` from `utc_now()` and
maps back to it; `duck-describe` and `catalog-assets` emit no timestamp today and continue
not to.

## Naming, and where the translation happens

The model uses one canonical name per concept: `uri`, `bbox`, `crs`, `record_count`,
`retrieved_at`. Each command's serializer maps back to the keys its callers know.

| Canonical | `inspect` | `duck-describe` | `catalog-assets` |
|---|---|---|---|
| `uri` | `input_path` | `uri` | `href` |
| `bbox` | `extent` | `bbox` | — |
| `crs` | `detected_crs` | `crs` | — |
| `record_count` | — | `row_count` | — |
| `retrieved_at` | `created_at` | — | — |

Alternatives rejected: carrying every historic name on the model as an alias, which grows
a wart per producer forever; and emitting canonical names alongside historic ones, which
changes output this phase set out not to change.

## Architecture

`asset.py` is pure data and knows no command's JSON. Serializers live with the commands
that own their contracts: a private `_to_report(asset)` in `inspect.py`,
`_to_describe(asset)` in `duck.py`, `_to_asset_json(asset)` in `catalog.py`.

The rejected alternative was `asset.as_inspect_report()` methods on the model. It drags
all three output contracts into one file and makes `asset.py` the file you edit when
catalog's JSON changes — the opposite of the boundary this phase is drawing.

Item-level keys in `catalog-assets` (`item_url`, `item_id`, `asset_count`) stay in
`get_assets`. They describe the item, not an asset.

## Data flow

Unchanged for every producer: gather the facts exactly as today, build an `Asset`,
serialize. No new I/O, no hashing, no network calls, no new error codes. The dict reaching
`stdout` is the dict that reaches it now.

## Testing

`tests/test_output_contract.py`, `tests/test_inspect.py`, `tests/test_duck.py` and
`tests/test_catalog_operations.py` are the oracle. They pass **unchanged** — no fixture
edits, no loosened assertions. Needing to soften an existing assertion means the
extraction is wrong, not the test.

Added: `tests/test_asset.py`, covering construction of an `Asset` for each source type and
one round-trip per producer — build from a known input, serialize, assert the result
equals the historic dict key for key.

## Documentation

`docs/llm/OUTPUT_SCHEMA.md` needs **no edit**. That absence of a diff is the evidence the
compatibility surface held.

`.claude/skills/hot-start/SKILL.md` gains `asset.py` per the CLAUDE.md rule that new
modules record their technical context there.

## Increments

Each step is independently reviewable and revertable, ordered so the model meets the
easiest producers first.

1. `llm_gis/asset.py` and `tests/test_asset.py`. Model only, wired to nothing. Proves the
   shape holds all three producers' facts before anything depends on it.
2. Wire `catalog.flatten_asset`. Smallest producer, six fields, cleanest provenance.
3. Wire `duck.describe`.
4. Wire `inspect.inspect_dataset`. Largest, two branches, done last.
5. Record `asset.py` in `.claude/skills/hot-start/SKILL.md`.

## Done when

- `llm_gis/asset.py` defines `Asset` and `Provenance`, and every field on them is
  populated by at least one of the three producers.
- `inspect`, `duck-describe` and `catalog-assets` each construct an `Asset` and serialize
  from it.
- The existing test suite passes with no modification to any test or fixture.
- `docs/llm/OUTPUT_SCHEMA.md` is unchanged.
