// Docker-only installer. Keep lockfiles immutable and make npm failures visible.
import { spawn } from 'node:child_process';
import { createHash } from 'node:crypto';
import { mkdtempSync, readFileSync, readdirSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';

export function redact(text) {
  return text
    .replace(/(https?:\/\/)[^\s/@]+:[^\s/@]+@/gi, '$1<redacted>@')
    .replace(/\bBearer\s+\S+/gi, 'Bearer <redacted>')
    .replace(/((?:_authToken|_auth|password|authorization)\s*[=:]\s*)\S+/gi, '$1<redacted>');
}

export function shouldRetry(output) {
  // Lock/peer/integrity/permission errors need a source or environment fix.
  if (/\b(EUSAGE|ERESOLVE|EINTEGRITY|EACCES|ENOSPC|E401|E403|E404)\b/i.test(output)) return false;
  return /Exit handler never called|\b(ECONNRESET|ECONNREFUSED|ETIMEDOUT|ESOCKETTIMEDOUT|EAI_AGAIN|ENETUNREACH|EHOSTUNREACH)\b|\bE5\d\d\b/i.test(output);
}

export function execute(args, env, timeoutMs = 1_800_000, idleMs = 300_000) {
  return new Promise((resolve) => {
    const child = spawn('npm', args, { env, detached: process.platform !== 'win32', stdio: ['ignore', 'pipe', 'pipe'] });
    const terminate = (signal) => { try { if (process.platform !== 'win32' && child.pid) process.kill(-child.pid, signal); else child.kill(signal); } catch {} };
    let tail = '';
    let timedOut = false;
    let killTimer;
    let lastActivity = Date.now();
    const capture = (chunk) => {
      const value = chunk.toString();
      lastActivity = Date.now();
      tail = (tail + value).slice(-262144);
      process.stdout.write(redact(value));
    };
    child.stdout.on('data', capture);
    child.stderr.on('data', capture);
    const stop = (reason) => {
      if (timedOut) return;
      timedOut = true;
      console.error(`npm watchdog: ${reason}; retry may reuse cached packages.`);
      terminate('SIGTERM');
      killTimer = setTimeout(() => terminate('SIGKILL'), 5_000);
    };
    const timer = setTimeout(() => stop('overall time limit'), timeoutMs);
    const idleTimer = setInterval(() => { if (Date.now() - lastActivity > idleMs) stop('no download/build output'); }, Math.min(idleMs, 5000));
    child.on('error', (error) => { tail += String(error); });
    child.on('close', (code, signal) => {
      clearTimeout(timer);
      clearInterval(idleTimer);
      clearTimeout(killTimer);
      resolve({ code: timedOut ? 124 : (code ?? 1), output: tail, signal, timedOut });
    });
  });
}

function debugTail(cache) {
  try {
    const logs = join(cache, '_logs');
    return readdirSync(logs).filter((name) => name.endsWith('.log')).sort().slice(-2)
      .map((name) => readFileSync(join(logs, name), 'utf8').split('\n').slice(-100).join('\n'))
      .join('\n');
  } catch {
    return '';
  }
}

export async function install(args) {
  if (!(args.length === 1 && args[0] === 'ci')
      && args.join(' ') !== 'install --global npm@11.9.0') {
    throw new Error('Expected ci or install --global npm@11.9.0');
  }
  const lockHash = () => createHash('sha256').update(readFileSync('package-lock.json')).digest('hex');
  const before = args[0] === 'ci' ? lockHash() : null;
  console.log(`Build environment: node=${process.version} platform=${process.platform} arch=${process.arch}`);
  await execute(['--version'], process.env, 10_000);
  let sharedCache = process.env.P2PKANBAN_NPM_CACHE;
  const temporaryCaches = [];
  try {
  for (let attempt = 1; attempt <= 2; attempt += 1) {
    const cache = sharedCache || mkdtempSync(join(tmpdir(), 'p2pkanban-npm-'));
    if (!sharedCache) temporaryCaches.push(cache);
    sharedCache = cache;
    try {
      console.log(`npm ${args.join(' ')}: attempt ${attempt}/2 (verified npm cache)`);
      const env = {
        ...process.env,
        npm_config_cache: cache,
        npm_config_audit: 'false',
        npm_config_loglevel: 'http',
        npm_config_prefer_offline: 'true',
        npm_config_fund: 'false',
        npm_config_update_notifier: 'false',
        npm_config_fetch_retries: '2',
        npm_config_fetch_retry_mintimeout: '2000',
        npm_config_fetch_retry_maxtimeout: '10000',
        npm_config_fetch_timeout: '60000',
        npm_config_maxsockets: '5',
        // Retain install/postinstall scripts required by esbuild/Rollup.
        npm_config_foreground_scripts: 'true',
      };
      const result = await execute([...args, '--no-audit', '--no-fund'], env);
      if (before !== null && lockHash() !== before) throw new Error('npm changed package-lock.json');
      if (result.code === 0) return 0;
      const debug = debugTail(cache);
      console.error(redact(debug));
      const evidence = `${result.output}\n${debug}`;
      if (attempt === 2 || (!result.timedOut && !shouldRetry(evidence))) {
        console.error('Dependency installation failed. See npm output above. Check Docker build network/DNS/proxy and registry access; package-lock.json was retained.');
        return result.code;
      }
      if (/Exit handler never called/i.test(evidence)) sharedCache = null;
      console.error('Transient npm failure or timeout: retrying once; lockfile retained, downloaded packages reused when possible.');
    } finally {
      // Cache is retained until all attempts finish.
    }
  }
  return 1;
  } finally { for (const cache of temporaryCaches) rmSync(cache, { recursive: true, force: true }); }
}

if (process.argv[1] === fileURLToPath(import.meta.url)) {
  install(process.argv.slice(2)).then((code) => { process.exitCode = code; }).catch((error) => {
    console.error(redact(String(error)));
    process.exitCode = 1;
  });
}
