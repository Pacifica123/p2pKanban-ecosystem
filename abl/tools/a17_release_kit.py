#!/usr/bin/env python3
"""A17 signed offline release kit. Verify with a separately trusted fingerprint.

No download, package installation, private key export or profile mutation. The
verifier itself must come from trusted source, not an unauthenticated download.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
import platform
import re
import shutil
import stat
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FORMAT = 'p2pkanban-offline-kit/1'
FINGERPRINT = re.compile(r'(?:[A-F0-9]{40}|[A-F0-9]{64})\Z')
NAME = re.compile(r'[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z')


def fail(message):
    raise ValueError(message)


def regular(path):
    if not stat.S_ISREG(path.lstat().st_mode):
        fail('Expected regular file (no symlink): ' + str(path))
    return path


def digest(path):
    h = hashlib.sha256()
    with regular(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def run(argv, **kwargs):
    result = subprocess.run(argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE, **kwargs)
    if result.returncode:
        fail('Command failed: ' + str(argv[0]) + ': ' + result.stderr.decode(errors='replace')[-2000:])
    return result.stdout


def fingerprint(value):
    value = value.upper()
    if not FINGERPRINT.fullmatch(value):
        fail('A complete independently trusted GPG fingerprint is required')
    return value


def verify_signature(manifest, signature, public_key, expected):
    # Use an isolated keyring and explicitly disable key fetching. The bundled
    # key is a transport convenience; the caller-pinned primary fingerprint owns trust.
    expected = fingerprint(expected)
    with tempfile.TemporaryDirectory(prefix='p2pkanban-a17-gpg-') as temporary:
        if regular(public_key).stat().st_size > 262144 or regular(signature).stat().st_size > 65536:
            fail('Oversized public key or signature')
        keyring = Path(temporary) / 'release-public.gpg'
        run(['gpg', '--homedir', temporary, '--batch', '--no-autostart', '--output',
             str(keyring), '--dearmor', str(regular(public_key))], timeout=30)
        base = ['gpg', '--homedir', temporary, '--batch', '--no-autostart',
                '--no-auto-key-retrieve', '--no-default-keyring', '--keyring', str(keyring)]
        status = run(base + ['--status-fd', '1', '--verify', str(regular(signature)), str(regular(manifest))], timeout=30)
        valid = []
        for line in status.decode().splitlines():
            fields = line.split()
            if fields[:2] == ['[GNUPG:]', 'VALIDSIG']:
                # A signing subkey's VALIDSIG ends in the primary fingerprint.
                valid.append(fields[-1] if len(fields) >= 12 else fields[2])
        if valid != [expected]:
            fail('Signature does not match the independently trusted primary fingerprint')


def verify(directory, expected, minimum_release, expected_version):
    if type(minimum_release) is not int or minimum_release < 1:
        fail('A positive separately trusted minimum release is required')
    directory = directory.absolute()
    if directory.is_symlink() or not directory.is_dir():
        fail('Kit must be a real directory')
    manifest = regular(directory / 'manifest.json')
    if manifest.stat().st_size > 262144:
        fail('Manifest is too large')
    raw = manifest.read_bytes()
    if len(raw) > 262144:
        fail('Manifest is too large')
    with tempfile.TemporaryDirectory(prefix='p2pkanban-a17-manifest-') as temporary:
        frozen = Path(temporary) / 'manifest.json'
        frozen.write_bytes(raw)
        verify_signature(frozen, directory / 'manifest.json.sig', directory / 'release-public-key.asc', expected)
    data = json.loads(raw)
    if data.get('format') != FORMAT or data.get('architecture') != 'x86_64':
        fail('Unsupported kit format or architecture')
    release = data.get('releaseSequence')
    if type(release) is not int or release < minimum_release or release < 1:
        fail('Release replay/downgrade refused')
    if data.get('appVersion') != expected_version or data.get('signingFingerprint') != fingerprint(expected):
        fail('Unexpected application version or signing key')
    files = data.get('files')
    if not isinstance(files, dict) or not files or len(files) > 32:
        fail('Invalid file inventory')
    required = {'p2pkanban.AppImage', 'release-public-key.asc', 'README.md', 'A16_RECOVERY.md', 'verify-kit.py',
                'PKGBUILD', 'release-inputs.json', 'build-record.json', 'p2pkanban.desktop', 'LICENSE'}
    if not required.issubset(files) or not any(name.endswith('.tar.gz') for name in files):
        fail('Kit is incomplete')
    if set(p.name for p in directory.iterdir()) != set(files) | {'manifest.json', 'manifest.json.sig'}:
        fail('Unexpected/missing kit members')
    for name, metadata in files.items():
        if not isinstance(name, str) or not NAME.fullmatch(name) or name in {'manifest.json', 'manifest.json.sig'}:
            fail('Unsafe inventory name')
        if not isinstance(metadata, dict) or type(metadata.get('bytes')) is not int or metadata['bytes'] < 0:
            fail('Invalid file metadata')
        path = regular(directory / name)
        if path.stat().st_size != metadata['bytes'] or digest(path) != metadata.get('sha256'):
            fail('Hash/size mismatch: ' + name)
    return data


def stage(args):
    from a15_prepare_release import read_versions
    expected = fingerprint(args.signing_key)
    version = read_versions()
    inputs = args.release_inputs.absolute()
    metadata = json.loads(regular(inputs / 'release-inputs.json').read_text())
    if metadata.get('format') != 'p2pkanban-arch-release-inputs' or metadata.get('appVersion') != version:
        fail('A15 release-inputs version/format mismatch')
    archive_meta = metadata['sourceArchive']
    if not NAME.fullmatch(archive_meta['filename']):
        fail('Unsafe source archive name')
    archive = regular(inputs / archive_meta['filename'])
    if digest(archive) != archive_meta['sha256'] or archive.stat().st_size != archive_meta['bytes']:
        fail('A15 source archive hash mismatch')
    image = regular(args.appimage.absolute())
    record = json.loads(regular(args.build_record.absolute()).read_text())
    if (record.get('format') != 'p2pkanban-appimage-build/1' or record.get('appVersion') != version
        or record.get('sourceSha256') != digest(archive) or record.get('appimageSha256') != digest(image)
        or record.get('overlaySha256') != digest(ROOT / 'packaging/appimage/tauri.appimage.conf.json')):
        fail('Build record does not bind this AppImage to the A15 source and A17 overlay')
    with image.open('rb') as stream:
        header = stream.read(20)
    if len(header) < 20 or header[:4] != b'\x7fELF' or header[4:6] != b'\x02\x01' or header[8:11] != b'AI\x02' or header[18:20] != b'\x3e\x00':
        fail('Expected x86_64 ELF Type-2 AppImage, not a renamed executable')
    if args.release_sequence < 1 or not args.build_baseline.strip():
        fail('Positive release sequence and measured build baseline required')
    output = args.output.absolute()
    if output.exists() or output.is_symlink():
        fail('Output exists; choose a new directory (never overwrite a release)')
    if output == ROOT or ROOT in output.parents:
        if output.relative_to(ROOT).parts[0] != '.uts-reports':
            fail('Repository staging is only permitted in ignored .uts-reports')
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.a17-stage-', dir=output.parent) as temporary:
        staged = Path(temporary) / 'kit'
        staged.mkdir(mode=0o700)
        sources = {
            'p2pkanban.AppImage': image,
            archive.name: archive,
            'release-inputs.json': inputs / 'release-inputs.json',
            'PKGBUILD': inputs / 'PKGBUILD',
            'p2pkanban.desktop': inputs / 'p2pkanban.desktop',
            'LICENSE': inputs / 'LICENSE',
            'build-record.json': args.build_record.absolute(),
            'README.md': ROOT / 'docs/A17_OFFLINE_KIT.md',
            'A16_RECOVERY.md': ROOT / 'docs/A16_RECOVERY.md',
            'verify-kit.py': Path(__file__),
        }
        for name, source in sources.items():
            shutil.copyfile(regular(source), staged / name)
        # Public export only. Signing remains in the caller's external gpg-agent.
        public = run(['gpg', '--batch', '--armor', '--export', expected], timeout=30)
        if not public:
            fail('Signing public key unavailable')
        (staged / 'release-public-key.asc').write_bytes(public)
        files = {p.name: {'bytes': p.stat().st_size, 'sha256': digest(p)} for p in sorted(staged.iterdir())}
        data = {'format': FORMAT, 'appVersion': version, 'architecture': 'x86_64',
                'releaseSequence': args.release_sequence, 'buildBaseline': args.build_baseline,
                'signingFingerprint': expected, 'files': files,
                'profileSchema': 6, 'privateSigningMaterialIncluded': False,
                'pacmanStateModified': False}
        (staged / 'manifest.json').write_text(json.dumps(data, indent=2, sort_keys=True) + '\n')
        run(['gpg', '--batch', '--local-user', expected, '--output', str(staged / 'manifest.json.sig'),
             '--detach-sign', str(staged / 'manifest.json')], timeout=60)
        verify(staged, expected, args.release_sequence, version)
        staged.rename(output)
    print(json.dumps({'result': 'verified', 'output': str(output), 'releaseSequence': args.release_sequence}))


def launch(directory, data, extract, application_args, env=None):
    if platform.machine() not in ('x86_64', 'AMD64'):
        fail('This kit supports x86_64 only')
    # Copy to a private execution directory and bind that copy to the signed hash.
    # The original kit remains immutable, even when FUSE is unavailable.
    with tempfile.TemporaryDirectory(prefix='p2pkanban-a17-run-') as temporary:
        private = Path(temporary)
        image = private / 'p2pkanban.AppImage'
        shutil.copyfile(regular(directory / 'p2pkanban.AppImage'), image)
        if digest(image) != data['files']['p2pkanban.AppImage']['sha256']:
            fail('Image changed after verification')
        image.chmod(0o700)
        executable = image
        if extract:
            run([str(image), '--appimage-extract'], cwd=private, env=env, timeout=120)
            executable = private / 'squashfs-root' / 'AppRun'
            if not executable.exists() or not executable.resolve().is_relative_to(private):
                fail('Extracted AppRun is missing or escapes the private directory')
        return subprocess.run([str(executable), *application_args], cwd=private, env=env).returncode


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    build = commands.add_parser('stage')
    build.add_argument('--appimage', type=Path, required=True)
    build.add_argument('--build-record', type=Path, required=True)
    build.add_argument('--release-inputs', type=Path, required=True)
    build.add_argument('--signing-key', required=True)
    build.add_argument('--release-sequence', type=int, required=True)
    build.add_argument('--build-baseline', required=True, help='Recorded distro/glibc/WebKit build environment')
    build.add_argument('--output', type=Path, required=True)
    for command in ('verify', 'run'):
        sub = commands.add_parser(command)
        sub.add_argument('--kit', type=Path, required=True)
        sub.add_argument('--fingerprint', required=True, help='Trusted independently of this kit')
        sub.add_argument('--minimum-release', type=int, required=True)
        sub.add_argument('--expected-version', required=True)
        if command == 'run':
            sub.add_argument('--extract', action='store_true', help='Explicit non-FUSE extraction mode')
            sub.add_argument('application_args', nargs=argparse.REMAINDER)
    args = parser.parse_args()
    try:
        if args.command == 'stage':
            stage(args)
            return 0
        if args.minimum_release < 1:
            fail('A positive separately trusted minimum release is required')
        data = verify(args.kit, args.fingerprint, args.minimum_release, args.expected_version)
        if args.command == 'verify':
            print(json.dumps({'result': 'verified', 'releaseSequence': data['releaseSequence'], 'appVersion': data['appVersion']}))
            return 0
        app_args = args.application_args
        if app_args[:1] == ['--']:
            app_args = app_args[1:]
        return launch(args.kit.absolute(), data, args.extract, app_args)
    except (OSError, ValueError, KeyError, TypeError, subprocess.TimeoutExpired) as error:
        print('A17 FAILED: ' + str(error))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
