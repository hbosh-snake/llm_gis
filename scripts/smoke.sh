#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

docker compose up -d db
./bin/doctor

sample_vector=""
while IFS= read -r -d '' file; do
  sample_vector="$file"
  break
done < <(find data/incoming -maxdepth 1 -type f \( -name '*.gpkg' -o -name '*.geojson' -o -name '*.shp' \) -print0)

if [[ -z "$sample_vector" ]]; then
  echo "No sample vector file in data/incoming; smoke check completed with infrastructure only."
  exit 0
fi

./bin/inspect "$sample_vector"
./bin/ingest-vector "$sample_vector" --table smoke_sample

echo "Smoke check completed."
