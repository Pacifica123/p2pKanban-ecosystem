#!/usr/bin/env python3
"""Convert devctl 0.7 recorded check results to project evidence; never runs commands."""
from __future__ import annotations
import argparse
import json
import re
import uuid
from pathlib import Path


def inside(root: Path, relative: str) -> Path:
    path = (root / relative).resolve()
    if not path.is_relative_to(root.resolve()):
        raise ValueError('Evidence path leaves the devctl workspace')
    return path


def read_json(path: Path):
    if path.stat().st_size > 4 * 1024 * 1024:
        raise ValueError('Evidence JSON exceeds 4 MiB')
    return json.loads(path.read_text(encoding='utf-8'))


def build_receipt(workspace: Path, project: dict, patch_id: str | None = None) -> dict:
    workspace = workspace.resolve()
    if project.get('schemaVersion') != 1 or project.get('resource', {}).get('provider') != 'devctl':
        raise ValueError('Expected exported .p2pkanban/project.json for devctl')
    project_id = str(uuid.UUID(project['projectId']))
    runs = [r for r in read_json(inside(workspace, '.devctl/state.json')).get('runs', [])
            if not patch_id or r.get('patchId') == patch_id]
    if not runs:
        raise ValueError('No matching completed devctl run')
    run = runs[-1]
    status = run.get('status')
    if status not in ('applied', 'push_failed'):
        raise ValueError(f'Latest run is {status!r}; no successful apply evidence')
    digest, commit = run.get('patchSha256', ''), run.get('commitSha', '')
    if not re.fullmatch(r'[a-fA-F0-9]{64}', digest) or not re.fullmatch(r'[a-fA-F0-9]{40}|[a-fA-F0-9]{64}', commit):
        raise ValueError('Missing actual patch checksum or commit')
    run_dir = inside(workspace, run['archiveDir'])
    manifest = read_json(inside(workspace, str((run_dir / 'logs/manifest.json').relative_to(workspace))))
    if manifest.get('patchId') != run['patchId']:
        raise ValueError('Run and archived manifest differ')
    declared = manifest.get('integrations', {}).get('p2pKanban', {})
    if declared and (declared.get('schemaVersion') != 1 or declared.get('projectId') != project_id):
        raise ValueError('Patch targets another project')
    logs = list((run_dir / 'logs').glob('check-*.log'))
    checks = []
    for index, check in enumerate(manifest.get('checks', []), 1):
        matches = [p for p in logs if p.name.startswith(f'check-{index:02d}-')]
        if len(matches) != 1:
            raise ValueError(f'Missing or ambiguous check {index}')
        path = inside(workspace, str(matches[0].relative_to(workspace)))
        with path.open(encoding='utf-8') as handle:
            header = ''.join(handle.readline() for _ in range(6))
        if not header.startswith(f"# Проверка: {check['name']}\n") or not re.search(r'^Код возврата: 0$', header, re.M):
            raise ValueError(f'Check {index} has no passing devctl evidence')
        checks.append({'name': check['name'], 'status': 'passed'})
    refs = []
    for item in declared.get('workItems', []):
        kind, separator, identifier = item.get('ref', '').partition(':')
        if not separator or kind not in ('card', 'checklistItem'):
            raise ValueError('Unsupported work reference')
        uuid.UUID(identifier)
        transition = item.get('requestedTransition')
        if transition not in (None, 'complete'):
            raise ValueError('Unsupported transition intent')
        refs.append({'ref': item['ref'], 'transition': transition})
    identity = '|'.join([project_id, digest.lower(), commit.lower(), run['finishedAt'], status])
    return {'schemaVersion': 1, 'receiptId': str(uuid.uuid5(uuid.NAMESPACE_URL, 'p2pkanban-devctl:' + identity)),
            'projectId': project_id, 'patchId': run['patchId'], 'patchSha256': 'sha256:' + digest.lower(),
            'result': status, 'commit': commit.lower(), 'checks': checks, 'workItems': refs, 'appliedAt': run['finishedAt']}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--workspace', type=Path, required=True)
    parser.add_argument('--project', type=Path, required=True)
    parser.add_argument('--patch-id')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    try:
        receipt = build_receipt(args.workspace, read_json(args.project), args.patch_id)
        with args.output.open('x', encoding='utf-8', newline='\n') as handle:
            json.dump(receipt, handle, ensure_ascii=False, indent=2)
            handle.write('\n')
    except (ValueError, KeyError, OSError) as error:
        parser.exit(1, f'{error}\n')
    print(f'Receipt saved: {args.output}. Preview and import in the board devctl panel; evidence only.')


if __name__ == '__main__':
    main()
