#!/usr/bin/env python3
"""Offline A17 security/packaging behavior, using synthetic artifacts and a frozen public test key.

This gate does NOT claim a compiled AppImage/FUSE/WebKitGTK was tested.
"""
import base64
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from a17_release_kit import ROOT, digest, verify


def command(argv, env=None, success=True):
    result = subprocess.run(argv, cwd=ROOT, env=env, capture_output=True, text=True, timeout=60)
    if success and result.returncode:
        raise AssertionError(result.stdout + result.stderr)
    if not success and not result.returncode:
        raise AssertionError('Expected rejection: ' + str(argv))
    return result


def rejected(call):
    try:
        call()
    except (ValueError, OSError, KeyError):
        return
    raise AssertionError('Tampering/replay was accepted')


assert shutil.which('gpg'), 'GPG required for real signature checks'
base = json.loads((ROOT / 'src-tauri/tauri.conf.json').read_text())
overlay = json.loads((ROOT / 'packaging/appimage/tauri.appimage.conf.json').read_text())
assert base['bundle']['active'] is False
assert overlay == {'bundle': {'active': True, 'targets': ['appimage'],
    'linux': {'appimage': {'bundleMediaFramework': False}}}}
assert 'A17' == json.loads((ROOT / 'tools/uts_plan.json').read_text())['stage']
with tempfile.TemporaryDirectory(prefix='p2pkanban-a17-check-') as temporary:
    work = Path(temporary)
    # Frozen public-key/signed-manifest fixture. It contains no private key and
    # is never executed. Real signatures can be checked without gpg-agent sockets.
    kit = work / 'kit'
    kit.mkdir()
    frozen = json.loads((ROOT / 'fixtures/a17-signed-kit.json').read_text())
    for name, encoded in frozen['filesBase64'].items():
        (kit / name).write_bytes(base64.b64decode(encoded, validate=True))
    fingerprint = json.loads((kit / 'manifest.json').read_text())['signingFingerprint']
    data = verify(kit, fingerprint, 17, '0.1.0')
    assert data['privateSigningMaterialIncluded'] is False
    rejected(lambda: verify(kit, 'F' * 40, 17, '0.1.0'))
    rejected(lambda: verify(kit, fingerprint, 18, '0.1.0'))
    rejected(lambda: verify(kit, fingerprint, 17, '9.9.9'))
    original = (kit / 'manifest.json').read_bytes()
    (kit / 'manifest.json').write_bytes(original + b' ')
    rejected(lambda: verify(kit, fingerprint, 17, '0.1.0'))
    (kit / 'manifest.json').write_bytes(original)
    for name in data['files']:
        path = kit / name; original = path.read_bytes()
        path.write_bytes(original + b'tamper')
        rejected(lambda: verify(kit, fingerprint, 17, '0.1.0'))
        path.write_bytes(original)
    extra = kit / 'unexpected'; extra.write_text('extra')
    rejected(lambda: verify(kit, fingerprint, 17, '0.1.0')); extra.unlink()
    path = kit / 'README.md'; original = path.read_bytes(); path.unlink()
    rejected(lambda: verify(kit, fingerprint, 17, '0.1.0'))
    outside = work / 'outside'; outside.write_bytes(original); path.symlink_to(outside)
    rejected(lambda: verify(kit, fingerprint, 17, '0.1.0')); path.unlink(); path.write_bytes(original)
    verify(kit, fingerprint, 17, '0.1.0')
    # No synthetic test key is ever written to the project or delivered kit.
    assert not any('PRIVATE KEY' in p.read_text(errors='ignore') for p in kit.iterdir())
evidence = json.loads((ROOT / 'evidence/a17-offline-kit.json').read_text())
assert evidence['stage'] == 'A17'
for source in evidence['sources']:
    assert digest(ROOT / source['path']) == source['sha256'], source['path']
print('A17 PASS: real GPG signature/hash/completeness/key/version/replay/symlink gates; real AppImage host acceptance pending')
