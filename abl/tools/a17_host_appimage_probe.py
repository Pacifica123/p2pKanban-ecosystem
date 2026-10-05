#!/usr/bin/env python3
"""Explicit real-image host probe; does not require an AppImage in generic UTS."""
import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from a17_release_kit import ROOT, verify


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--kit', type=Path, required=True)
    ap.add_argument('--fingerprint', required=True)
    ap.add_argument('--minimum-release', type=int, required=True)
    ap.add_argument('--expected-version', required=True)
    ap.add_argument('--report', type=Path, required=True)
    args = ap.parse_args()
    data = verify(args.kit, args.fingerprint, args.minimum_release, args.expected_version)
    checks = []
    with tempfile.TemporaryDirectory(prefix='p2pkanban-a17-host-') as temporary:
        root = Path(temporary)
        for mode in ('fuse', 'extract'):
            environment = os.environ.copy()
            for key, name in [('XDG_DATA_HOME','data'),('XDG_CONFIG_HOME','config'),
                              ('XDG_STATE_HOME','state'),('XDG_CACHE_HOME','cache'),('XDG_RUNTIME_DIR','runtime')]:
                directory = root / mode / name; directory.mkdir(parents=True, mode=0o700)
                environment[key] = str(directory)
            argv = [sys.executable, '-B', str(ROOT / 'tools/a17_release_kit.py'), 'run',
                    '--kit', str(args.kit.absolute()), '--fingerprint', args.fingerprint,
                    '--minimum-release', str(args.minimum_release), '--expected-version', args.expected_version]
            if mode == 'extract':
                argv.append('--extract')
            argv += ['--', 'doctor', '--json']
            try:
                result = subprocess.run(argv, env=environment, capture_output=True, text=True, timeout=60)
                # Require a JSON doctor response, not merely a zero exit from a wrapper.
                doctor = json.loads(result.stdout)
                passed = (result.returncode == 0 and isinstance(doctor, dict)
                          and doctor.get('safeModeRequired') is False
                          and doctor.get('profileExists') is False)
                checks.append({'mode':mode,'pass':passed,'returncode':result.returncode,
                               'stdout':result.stdout[-8192:],'stderr':result.stderr[-8192:]})
            except (subprocess.TimeoutExpired, ValueError) as error:
                checks.append({'mode':mode,'pass':False,'error':str(error)})
    report = {'stage':'A17','appimageSha256':data['files']['p2pkanban.AppImage']['sha256'],
              'checks':checks,'guiVerified':False,'offlineGuiManualEvidencePending':True,
              'pass':all(check['pass'] for check in checks)}
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))
    return 0 if report['pass'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
