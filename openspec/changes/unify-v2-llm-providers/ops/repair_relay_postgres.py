"""One-off, guarded repair for the user's dedicated laptop relay PostgreSQL.

Run as root on the laptop after review. Copies data; never removes the old cluster.
No passwords, database rows, application configuration or system logind settings
are changed. The unrelated distro PostgreSQL cluster must retain its PID.
"""
from __future__ import annotations

import datetime
import hashlib
import json
import os
from pathlib import Path
import pwd
import shutil
import subprocess
import time


BASE = Path('/home/zxbjushuai/api-relay')
OLD = BASE / 'native-postgres'
NEW = Path('/var/lib/personal-relay-postgres')
UNIT = Path('/etc/systemd/system/personal-relay-postgres.service')
SERVICE = 'personal-relay-postgres.service'
SYSTEM_SERVICE = 'postgresql@18-main.service'
CONTAINER = 'personal-relay-sub2api-1'
OWNER = 'relay-postgres'
BIN = Path('/usr/lib/postgresql/18/bin')
SOCKET = '/run/personal-relay-postgres'


def run(*args, timeout=45, output=None):
    return subprocess.run(args, check=True, text=True, stdout=output or subprocess.PIPE,
                          stderr=subprocess.PIPE, timeout=timeout).stdout


def system_pid():
    return run('systemctl', 'show', SYSTEM_SERVICE, '-p', 'MainPID', '--value').strip()


def control_identifier(path):
    text = run(str(BIN / 'pg_controldata'), str(path))
    return next(line.split(':', 1)[1].strip() for line in text.splitlines()
                if line.startswith('Database system identifier:'))


