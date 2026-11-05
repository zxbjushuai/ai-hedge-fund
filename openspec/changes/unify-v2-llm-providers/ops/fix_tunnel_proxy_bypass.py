"""Add the laptop origin to cloudflared's proxy bypass; preserve backups.

Run as root on the laptop. The owner approved recreating only the cloudflared
container. Do not restart robot services or pull a different container image.
"""

from datetime import datetime, timezone
from pathlib import Path
import json
import shutil
import subprocess


DIRECTORY = Path('/opt/cloudflared')
CONFIG = DIRECTORY / 'docker-compose.yml'
CONTAINER = 'cloudflared-cloudflared-1'


def run(*args: str) -> None:
    subprocess.run(args, cwd=DIRECTORY, check=True, timeout=90)


def inspect(name: str) -> dict:
    return json.loads(subprocess.check_output(
        ['docker', 'inspect', name], text=True, timeout=10))[0]


def main() -> None:
    original = CONFIG.read_text()
    old = '      - NO_PROXY=localhost,127.0.0.1\n'
    if original.count(old) != 1 or '      - no_proxy=' in original:
        raise RuntimeError('Unexpected proxy configuration; inspect manually.')
    before = inspect(CONTAINER)
    robot_ids = {name: inspect(name)['Id'] for name in ('astrbot', 'napcat')}
    updated = original.replace(old,
        '      - NO_PROXY=localhost,127.0.0.1,100.84.98.125\n'
        '      - no_proxy=localhost,127.0.0.1,100.84.98.125\n')
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    backup = DIRECTORY / f'docker-compose.before-proxy-bypass-{stamp}.yml'
    shutil.copy2(CONFIG, backup)
    try:
        CONFIG.write_text(updated)
        run('docker', 'compose', 'config', '--quiet')
        run('docker', 'compose', 'up', '-d', '--no-deps', '--force-recreate',
            '--pull', 'never', 'cloudflared')
        after = inspect(CONTAINER)
        if after['Image'] != before['Image']:
            raise RuntimeError('Unexpected container image change.')
        if after['State']['Status'] != 'running':
            raise RuntimeError('Tunnel container did not remain running.')
        for name, identity in robot_ids.items():
            if inspect(name)['Id'] != identity:
                raise RuntimeError(f'Unexpected robot container replacement: {name}')
        run('docker', 'exec', CONTAINER, 'cloudflared', 'tunnel', '--config',
            '/etc/cloudflared/config.yml', 'ingress', 'validate')
    except Exception:
        shutil.copy2(backup, CONFIG)
        run('docker', 'compose', 'up', '-d', '--no-deps', '--force-recreate',
            '--pull', 'never', 'cloudflared')
        raise
    print(f'Proxy bypass updated. Backup: {backup}')
    print('Image unchanged; AstrBot and NapCat containers unchanged.')


if __name__ == '__main__':
    main()
