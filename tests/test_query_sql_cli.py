"""CLI delegates SQL evidence and preserves the command result envelope."""
import json
from typer.testing import CliRunner
from llm_gis.cli import app


def test_query_sql_cli_exposes_result_options(monkeypatch):
    from llm_gis import cli
    seen = {}
    def execute(**kwargs):
        seen.update(kwargs)
        return {'engine': 'postgis', 'rows': [[5]], 'returned_row_count': 1}
    monkeypatch.setattr(cli, 'query_sql', execute, raising=False)
    result = CliRunner().invoke(app, ['query-sql', '--sql', 'SELECT 5', '--max-rows', '2',
                                      '--max-bytes', '100', '--format', 'csv'])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload['command'] == 'query-sql'
    assert payload['rows'] == [[5]]
    assert seen['statement'] == 'SELECT 5'
    assert seen['max_rows'] == 2
    assert seen['max_bytes'] == 100
    assert seen['output_format'] == 'csv'
