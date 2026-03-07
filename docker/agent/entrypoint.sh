#!/usr/bin/env bash
set -euo pipefail
mkdir -p /data/work/tmp /data/work/logs /data/work/reports /data/work/staging
exec "$@"
