import re

from llm_gis import common
from llm_gis.common import make_ingest_id


def test_ingest_ids_fit_postgres_identifiers(monkeypatch):
    original_datetime = common.datetime

    class FrozenDateTime:
        @classmethod
        def now(cls, tz=None):
            return original_datetime(2026, 9, 15, 12, 34, 56, tzinfo=tz)

    # Keep the timestamp fixed while allowing the entropy suffix to vary.
    monkeypatch.setattr(common, "datetime", FrozenDateTime)
    ids = [make_ingest_id("a" * 64) for _ in range(2)]
    assert ids[0] != ids[1]
    assert all(re.fullmatch(r"\d{14}_a{10}_[0-9a-f]{6}", value) for value in ids)
    assert all(len("analysis_" + value) <= 63 for value in ids)
