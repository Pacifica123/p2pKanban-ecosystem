#!/usr/bin/env python3
"""Offline regression for incomplete Cargo cache and the shipped real lock."""
import json
from pathlib import Path
import tempfile
import tomllib
from unittest.mock import patch
import uts_verify as verify

ROOT = Path(__file__).resolve().parents[1]
manifest=tomllib.loads((ROOT/'src-tauri/Cargo.toml').read_text())
lock=tomllib.loads((ROOT/'src-tauri/Cargo.lock').read_text())
assert lock['version']>=3 and len(lock['package'])>100
for name,spec in manifest['dependencies'].items():
    pin=spec if isinstance(spec,str) else spec['version']
    assert any(p['name']==name and p['version']==pin.lstrip('=') for p in lock['package']),name
with tempfile.TemporaryDirectory() as td:
    report=Path(td);(report/'logs').mkdir()
    log=report/'logs/missing.log';log.write_text('error: no matching package named `k256` found\n')
    first=verify.Result('cargo.lock.offline','FAIL',['cargo'],101,0,'logs/missing.log')
    results=[]
    with patch.object(verify,'run_command',return_value=first) as run:
        assert not verify.prepare_cargo_lock({'lockOffline':['cargo','generate-lockfile','--offline']},report/'Cargo.lock',report,results,False)
        assert run.call_count==1
    assert all(r.status=='BLOCKED' for r in results)
    assert '--allow-network' in results[0].note
    log.write_text('error: failed to parse manifest\n')
    first=verify.Result('cargo.lock.offline','FAIL',['cargo'],101,0,'logs/missing.log')
    results=[]
    with patch.object(verify,'run_command',return_value=first):
        assert not verify.prepare_cargo_lock({'lockOffline':['cargo']},report/'Cargo.lock',report,results,False)
    assert results[0].status=='FAIL' # real defects must not be relabeled as cache prerequisites
print('PASS A17b cache prerequisites and real locked dependency pins')
