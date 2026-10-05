import assert from 'node:assert/strict';
import test from 'node:test';
import { spawnSync } from 'node:child_process';
import { mkdtempSync, writeFileSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { expoCommand, gradleCommand } from './apk-commands.mjs';

test('Expo uses the installed CLI through node without npx or a shell', () => {
  const cli = 'C:\\Users\\Тест & User\\my project\\node_modules\\expo\\bin\\cli';
  const [command, args] = expoCommand('C:\\Program Files\\nodejs\\node.exe', cli);
  assert.equal(command, 'C:\\Program Files\\nodejs\\node.exe');
  assert.equal(args[0], cli);
  assert.deepEqual(args.slice(1), ['prebuild', '--platform', 'android', '--clean', '--no-install']);
});

test('Windows uses cmd with a fixed command, Linux executes the wrapper with sh', () => {
  assert.deepEqual(gradleCommand('win32', { ComSpec: 'C:\\Windows\\System32\\cmd.exe' }),
    ['C:\\Windows\\System32\\cmd.exe', ['/d', '/s', '/c', 'gradlew.bat assembleRelease']]);
  assert.deepEqual(gradleCommand('linux'), ['sh', ['./gradlew', 'assembleRelease']]);
});

test('Gradle execution preserves cwd and arguments on the actual host', () => {
  const cwd = mkdtempSync(join(tmpdir(), 'p2pkanban Тест & spaces-'));
  try {
    if (process.platform === 'win32') {
      writeFileSync(join(cwd, 'gradlew.bat'), '@echo off\r\necho ARG=%1\r\nexit /b 7\r\n');
    } else {
      writeFileSync(join(cwd, 'gradlew'), '#!/bin/sh\nprintf "ARG=%s\\n" "$1"\nexit 7\n');
    }
    const [command, args] = gradleCommand(process.platform);
    const result = spawnSync(command, args, { cwd, encoding: 'utf8', shell: false });
    assert.equal(result.error, undefined);
    assert.equal(result.status, 7);
    assert.match(result.stdout, /ARG=assembleRelease/);
  } finally {
    rmSync(cwd, { recursive: true, force: true });
  }
});
