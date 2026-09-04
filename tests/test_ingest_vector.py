from pathlib import Path
from unittest import TestCase

from llm_gis.ingest_vector import _ogr_command


class OgrCommandTests(TestCase):
    def test_promotes_mixed_single_and_multi_geometries(self) -> None:
        command = _ogr_command(
            input_path=Path("/data/work/source.shp"),
            schema="raw_example",
            table="features",
            src_crs=None,
            dst_crs="EPSG:25832",
            dsn="PG:example",
        )

        self.assertIn("PROMOTE_TO_MULTI", command)
        self.assertEqual(command[command.index("-nlt") + 1], "PROMOTE_TO_MULTI")
