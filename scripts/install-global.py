#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""Install the host launcher and equivalent Codex/Claude skills."""
from __future__ import annotations

import argparse
import difflib
import json
import os
from pathlib import Path
import sys


def install(*, repo: Path, home: Path, codex_home: Path | None = None,
            check: bool = False, replace: bool = False) -> dict:
    repo, home = repo.resolve(), home.resolve()
    launcher = home / '.local/bin/llm-gis'
    target = repo / 'bin/llm-gis'
    for source in (target, repo / 'AGENTS.md', repo / 'docs/llm/GLOBAL_WORKFLOW.md'):
        if not source.is_file():
            raise ValueError(f'Required installation source does not exist: {source}')
    template = (repo / 'skills/llm-gis/SKILL.md.in').read_text(encoding='utf-8')
    rendered = template.replace('@@REPO@@', str(repo)).replace('@@LAUNCHER@@', str(launcher))
    codex_root = codex_home.expanduser().resolve() if codex_home else home / '.codex'
    skills = [codex_root / 'skills/llm-gis/SKILL.md', home / '.claude/skills/llm-gis/SKILL.md']
    changes = []
    diffs = []
    conflicts = []
    for skill in skills:
        exists = skill.exists() or skill.is_symlink()
        old = skill.read_text(encoding='utf-8') if exists else ''
        if old != rendered:
            changes.append(skill)
            diffs.append(''.join(difflib.unified_diff(
                old.splitlines(keepends=True), rendered.splitlines(keepends=True),
                fromfile=str(skill), tofile=str(skill) + ' (proposed)')))
            if exists:
                conflicts.append(skill)
    launcher_exists = launcher.exists() or launcher.is_symlink()
    launcher_matches = launcher.is_symlink() and launcher.resolve() == target
    launcher_conflict = launcher_exists and not launcher_matches
    result = {
        'status': 'ok', 'mode': 'check' if check else 'install',
        'launcher': str(launcher), 'skills': [str(p) for p in skills],
        'changed': [str(p) for p in changes] + ([] if launcher_matches else [str(launcher)]),
        'diff': '\n'.join(diffs),
        'launcher_conflict': launcher_conflict,
        'path_hint': f'Use {launcher} directly or add {launcher.parent} to PATH.',
    }
    if check:
        return result
    # Preflight all conflicts before changing any destination.
    if launcher_conflict:
        raise ValueError(f'Existing launcher is unrelated; leave it in place and resolve manually: {launcher}')
    if conflicts and not replace:
        raise ValueError('Existing skills differ. Run --check, review the diff, then use --replace: '
                         + ', '.join(map(str, conflicts)))
    for skill in changes:
        skill.parent.mkdir(parents=True, exist_ok=True)
        # Replace the skill entry itself, not the target of a pre-existing symlink.
        if skill.is_symlink():
            skill.unlink()
        skill.write_text(rendered, encoding='utf-8')
    if not launcher_matches:
        launcher.parent.mkdir(parents=True, exist_ok=True)
        launcher.symlink_to(target)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true', help='Show proposed skill diffs; write nothing')
    parser.add_argument('--replace', action='store_true', help='Replace differing skills after reviewing --check')
    args = parser.parse_args()
    try:
        root = Path(__file__).resolve().parents[1]
        codex_home = Path(os.environ['CODEX_HOME']) if os.environ.get('CODEX_HOME') else None
        result = install(repo=root, home=Path.home(), codex_home=codex_home,
                         check=args.check, replace=args.replace)
    except (OSError, ValueError) as exc:
        print(json.dumps({'status': 'error', 'code': 'INSTALL_FAILED', 'message': str(exc),
                          'suggested_action': 'Check the paths and review --check before replacing skills.'}),
              file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
