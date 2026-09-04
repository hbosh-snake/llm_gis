from __future__ import annotations

import shutil
import zipfile
from pathlib import Path

from llm_gis.common import (
    ensure_child_path,
    incoming_root,
    ensure_workspace_dirs,
    make_ingest_id,
    sha256_for_path,
    utc_now,
    write_json,
)


WORK_ROOT = Path("/data/work")


def stage_input(input_path: Path, ingest_id: str | None = None) -> dict:
    ensure_workspace_dirs()
    if not input_path.exists():
        raise FileNotFoundError(input_path)
    ensure_child_path(input_path, incoming_root())

    input_hash = sha256_for_path(input_path)
    resolved_ingest_id = ingest_id or make_ingest_id(input_hash)
    stage_dir = WORK_ROOT / "staging" / resolved_ingest_id
    stage_dir.mkdir(parents=True, exist_ok=True)

    target = stage_dir / input_path.name
    if input_path.is_dir():
        if target.exists():
            shutil.rmtree(target)
        shutil.copytree(input_path, target)
    else:
        shutil.copy2(input_path, target)
        if input_path.suffix.lower() == ".zip":
            with zipfile.ZipFile(target) as archive:
                archive.extractall(stage_dir)

    report = {
        "ingest_id": resolved_ingest_id,
        "input_path": str(input_path),
        "input_hash": input_hash,
        "staging_dir": str(stage_dir),
        "staged_item": str(target),
        "created_at": utc_now(),
    }
    write_json(WORK_ROOT / "reports" / f"{resolved_ingest_id}.json", report)
    return report
