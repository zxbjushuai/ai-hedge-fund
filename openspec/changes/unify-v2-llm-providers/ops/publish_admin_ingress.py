"""Publish owner-requested admin routes; run on the laptop as root.

Uses application authentication only, by explicit owner choice. Does not change
DNS, passwords, application ports, or API routes. Keeps all backup files.
"""

from datetime import datetime, timezone
from pathlib import Path
import shutil
import subprocess
import sys


def run(*args: str) -> None:
    subprocess.run(args, check=True, timeout=45)


def main() -> None:
    directory = Path('/opt/cloudflared/config')
    config = directory / 'config.yml'
    original = config.read_text()
    if sys.argv[1:] == ['--rename-relay-to-sub2api']:
        old = '- hostname: relay.zxbjushuai.com\n'
        new = '- hostname: sub2api.zxbjushuai.com\n'
        if original.count(old) != 1 or new in original:
            raise RuntimeError('Unexpected admin hostname configuration.')
        proposed = original.replace(old, new)
        apply_config(directory, config, original, proposed)
        return
    if sys.argv[1:]:
        raise RuntimeError('Unknown arguments.')
    routes = {
        'relay.zxbjushuai.com': 'http://127.0.0.1:18080',
        'napcat.zxbjushuai.com': 'http://100.84.98.125:6099',
        'astrbot.zxbjushuai.com': 'http://100.84.98.125:6185',
    }
    if any(host in original for host in routes):
        raise RuntimeError('An admin hostname already exists; inspect before changing.')
    catch_all = '- service: http_status:404'
    if original.count(catch_all) != 1 or not original.rstrip().endswith(catch_all):
        raise RuntimeError('Unexpected catch-all layout; refusing automatic edit.')
    block = ''.join(f'- hostname: {host}\n  service: {url}\n' for host, url in routes.items())
    proposed = original.replace(catch_all, block + catch_all)
    apply_config(directory, config, original, proposed)


def apply_config(directory: Path, config: Path, original: str, proposed: str) -> None:
    if config.read_text() != original:
        raise RuntimeError('Configuration changed during preparation.')
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    candidate = directory / f'config.admin-proposed-{stamp}.yml'
    candidate.write_text(proposed)
    run('docker', 'exec', 'cloudflared-cloudflared-1', 'cloudflared',
        'tunnel', '--config', f'/etc/cloudflared/{candidate.name}', 'ingress', 'validate')
    backup = directory / f'config.before-public-admin-{stamp}.yml'
    shutil.copy2(config, backup)
    try:
        config.write_text(proposed)
        run('docker', 'restart', 'cloudflared-cloudflared-1')
        run('docker', 'exec', 'cloudflared-cloudflared-1', 'cloudflared',
            'tunnel', '--config', '/etc/cloudflared/config.yml', 'ingress', 'validate')
    except Exception:
        shutil.copy2(backup, config)
        run('docker', 'restart', 'cloudflared-cloudflared-1')
        raise
    print(f'Configured admin hostnames. Backup: {backup}')
    print('DNS and end-to-end HTTPS/login verification still required.')


if __name__ == '__main__':
    main()
