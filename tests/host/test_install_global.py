"""Personal installation can be previewed without changing existing skills."""
from pathlib import Path
import runpy

import pytest

REPO = Path(__file__).resolve().parents[2]


@pytest.fixture
def source_repo(tmp_path):
    root = tmp_path / 'source-repo'
    for name in ('bin/llm-gis', 'AGENTS.md', 'docs/llm/GLOBAL_WORKFLOW.md'):
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('fixture')
    template = root / 'skills/llm-gis/SKILL.md.in'
    template.parent.mkdir(parents=True)
    template.write_text((REPO / 'skills/llm-gis/SKILL.md.in').read_text())
    return root


def installer():
    return runpy.run_path(str(REPO / 'scripts/install-global.py'))['install']


def test_first_install_and_idempotent_rerun(tmp_path, source_repo):
    install = installer()
    result = install(repo=source_repo, home=tmp_path)
    assert result['status'] == 'ok'
    assert (tmp_path / '.local/bin/llm-gis').resolve() == source_repo / 'bin/llm-gis'
    codex = tmp_path / '.codex/skills/llm-gis/SKILL.md'
    claude = tmp_path / '.claude/skills/llm-gis/SKILL.md'
    assert codex.read_text() == claude.read_text()
    assert str(source_repo / 'docs/llm/GLOBAL_WORKFLOW.md') in codex.read_text()
    assert install(repo=source_repo, home=tmp_path)['changed'] == []


def test_check_shows_diff_and_writes_nothing(tmp_path, source_repo):
    install = installer()
    skill = tmp_path / '.claude/skills/llm-gis/SKILL.md'
    skill.parent.mkdir(parents=True)
    skill.write_text('custom instructions\n')
    result = install(repo=source_repo, home=tmp_path, check=True)
    assert '-custom instructions' in result['diff']
    assert skill.read_text() == 'custom instructions\n'
    assert not (tmp_path / '.local').exists()
    assert not (tmp_path / '.codex').exists()


def test_conflict_does_not_partially_install(tmp_path, source_repo):
    install = installer()
    skill = tmp_path / '.claude/skills/llm-gis/SKILL.md'
    skill.parent.mkdir(parents=True)
    skill.write_text('custom\n')
    with pytest.raises(ValueError, match='--replace'):
        install(repo=source_repo, home=tmp_path)
    assert not (tmp_path / '.local').exists()
    assert not (tmp_path / '.codex').exists()
    install(repo=source_repo, home=tmp_path, replace=True)
    assert skill.read_text() != 'custom\n'


def test_conflicting_launcher_is_never_overwritten(tmp_path, source_repo):
    install = installer()
    launcher = tmp_path / '.local/bin/llm-gis'
    launcher.parent.mkdir(parents=True)
    launcher.write_text('different executable')
    with pytest.raises(ValueError, match='launcher'):
        install(repo=source_repo, home=tmp_path, replace=True)
    assert launcher.read_text() == 'different executable'


def test_custom_codex_home(tmp_path, source_repo):
    install = installer()
    codex_home = tmp_path / 'custom-codex'
    install(repo=source_repo, home=tmp_path, codex_home=codex_home)
    assert (codex_home / 'skills/llm-gis/SKILL.md').is_file()
    assert not (tmp_path / '.codex').exists()