def main():
    if os.geteuid() != 0:
        raise RuntimeError('Run with sudo on the laptop')
    if OLD.resolve() != OLD or NEW.resolve() != NEW or NEW.exists():
        raise RuntimeError('Unexpected source/destination or destination already exists')
    if not (OLD / 'PG_VERSION').read_text().strip() == '18':
        raise RuntimeError('Expected PostgreSQL 18 cluster')
    if any(path.is_symlink() for path in OLD.rglob('*')):
        raise RuntimeError('External data/WAL/tablespaces require separate review')
    original_user = run('systemctl', 'show', SERVICE, '-p', 'User', '--value').strip()
    if original_user != 'zxbjushuai':
        raise RuntimeError('Unexpected original service user')
    original_pid = system_pid()
    if original_pid in {'0', ''}:
        raise RuntimeError('System PostgreSQL baseline is not running')
    identifier = control_identifier(OLD)
    auto_config = (OLD / 'postgresql.auto.conf').read_text()
    if '/home/' in auto_config or 'unix_socket_directories' in auto_config:
        raise RuntimeError('Auto configuration needs explicit path review')
    try:
        owner = pwd.getpwnam(OWNER)
        if owner.pw_uid >= 1000 or owner.pw_dir != str(NEW):
            raise RuntimeError('Existing service user is not the expected system identity')
    except KeyError:
        owner = None

    stamp = datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    backup = BASE / 'backups' / ('postgres-service-' + stamp)
    backup.mkdir(parents=True, mode=0o700)
    backup.chmod(0o700)
    shutil.copy2(UNIT, backup / UNIT.name)
    for filename in ('postgresql.conf', 'postgresql.auto.conf', 'pg_hba.conf', 'pg_ident.conf'):
        shutil.copy2(OLD / filename, backup / filename)
    metadata = dict(backup=str(backup), source=str(OLD), destination=str(NEW),
                    system_pid=original_pid, database_identifier=identifier, state='prepared')
    metadata_path = backup / 'migration.json'

    def record(state):
        metadata['state'] = state
        metadata_path.write_text(json.dumps(metadata, indent=2) + '\n')
        metadata_path.chmod(0o600)
        print(state, flush=True)

    print('backup_directory=' + str(backup), flush=True)
    record('prepared')
    changed_unit = False
    stopped = False
    app_stopped = False
    try:
        run('docker', 'stop', '--time', '20', CONTAINER, timeout=35)
        app_stopped = True
        record('application_stopped')
        run('runuser', '-u', original_user, '--', str(BIN / 'pg_ctl'), '-D', str(OLD),
            '-m', 'fast', '-w', '-t', '30', 'stop', timeout=40)
        stopped = True
        run('systemctl', 'stop', SERVICE)
        control = run(str(BIN / 'pg_controldata'), str(OLD))
        if not any('Database cluster state:' in line and 'shut down' in line for line in control.splitlines()):
            raise RuntimeError('Cluster did not reach a clean shutdown state')
        record('database_cleanly_stopped')
        archive = backup / 'cluster.tar.gz'
        run('tar', '-C', str(OLD), '-czf', str(archive), '.', timeout=120)
        archive.chmod(0o600)
        run('tar', '-tzf', str(archive), timeout=120)
        with archive.open('rb') as stream:
            digest = hashlib.file_digest(stream, 'sha256').hexdigest()
        (backup / 'SHA256SUMS').write_text(digest + '  cluster.tar.gz\n')
        metadata['archive_sha256'] = digest
        record('cold_backup_verified')
        if owner is None:
            run('useradd', '--system', '--user-group', '--no-create-home', '--home-dir', str(NEW),
                '--shell', '/usr/sbin/nologin', OWNER)
        owner = pwd.getpwnam(OWNER)
        if owner.pw_uid >= 1000:
            raise RuntimeError('Service user must be a system user')
        NEW.mkdir(mode=0o700)
        run('rsync', '-a', '--chown=' + OWNER + ':' + OWNER, str(OLD) + '/', str(NEW) + '/', timeout=120)
        os.chown(NEW, owner.pw_uid, owner.pw_gid)
        NEW.chmod(0o700)
        config = NEW / 'postgresql.conf'
        with config.open('a') as stream:
            stream.write("\n# Dedicated relay service: runtime socket independent of user login.\n")
            stream.write("unix_socket_directories = '" + SOCKET + "'\n")
        if control_identifier(NEW) != identifier:
            raise RuntimeError('Copied cluster identifier changed')
        record('data_copied')
        UNIT.write_text('''[Unit]
Description=Dedicated personal API relay PostgreSQL
After=network.target

[Service]
Type=simple
User=relay-postgres
Group=relay-postgres
WorkingDirectory=/var/lib/personal-relay-postgres
ExecStart=/usr/lib/postgresql/18/bin/postgres -D /var/lib/personal-relay-postgres
Restart=on-failure
RestartSec=3
KillSignal=SIGINT
TimeoutStopSec=60
RuntimeDirectory=personal-relay-postgres
RuntimeDirectoryMode=0755
UMask=0077
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=true
ReadWritePaths=/var/lib/personal-relay-postgres

[Install]
WantedBy=multi-user.target
''')
        changed_unit = True
        run('systemd-analyze', 'verify', str(UNIT))
        run('systemctl', 'daemon-reload')
        run('systemctl', 'start', SERVICE)
        for _ in range(30):
            ready = subprocess.run([str(BIN / 'pg_isready'), '-h', '127.0.0.1', '-p', '15432', '-t', '1'],
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            if ready.returncode == 0:
                break
            time.sleep(1)
        else:
            raise RuntimeError('Dedicated database did not become ready')
        query = 'select current_user, current_database(), pg_postmaster_start_time();'
        admin = run('runuser', '-u', original_user, '--', str(BIN / 'psql'), '-X',
                    '-h', SOCKET, '-p', '15432', '-d', 'postgres', '-Atc', query)
        print('database_query=' + admin.strip(), flush=True)
        for filename, command in (
            ('globals.sql', [str(BIN / 'pg_dumpall'), '-h', SOCKET, '-p', '15432', '--globals-only']),
            ('sub2api.dump', [str(BIN / 'pg_dump'), '-h', SOCKET, '-p', '15432', '-Fc', '-d', 'sub2api']),
        ):
            with (backup / filename).open('w') as stream:
                run('runuser', '-u', original_user, '--', *command, output=stream, timeout=120)
            (backup / filename).chmod(0o600)
        if system_pid() != original_pid:
            raise RuntimeError('Unrelated system cluster PID changed')
        record('database_verified_and_logically_backed_up')
        run('docker', 'start', CONTAINER)
        app_stopped = False
        record('completed')
        print('service_user=' + OWNER + ' uid=' + str(owner.pw_uid), flush=True)
        print('system_cluster_pid_unchanged=' + original_pid, flush=True)
    except Exception as error:
        print('repair_failed=' + type(error).__name__, flush=True)
        # Private diagnostics may contain database details; never print them.
        (backup / 'failure.txt').write_text(str(error) + '\n' + str(getattr(error, 'stderr', '')))
        (backup / 'failure.txt').chmod(0o600)
        try:
            if changed_unit:
                run('systemctl', 'stop', SERVICE)
                shutil.copy2(backup / UNIT.name, UNIT)
                run('systemctl', 'daemon-reload')
            if stopped:
                run('systemctl', 'start', SERVICE)
            if app_stopped:
                run('docker', 'start', CONTAINER)
            record('rolled_back')
        except Exception:
            record('manual_recovery_required')
        raise SystemExit(1)


if __name__ == '__main__':
    main()
