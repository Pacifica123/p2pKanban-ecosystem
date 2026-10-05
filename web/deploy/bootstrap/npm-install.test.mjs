import assert from 'node:assert/strict';
import test from 'node:test';
import { spawnSync } from 'node:child_process';
import { mkdtempSync, readFileSync, writeFileSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, dirname, delimiter } from 'node:path';
import { fileURLToPath } from 'node:url';
import { shouldRetry, redact } from './npm-install.mjs';

test('retry only transient npm failures and never bad dependency graphs', () => {
  for (const text of ['Exit handler never called!', 'npm error ECONNRESET', 'npm error EAI_AGAIN', 'npm error E503']) {
    assert.equal(shouldRetry(text), true, text);
  }
  for (const text of ['npm error EUSAGE', 'npm error ERESOLVE', 'npm error EINTEGRITY', 'npm error ENOSPC', 'npm error E403', 'postinstall exited 1', 'Exit handler never called! npm error EUSAGE']) {
    assert.equal(shouldRetry(text), false, text);
  }
});

test('diagnostics omit proxy credentials and npm authentication', () => {
  const output = redact('https://user:secret@proxy.test _authToken=abc Authorization: Bearer xyz');
  for (const secret of ['user:secret', 'abc', 'xyz']) assert.equal(output.includes(secret), false);
});

test('a failing npm process retries once with a different cache and an unchanged lock', { skip: process.platform === 'win32' }, () => {
  const root = mkdtempSync(join(tmpdir(), 'p2pkanban-npm-test-'));
  const installer = join(dirname(fileURLToPath(import.meta.url)), 'npm-install.mjs');
  try {
    writeFileSync(join(root, 'package-lock.json'), '{"lockfileVersion":3}\n');
    const lock = readFileSync(join(root, 'package-lock.json'));
    writeFileSync(join(root, 'npm'), `#!/usr/bin/env node
const fs = require('node:fs');
if (process.argv.includes('--version')) { console.log('11.9.0'); process.exit(0); }
let attempts = [];
try { attempts = JSON.parse(fs.readFileSync('attempts.json')); } catch {}
attempts.push(process.env.npm_config_cache);
fs.writeFileSync('attempts.json', JSON.stringify(attempts));
if (process.env.FAKE_NPM_MODE === 'permanent') { console.error('npm error EUSAGE'); process.exit(1); }
if (attempts.length === 1 || process.env.FAKE_NPM_MODE === 'always') { console.error('npm error Exit handler never called!'); process.exit(1); }
`, { mode: 0o755 });
    for (const [mode, code, count] of [['recover', 0, 2], ['permanent', 1, 1], ['always', 1, 2]]) {
      rmSync(join(root, 'attempts.json'), { force: true });
      const result = spawnSync(process.execPath, [installer, 'ci'], {
        cwd: root, encoding: 'utf8', timeout: 15_000,
        env: { ...process.env, PATH: `${root}${delimiter}${process.env.PATH}`, FAKE_NPM_MODE: mode },
      });
      assert.equal(result.status, code, result.stderr);
      const attempts = JSON.parse(readFileSync(join(root, 'attempts.json')));
      assert.equal(attempts.length, count);
      assert.equal(new Set(attempts).size, count);
      assert.deepEqual(readFileSync(join(root, 'package-lock.json')), lock);
    }
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
});

test('network retry reuses verified downloaded packages', { skip: process.platform === 'win32' }, () => {
  const root = mkdtempSync(join(tmpdir(), 'p2pkanban-network-test-'));
  try {
    writeFileSync(join(root, 'package-lock.json'), '{}');
    writeFileSync(join(root, 'npm'), `#!/usr/bin/env node
const fs=require('node:fs');
if(process.argv.includes('--version'))process.exit(0);
let a=[];try{a=JSON.parse(fs.readFileSync('attempts.json'))}catch{}
a.push(process.env.npm_config_cache);fs.writeFileSync('attempts.json',JSON.stringify(a));
if(a.length===1){console.error('ECONNRESET');process.exit(1)}
`, {mode:0o755});
    const result=spawnSync(process.execPath,[join(dirname(fileURLToPath(import.meta.url)),'npm-install.mjs'),'ci'],{cwd:root,encoding:'utf8',timeout:15000,env:{...process.env,PATH:`${root}${delimiter}${process.env.PATH}`}});
    assert.equal(result.status,0,result.stderr);
    const a=JSON.parse(readFileSync(join(root,'attempts.json')));assert.equal(a.length,2);assert.equal(a[0],a[1]);
  } finally {rmSync(root,{recursive:true,force:true});}
});

test('watchdog allows progress, but terminates silent or overlong installs', {skip:process.platform==='win32'}, async()=>{
  const {execute}=await import('./npm-install.mjs');
  const root=mkdtempSync(join(tmpdir(),'p2pkanban-watchdog-'));
  try {
    writeFileSync(join(root,'npm'),`#!/usr/bin/env node
if(process.env.MODE==='silent')setInterval(()=>{},1000);
else {const t=setInterval(()=>console.log('download progress'),50);setTimeout(()=>{clearInterval(t)},500)}
`,{mode:0o755});
    const env={...process.env,PATH:`${root}${delimiter}${process.env.PATH}`};
    // Allow process startup on a loaded host.
    assert.equal((await execute(['ci'],env,20000,5000)).code,0);
    assert.equal((await execute(['ci'],{...env,MODE:'silent'},2000,100)).code,124);
    assert.equal((await execute(['ci'],env,200,250)).code,124);
  }finally{rmSync(root,{recursive:true,force:true});}
});
