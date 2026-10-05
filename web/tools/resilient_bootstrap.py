"""Bounded dependency preparation and portable runtime images; never copies volumes."""
from __future__ import annotations
import hashlib
import json
import re
import tempfile
import time
import zipfile
from pathlib import Path

NETWORK = re.compile(r'tls:|TLS handshake|ECONNRESET|ETIMEDOUT|EAI_AGAIN|unexpected EOF|connection reset|i/o timeout|temporary failure|no such host|too many requests|429|503|504|network is unreachable', re.I)
PERMANENT = re.compile(r'EUSAGE|ERESOLVE|EINTEGRITY|no space left|permission denied|unauthorized|denied:|manifest unknown|no matching manifest|error\[E[0-9]+\]|could not compile|failed to run custom build command|error: the lock file|failed to compile', re.I)

def retryable(text):
    return not PERMANENT.search(text) and bool(NETWORK.search(text))

def digest(path):
    h = hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''): h.update(chunk)
    return h.hexdigest()

def images(tag):
    return ['alpine:3.20', 'postgres:16-alpine', f'p2pkanban/backend:{tag}', f'p2pkanban/web:{tag}', 'p2pkanban/gateway:local']

def inspect(b, root, ref):
    result = b.run_capture([b.docker_executable(), 'image', 'inspect', ref], cwd=root, env=b.os.environ.copy(), timeout=30)
    if result.returncode: return None
    try:
        rows = json.loads(result.stdout)
        return rows[0] if len(rows) == 1 else None
    except (ValueError, TypeError, IndexError): return None

def run_retry(b, command, root, env, log):
    for attempt in range(1, 4):
        attempt_log = log.with_name(log.stem + f'-attempt-{attempt}.log')
        result = b.run_logged(command, cwd=root, env=env, log_path=attempt_log)
        if result.returncode == 0: return
        evidence = attempt_log.read_text(encoding='utf-8', errors='replace')[-131072:]
        if attempt == 3 or not retryable(evidence):
            raise b.BootstrapError(f'Подготовка образов не завершена. Работающий stack не заменён. Лог: {attempt_log}. '
                'При сбое TLS/registry проверьте сеть именно Docker daemon или используйте bundle-import и start --offline. '
                'Проверка TLS не отключается; reset не поможет.')
        print(f'Временный сетевой сбой; повтор {attempt + 1}/3 с сохранённым Docker cache.')
        time.sleep(attempt * 2)

def prepare(b, root, env, log, *, build=True, offline=False):
    refs = images(env['P2PKANBAN_IMAGE_TAG'])
    for ref in refs[:2]:
        if inspect(b, root, ref): continue
        if offline: raise b.BootstrapError(f'Офлайн: отсутствует {ref}. Сначала bundle-import.')
        run_retry(b, [b.docker_executable(), 'pull', ref], root, env, log.with_name(log.stem + '-' + ref.split(':')[0]))
    if build:
        run_retry(b, b.compose_command(root, 'build'), root, env, log.with_name(log.stem + '-build'))
    missing = [ref for ref in refs if not inspect(b, root, ref)]
    if missing: raise b.BootstrapError('Не хватает готовых образов: ' + ', '.join(missing))

def verified_owner(b, root, container):
    labels = b.container_labels(container)
    service = labels.get('com.docker.compose.service')
    if labels.get('com.docker.compose.project') != b.COMPOSE_PROJECT or service not in ('gateway', 'web'): return False
    if not b.container_image(container).startswith(f'p2pkanban/{service}:'): return False
    try:
        pg = b.compose_service_container(root, 'postgres', include_stopped=True)
        backend = b.compose_service_container(root, 'backend', include_stopped=True)
    except b.BootstrapError: return False
    # Names alone are insufficient: verify where data and secrets are mounted.
    expected = {'/var/lib/postgresql/data': b.COMPOSE_PROJECT + '_postgres_data'}
    def mounted(c, required):
        return all(any(m.get('Type') == 'volume' and m.get('Name') == name and m.get('Destination') == path
                       for m in c.get('Mounts', [])) for path, name in required.items())
    secret = {'/run/p2pkanban-secrets': b.COMPOSE_PROJECT + '_bootstrap_secrets'}
    return (b.container_image(pg).startswith('postgres:16') and b.container_image(backend).startswith('p2pkanban/backend:')
            and mounted(pg, expected) and mounted(pg, secret) and mounted(backend, secret))

