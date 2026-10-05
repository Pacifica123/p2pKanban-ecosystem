#!/usr/bin/env python3
"""Build A17 from the immutable A15 source, not from the mutable working tree.

Release builder only. Requires compatible cargo-tauri CLI and build dependencies.
Allowing network preparation is explicit; the resulting installation kit is offline.
"""
from __future__ import annotations
import argparse
import json
import os
import platform
import shutil
import subprocess
import tarfile
import tempfile
from pathlib import Path
from a17_release_kit import digest, fail, regular, ROOT, NAME


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--release-inputs', type=Path, required=True)
    ap.add_argument('--output', type=Path, required=True, help='New directory outside the source tree')
    ap.add_argument('--allow-network', action='store_true', help='Allow dependency/tool preparation on the builder')
    args = ap.parse_args()
    if platform.machine() != 'x86_64':
        fail('A17 builder supports x86_64 only')
    inputs = args.release_inputs.absolute()
    metadata = json.loads(regular(inputs / 'release-inputs.json').read_text())
    if metadata.get('format') != 'p2pkanban-arch-release-inputs' or metadata.get('architecture') != 'x86_64':
        fail('A15 release-inputs format/architecture mismatch')
    if not NAME.fullmatch(metadata['sourceArchive']['filename']):
        fail('Unsafe source archive name')
    source = regular(inputs / metadata['sourceArchive']['filename'])
    if digest(source) != metadata['sourceArchive']['sha256']:
        fail('A15 source hash mismatch')
    output = args.output.absolute()
    if output.exists() or output.is_symlink() or output == ROOT or ROOT in output.parents:
        fail('Build output must be new and outside the source tree')
    for command in ('npm', 'cargo'):
        if not shutil.which(command):
            fail('Missing release build tool: ' + command)
    cli = subprocess.run(['cargo', 'tauri', '--version'], capture_output=True, text=True, check=True).stdout.strip()
    if not cli.startswith('tauri-cli 2.'):
        fail('Compatible cargo-tauri 2.x CLI is required')
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.a17-build-', dir=output.parent) as directory:
        temporary = Path(directory)
        with tarfile.open(source, 'r:gz') as archive:
            # Python data filter rejects path escapes/device members. The A15
            # archive is internally produced but still validated before extraction.
            archive.extractall(temporary, filter='data')
        build = temporary / ('p2pkanban-' + metadata['appVersion'])
        if not build.is_dir():
            fail('Source archive prefix mismatch')
        overlay = temporary / 'tauri.appimage.conf.json'
        shutil.copyfile(ROOT / 'packaging/appimage/tauri.appimage.conf.json', overlay)
        environment = os.environ.copy()
        if not args.allow_network:
            environment['CARGO_NET_OFFLINE'] = 'true'
        install = ['npm', 'ci', '--ignore-scripts', '--no-audit', '--no-fund']
        if not args.allow_network:
            install.append('--offline')
        commands = [install, ['npm', 'run', 'build'], ['cargo', 'tauri', 'build', '--ci', '--bundles',
                    'appimage', '--config', str(overlay), '--', '--locked']]
        log = temporary / 'build.log'
        with log.open('wb') as stream:
            for command in commands:
                result = subprocess.run(command, cwd=build, env=environment, stdout=stream, stderr=subprocess.STDOUT)
                if result.returncode:
                    # Retain a failure log under a distinct sibling, never an apparent release.
                    failure = output.with_name(output.name + '.failed.log')
                    with failure.open('xb') as destination:
                        destination.write(log.read_bytes())
                    fail('Build failed; log: ' + str(failure))
        images = list((build / 'src-tauri/target/release/bundle/appimage').glob('*.AppImage'))
        if len(images) != 1:
            fail('Bundler did not produce exactly one AppImage')
        stage = temporary / 'result'
        stage.mkdir()
        image = stage / 'p2pkanban.AppImage'
        shutil.copyfile(regular(images[0]), image)
        baseline = {'platform': platform.platform(), 'libc': list(platform.libc_ver()),
                    'tauriCli': cli, 'networkPreparationAllowed': args.allow_network}
        record = {'format': 'p2pkanban-appimage-build/1', 'appVersion': metadata['appVersion'],
                  'sourceSha256': digest(source), 'appimageSha256': digest(image),
                  'overlaySha256': digest(overlay), 'baseline': baseline}
        (stage / 'build-record.json').write_text(json.dumps(record, indent=2, sort_keys=True) + '\n')
        shutil.copyfile(log, stage / 'build.log')
        stage.rename(output)
    print('A17 AppImage built: ' + str(output))
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (ValueError, OSError, KeyError, subprocess.CalledProcessError) as error:
        raise SystemExit('A17 BUILD FAILED: ' + str(error))