def bundle_export(args, root, b):
    output = Path(args.output).expanduser().resolve()
    if output.exists(): raise b.BootstrapError('Выходной файл уже существует; выберите новое имя.')
    tag = b.source_image_tag(root, b.source_revision(root))
    env = b.compose_environment(8080, '127.0.0.1', tag)
    b.ensure_docker_ready(root, env)
    prepare(b, root, env, root / '.dev-bootstrap/container-runs/bundle-export.log')
    metadata = {ref: inspect(b, root, ref) for ref in images(tag)}
    platforms = {(i['Os'], i['Architecture']) for i in metadata.values()}
    if len(platforms) != 1: raise b.BootstrapError('Набор образов смешивает платформы.')
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='p2pkanban-bundle-') as directory:
        tar = Path(directory) / 'images.tar'
        result = b.run_capture([b.docker_executable(), 'save', '-o', str(tar), *metadata], cwd=root, env=env, timeout=1800)
        if result.returncode: raise b.BootstrapError('docker save failed: ' + result.stdout[-2000:])
        manifest = {'format': 'p2pkanban-runtime/1', 'sourceFingerprint': b.source_fingerprint(root), 'imageTag': tag,
                    'version': b.read_version(root), 'platform': list(next(iter(platforms))), 'sha256': digest(tar),
                    'images': {ref: item['Id'] for ref, item in metadata.items()}}
        try:
            with zipfile.ZipFile(output, 'x', zipfile.ZIP_STORED) as z:
                z.writestr('manifest.json', json.dumps(manifest, indent=2)); z.write(tar, 'images.tar')
        except BaseException:
            output.unlink(missing_ok=True); raise
    print(f'Готов офлайн-набор: {output}. В нём нет БД, volumes и секретов. Платформа: {manifest["platform"]}.')
    return 0

def bundle_import(args, root, b):
    path = Path(args.bundle).expanduser().resolve()
    env = b.compose_environment(8080, '127.0.0.1')
    b.ensure_docker_ready(root, env)
    try:
        with zipfile.ZipFile(path) as z, tempfile.TemporaryDirectory(prefix='p2pkanban-load-') as directory:
            if sorted(z.namelist()) != ['images.tar', 'manifest.json'] or z.getinfo('manifest.json').file_size > 65536:
                raise b.BootstrapError('Неверный состав офлайн-набора.')
            m = json.loads(z.read('manifest.json'))
            if (m.get('format') != 'p2pkanban-runtime/1' or m.get('sourceFingerprint') != b.source_fingerprint(root)
                or not re.fullmatch(r'[a-zA-Z0-9_.-]{1,128}', str(m.get('imageTag', '')))
                or set(m.get('images', {})) != set(images(m['imageTag']))):
                raise b.BootstrapError('Набор не соответствует этим исходникам. Перенесите тот же каталог проекта без изменения файлов.')
            daemon = b.run_capture([b.docker_executable(), 'version', '--format', '{{.Server.Os}}/{{.Server.Arch}}'], cwd=root, env=env, timeout=30)
            if daemon.returncode or daemon.stdout.strip() != '/'.join(m['platform']):
                raise b.BootstrapError('Архитектура Docker daemon не совпадает с набором.')
            tar = Path(directory) / 'images.tar'
            with z.open('images.tar') as source, tar.open('wb') as target:
                b.shutil.copyfileobj(source, target, 1024 * 1024)
            if digest(tar) != m.get('sha256'): raise b.BootstrapError('Повреждён images.tar: checksum mismatch.')
            result = b.run_capture([b.docker_executable(), 'load', '-i', str(tar)], cwd=root, env=env, timeout=1800)
            if result.returncode: raise b.BootstrapError('docker load failed: ' + result.stdout[-2000:])
            for ref, expected in m['images'].items():
                if (inspect(b, root, ref) or {}).get('Id') != expected: raise b.BootstrapError('Image ID mismatch: ' + ref)
            b.write_json_object(root / '.dev-bootstrap/offline-images.json', m)
    except (OSError, ValueError, KeyError, zipfile.BadZipFile) as exc:
        raise b.BootstrapError(f'Невозможно загрузить набор: {exc}') from exc
    print('Образы проверены. Запуск без registry/build: python bootstrap.py start --offline')
    return 0

def offline_environment(b, root, env):
    m = b.read_json_object(root / '.dev-bootstrap/offline-images.json')
    if (m.get('format') != 'p2pkanban-runtime/1' or m.get('sourceFingerprint') != b.source_fingerprint(root)
        or not re.fullmatch(r'[a-zA-Z0-9_.-]{1,128}', str(m.get('imageTag', '')))
        or set(m.get('images', {})) != set(images(m['imageTag']))):
        raise b.BootstrapError('Для этих исходников нет проверенного bundle-import.')
    for ref, expected in m.get('images', {}).items():
        if (inspect(b, root, ref) or {}).get('Id') != expected: raise b.BootstrapError('Офлайн-образ отсутствует или заменён: ' + ref)
    env['P2PKANBAN_IMAGE_TAG'] = m['imageTag']
    return m


def ready_existing_database(b, root, env):
    pg = b.compose_service_container(root, 'postgres', include_stopped=True)
    if pg.get('State', {}).get('Running'): return
    identifier = pg.get('Id')
    if not identifier: raise b.BootstrapError('Не удалось определить старый PostgreSQL для backup.')
    result = b.run_capture([b.docker_executable(), 'start', identifier], cwd=root, env=env, timeout=60)
    if result.returncode: raise b.BootstrapError('Старый PostgreSQL не запустился для backup; замена отменена.')
    for _ in range(30):
        result = b.run_capture([b.docker_executable(), 'exec', identifier, 'pg_isready', '-U', 'p2pkanban', '-d', 'p2pkanban'], cwd=root, env=env, timeout=5)
        if result.returncode == 0: return
        time.sleep(1)
    raise b.BootstrapError('Старый PostgreSQL не готов для backup; замена отменена.')
