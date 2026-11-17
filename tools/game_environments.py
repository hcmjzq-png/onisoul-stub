"""Manage distinct local-test/cloud profiles for the legacy Windows client.

The original game hosts share port 80, so selecting profiles is exclusive while
any client is open. Every gateway switch verifies a server instance ID first;
there is no automatic local/cloud fallback. Credentials stay in private JSON.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import ctypes
from ctypes import wintypes
import datetime
import http.client
import ipaddress
import json
import os
from pathlib import Path
import secrets
import shutil
import socket
import subprocess
import sys
import time
import uuid

GAME_EXE = '鬼武者魂.exe'
HOSTS = ('passport.86joy.com', 'game-onisoul.86joy.com', 'client-onisoul.86joy.com', 'test12242013.86joy.com')
LABELS = {'local-test': '本地测试服', 'cloud': '云端正式服'}
NO_WINDOW = getattr(subprocess, 'CREATE_NO_WINDOW', 0)


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding='utf-8-sig'))


def write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    os.replace(temporary, path)


def process_identity(pid: int) -> dict | None:
    if os.name != 'nt':
        raise OSError('Windows process identity required')
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]
    kernel.GetProcessTimes.argtypes = [wintypes.HANDLE] + [ctypes.POINTER(wintypes.FILETIME)] * 4
    kernel.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
    handle = kernel.OpenProcess(0x1000, False, pid)
    if not handle:
        return None
    try:
        exit_code = wintypes.DWORD()
        if not kernel.GetExitCodeProcess(handle, ctypes.byref(exit_code)) or exit_code.value != 259:
            return None
        name, length = ctypes.create_unicode_buffer(32768), wintypes.DWORD(32768)
        times = [wintypes.FILETIME() for _ in range(4)]
        if not kernel.QueryFullProcessImageNameW(handle, 0, name, ctypes.byref(length)) or not kernel.GetProcessTimes(handle, *(ctypes.byref(t) for t in times)):
            return None
        creation = (times[0].dwHighDateTime << 32) | times[0].dwLowDateTime
        return dict(pid=pid, executable=str(Path(name.value).resolve()), creation_100ns=creation)
    finally:
        kernel.CloseHandle(handle)


def same_process(record: dict, current: dict | None) -> bool:
    return bool(current and record.get('pid') == current['pid']
        and record.get('creation_100ns') == current['creation_100ns']
        and str(record.get('executable', '')).casefold() == current['executable'].casefold())


def game_processes() -> list[dict]:
    class Entry(ctypes.Structure):
        _fields_ = [('dwSize', wintypes.DWORD), ('cntUsage', wintypes.DWORD), ('pid', wintypes.DWORD),
            ('heap', ctypes.c_size_t), ('module', wintypes.DWORD), ('threads', wintypes.DWORD),
            ('parent', wintypes.DWORD), ('priority', wintypes.LONG), ('flags', wintypes.DWORD),
            ('name', wintypes.WCHAR * 260)]
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
    kernel.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    kernel.Process32FirstW.argtypes = kernel.Process32NextW.argtypes = [wintypes.HANDLE, ctypes.POINTER(Entry)]
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    snapshot = kernel.CreateToolhelp32Snapshot(2, 0)
    if snapshot == ctypes.c_void_p(-1).value:
        raise ctypes.WinError(ctypes.get_last_error())
    found = []
    try:
        entry = Entry(dwSize=ctypes.sizeof(Entry))
        valid = kernel.Process32FirstW(snapshot, ctypes.byref(entry))
        while valid:
            if entry.name.casefold() == GAME_EXE.casefold():
                identity = process_identity(entry.pid)
                if identity:
                    found.append(identity)
            valid = kernel.Process32NextW(snapshot, ctypes.byref(entry))
    finally:
        kernel.CloseHandle(snapshot)
    return found


def listening_pids(port: int) -> set[int]:
    rows = subprocess.check_output(['netstat', '-ano', '-p', 'tcp'], creationflags=NO_WINDOW).decode('ascii', 'ignore')
    return {int(parts[-1]) for line in rows.splitlines()
        if len(parts := line.split()) == 5 and parts[0] == 'TCP'
        and parts[1].rsplit(':', 1)[-1] == str(port) and parts[3] == 'LISTENING'}


def get_json(port: int, path='/client/status', timeout=5, host='127.0.0.1') -> dict:
    connection = http.client.HTTPConnection(host, port, timeout=timeout)
    try:
        connection.request('GET', path)
        response = connection.getresponse()
        data = response.read()
        if response.status != 200:
            raise RuntimeError('HTTP health check returned ' + str(response.status))
        return json.loads(data)
    finally:
        connection.close()


def validate_health(value: dict, role: str, instance: str) -> None:
    if value.get('service') != 'onisoul-stub' or value.get('status') != 'up':
        raise RuntimeError('target is not a healthy OniSoul server')
    if value.get('environment') != role or value.get('instance_id') != instance:
        raise RuntimeError('server identity mismatch; environment was not switched')


class Environments:
    def __init__(self, path: Path):
        self.path = path.resolve()
        self.settings = read_json(self.path)
        self.private = self.path.parent
        self.root = Path(self.settings['runtime_root']).resolve()
        self.repo = Path(self.settings['repo']).resolve()
        self.python = self.settings['python']
        self.records = self.private / 'processes'
        self.logs = self.root / 'logs'
        self.records.mkdir(parents=True, exist_ok=True)
        self.logs.mkdir(parents=True, exist_ok=True)

    def record_path(self, name):
        return self.records / (name + '.local.json')

    def live(self, name) -> dict | None:
        path = self.record_path(name)
        if not path.is_file():
            return None
        record = read_json(path)
        return record if same_process(record, process_identity(record.get('pid', 0))) else None

    def stop(self, name) -> None:
        record = self.live(name)
        if not record:
            return
        os.kill(record['pid'], 15)  # Only the exact owned PID/executable/creation time.
        for _ in range(50):
            if not same_process(record, process_identity(record['pid'])):
                return
            time.sleep(.1)
        raise RuntimeError('owned helper did not stop: ' + name)

    def spawn(self, name, command, env=None, cwd=None, extra=None) -> dict:
        if record := self.live(name):
            return record
        command = [str(x) for x in command]
        # Windows venv redirectors otherwise leave an untracked child listening.
        if Path(command[0]).resolve() == Path(self.python).resolve():
            env = (env or os.environ).copy()
            env['__PYVENV_LAUNCHER__'] = self.python
            command[0] = self.settings['python_base']
        with (self.logs / (name + '.stdout.log')).open('ab') as stdout, (self.logs / (name + '.stderr.log')).open('ab') as stderr:
            process = subprocess.Popen(command, env=env, cwd=cwd,
                stdout=stdout, stderr=stderr, creationflags=NO_WINDOW)
        for _ in range(30):
            if process.poll() is not None:
                raise RuntimeError('helper exited; inspect ' + str(self.logs / (name + '.stderr.log')))
            record = process_identity(process.pid)
            if record:
                record.update(extra or {})
                write_json(self.record_path(name), record)
                return record
            time.sleep(.1)
        raise RuntimeError('could not record helper identity')

    def local_env(self) -> dict:
        value = os.environ.copy()
        # Do not inherit another server profile from a developer shell.
        for key in list(value):
            if key.startswith(('ONI_', 'STUB_')) or key == 'AUTH_MODE':
                value.pop(key)
        value.update(ONI_ROOT=str(self.repo), ONI_DB_HOST='127.0.0.1', ONI_DB_PORT='3307',
            ONI_DB_NAME='onisoul_local_test', ONI_DB_USER='oni_local_test',
            ONI_DB_PASSWORD=self.settings['mysql_app_password'], AUTH_MODE='strict', STUB_DEBUG_LOGIN_KEY='',
            ONI_PC_WEB_DIR=str(self.root / 'assets/pc/web'),
            ONI_PC_BUNDLE_DIR=str(self.root / 'assets/pc/bundles'),
            ONI_PC_CACHE_DIR=str(self.root / 'assets/pc/cache'),
            ONI_TABLE_DIR=str(self.root / 'assets/pc/tables'),
            ONI_DATA_DIR=str(self.root / 'data'), ONI_LOG_DIR=str(self.logs / 'local-server'),
            ONI_ENVIRONMENT='local-test', ONI_INSTANCE_ID=self.settings['local_instance'],
            ONI_BUILD_ID=self.settings['build_id'])
        return value

    def mysql(self) -> None:
        import pymysql
        data = self.root / 'mysql/data'
        binary = Path(self.settings['mysql_exe'])
        if not data.exists():
            data.mkdir(parents=True)
            subprocess.run([str(binary), '--no-defaults', '--initialize-insecure', '--datadir=' + str(data)],
                stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, check=True, timeout=120, creationflags=NO_WINDOW)
        if not self.live('mysql'):
            if listening_pids(3307):
                raise RuntimeError('port 3307 belongs to an untracked process')
            self.spawn('mysql', [binary, '--no-defaults', '--datadir=' + str(data),
                '--bind-address=127.0.0.1', '--port=3307', '--mysqlx=OFF', '--skip-log-bin',
                '--performance-schema=OFF', '--innodb-buffer-pool-size=128M', '--max-connections=100'])
        deadline = time.monotonic() + 45
        while True:
            try:
                password = self.settings['mysql_root_password'] if self.settings.get('mysql_configured') else ''
                connection = pymysql.connect(host='127.0.0.1', port=3307, user='root', password=password,
                    connect_timeout=2, autocommit=True)
                break
            except pymysql.Error:
                if time.monotonic() >= deadline:
                    raise RuntimeError('local MySQL readiness failed; inspect mysql logs')
                time.sleep(.2)
        with connection:
            if not self.settings.get('mysql_configured'):
                with connection.cursor() as cursor:
                    cursor.execute('CREATE DATABASE IF NOT EXISTS onisoul_local_test CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci')
                    cursor.execute("CREATE USER IF NOT EXISTS 'oni_local_test'@'127.0.0.1' IDENTIFIED BY %s", (self.settings['mysql_app_password'],))
                    cursor.execute("GRANT ALL ON onisoul_local_test.* TO 'oni_local_test'@'127.0.0.1'")
                    cursor.execute("ALTER USER 'root'@'localhost' IDENTIFIED BY %s", (self.settings['mysql_root_password'],))
                self.settings['mysql_configured'] = True
                write_json(self.path, self.settings)

    def helper(self, role) -> None:
        port = 19766 if role == 'local-test' else 19765
        try:
            if get_json(port, '/health', 1).get('service') == 'onisoul-login-memory':
                if role == 'cloud' or self.live('local-login-memory'):
                    return
                raise RuntimeError('local login helper is not owned by this profile')
        except (OSError, http.client.HTTPException, ValueError):
            pass
        if listening_pids(port):
            raise RuntimeError('login-helper port is occupied by an unknown service')
        store = self.private / 'local-login.dpapi' if role == 'local-test' else self.private.parent / 'login.dpapi'
        self.spawn('local-login-memory' if role == 'local-test' else 'cloud-login-memory',
            [self.python, self.repo / 'tools/login_memory.py', '--port', str(port), '--store', store])

    def backend(self, restart=False) -> None:
        evidence = self.root / 'assets/pc-source-verification.json'
        if not evidence.is_file() or not read_json(evidence).get('verified'):
            raise RuntimeError('finish the verified local asset snapshot first')
        self.mysql()
        if restart:
            self.stop('local-stub')
            self.stop('local-proxy')
        if not self.live('local-stub'):
            if listening_pids(18081):
                raise RuntimeError('port 18081 belongs to an untracked service')
            self.spawn('local-stub', [self.python, '-m', 'app.main', '--host', '127.0.0.1', '--port', '18081', '--init-schema'],
                env=self.local_env(), cwd=self.repo)
        self.wait_health(18081, 'local-test')
        if not self.live('local-proxy'):
            if listening_pids(18082):
                raise RuntimeError('port 18082 belongs to an untracked service')
            env = self.local_env()
            env['ONI_LOG_DIR'] = str(self.logs / 'local-capture')
            self.spawn('local-proxy', [self.python, '-u', self.repo / 'tools/proxy80.py', '--host', '127.0.0.1',
                '--listen', '18082', '--upstream-host', '127.0.0.1', '--upstream', '18081'], env=env, cwd=self.repo)
        self.wait_health(18082, 'local-test')
        self.helper('local-test')

    def wait_health(self, port, role, seconds=30, host='127.0.0.1'):
        deadline = time.monotonic() + seconds
        while True:
            try:
                value = get_json(port, timeout=3, host=host)
                validate_health(value, role, self.settings['local_instance' if role == 'local-test' else 'cloud_instance'])
                return value
            except (OSError, http.client.HTTPException, ValueError, RuntimeError):
                if time.monotonic() >= deadline:
                    raise RuntimeError('expected ' + role + ' server did not pass identity check on port ' + str(port))
                time.sleep(.2)

    def tunnel(self):
        if not self.live('cloud-tunnel'):
            if listening_pids(19880):
                raise RuntimeError('SSH tunnel port belongs to an untracked process')
            self.spawn('cloud-tunnel', [self.settings['ssh_exe'], '-N', '-T', '-o', 'BatchMode=yes',
                '-o', 'ConnectTimeout=8', '-o', 'ExitOnForwardFailure=yes', '-o', 'ServerAliveInterval=15',
                '-o', 'ServerAliveCountMax=3', '-L', '127.0.0.1:19880:127.0.0.1:80', self.settings['ssh_target']])
        return self.wait_health(19880, 'cloud')

    def stop_legacy_gateway(self):
        path = self.private.parent / 'cloud-relay.local.json'
        if not path.is_file():
            raise RuntimeError('port 80 belongs to an untracked service; it was not stopped')
        record = read_json(path)
        current = process_identity(record.get('pid', 0))
        expected = datetime.datetime.fromisoformat(record['started'].replace('Z', '+00:00')).timestamp()
        actual = (current['creation_100ns'] / 10_000_000 - 11644473600) if current else 0
        if not current or record['pid'] not in listening_pids(80) or abs(expected - actual) > .01 or Path(current['executable']).name.lower() != 'python.exe':
            raise RuntimeError('legacy gateway identity mismatch; port 80 was not changed')
        os.kill(current['pid'], 15)
        for _ in range(50):
            if not listening_pids(80):
                return
            time.sleep(.1)
        raise RuntimeError('legacy gateway did not stop')

    def select(self, role, launch=False) -> dict:
        running = game_processes()
        gateway = self.live('gateway')
        if running:
            if gateway and gateway.get('role') == role:
                result = self.wait_health(80, role, seconds=3)
                print(LABELS[role] + '客户端已在运行；没有重复启动。')
                return result
            raise RuntimeError('请先关闭游戏，再切换本地测试服/云端正式服；两个模式共用原游戏域名和80端口。')
        for host in HOSTS:
            if {row[4][0] for row in socket.getaddrinfo(host, 80, family=socket.AF_INET)} != {'127.0.0.1'}:
                raise RuntimeError('game hosts are not exclusively mapped to loopback: ' + host)
        if role == 'local-test':
            self.backend()
            upstream = 18082
            upstream_host = '127.0.0.1'
        else:
            self.helper('cloud')
            if self.settings.get('cloud_transport', 'direct') == 'ssh':
                self.tunnel()
                upstream, upstream_host = 19880, '127.0.0.1'
            else:
                upstream, upstream_host = 80, self.settings['cloud_address']
        # Validate the destination before touching the shared gateway.
        self.wait_health(upstream, role, host=upstream_host)
        if gateway and (gateway.get('upstream_port') != upstream or gateway.get('upstream_host') != upstream_host):
            self.stop('gateway')
            gateway = None
        if gateway and gateway.get('role') != role:
            self.stop('gateway')
            gateway = None
        if not gateway:
            if listening_pids(80):
                self.stop_legacy_gateway()
            env = os.environ.copy()
            env['ONI_LOG_DIR'] = str(self.logs / (role + '-gateway-capture'))
            self.spawn('gateway', [self.python, '-u', self.repo / 'tools/proxy80.py', '--host', '127.0.0.1',
                '--listen', '80', '--upstream-host', upstream_host, '--upstream', str(upstream)],
                env=env, cwd=self.repo, extra=dict(role=role, upstream_host=upstream_host, upstream_port=upstream))
        value = self.wait_health(80, role)
        print(LABELS[role] + ' 已校验，版本 ' + value.get('build_id', 'unknown'))
        if launch:
            root = Path(self.settings['local_client' if role == 'local-test' else 'cloud_client'])
            subprocess.Popen([str(root / GAME_EXE)], cwd=root)
        return value


@contextmanager
def profile_lock(path: Path):
    import msvcrt
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('a+b') as file:
        file.seek(0, 2)
        if file.tell() == 0:
            file.write(b'0')
            file.flush()
        file.seek(0)
        try:
            msvcrt.locking(file.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError as exc:
            raise RuntimeError('另一个环境切换正在进行，请稍后重试。') from exc
        try:
            yield
        finally:
            file.seek(0)
            msvcrt.locking(file.fileno(), msvcrt.LK_UNLCK, 1)


def configure(args) -> None:
    if args.config.exists():
        raise RuntimeError('private profiles already exist; refusing to replace credentials')
    root = args.runtime_root.resolve()
    source = args.source_client.resolve()
    destination = root / 'Client'
    if destination.exists():
        raise RuntimeError('local client directory already exists')
    for name in ('config.ini', 'Cantainer/config.ini', GAME_EXE):
        if not (source / name).is_file():
            raise RuntimeError('source client is incomplete')
    destination.mkdir(parents=True)
    for item in source.iterdir():
        if item.is_file() and item.suffix.lower() in {'.exe', '.dll', '.ini', '.bin', '.ico', '.dat'}:
            if not item.name.lower().startswith('unins'):
                shutil.copy2(item, destination / item.name)
        elif item.is_dir() and item.name in {'Cantainer', 'WebPlayer', 'imageformats', 'sound'}:
            shutil.copytree(item, destination / item.name, ignore=shutil.ignore_patterns('Cache', 'cache'))
    settings = dict(repo=str(Path(__file__).resolve().parents[1]), runtime_root=str(root),
        python=str(args.python.resolve()), python_base=str(Path(sys._base_executable).resolve()), mysql_exe=str(args.mysql.resolve()),
        cloud_client=str(source), local_client=str(destination),
        ssh_exe=str(Path(os.environ['WINDIR']) / 'System32/OpenSSH/ssh.exe'), ssh_target=args.ssh_target,
        cloud_address=str(ipaddress.IPv4Address(args.cloud_address)),
        cloud_transport='direct',
        local_instance='local-' + uuid.uuid4().hex, cloud_instance='cloud-' + uuid.uuid4().hex,
        build_id='environment-setup', mysql_root_password=secrets.token_urlsafe(32),
        mysql_app_password=secrets.token_urlsafe(32), mysql_configured=False)
    write_json(args.config, settings)
    print('Private environment profiles and separate local client created. No cloud database was copied.')


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, required=True)
    parser.add_argument('--action', choices=['configure', 'backend', 'select', 'status'], required=True)
    parser.add_argument('--profile', choices=['local-test', 'cloud'])
    parser.add_argument('--launch', action='store_true')
    parser.add_argument('--restart', action='store_true')
    parser.add_argument('--runtime-root', type=Path)
    parser.add_argument('--source-client', type=Path)
    parser.add_argument('--python', type=Path)
    parser.add_argument('--mysql', type=Path)
    parser.add_argument('--ssh-target')
    parser.add_argument('--cloud-address')
    args = parser.parse_args()
    if os.name != 'nt':
        parser.error('Windows profile launcher required')
    if args.action == 'configure':
        if not all([args.runtime_root, args.source_client, args.python, args.mysql, args.ssh_target, args.cloud_address]):
            parser.error('configure requires explicit runtime, client, Python, MySQL and SSH settings')
        configure(args)
        return
    with profile_lock(args.config.parent / 'switch.lock'):
        manager = Environments(args.config)
        if args.action == 'backend':
            manager.backend(args.restart)
            print('本地测试后端就绪：MySQL 3307 / stub 18081 / proxy 18082')
        elif args.action == 'select':
            if not args.profile:
                parser.error('--profile is required for select')
            manager.select(args.profile, args.launch)
        else:
            print(json.dumps(dict(active_gateway=manager.live('gateway'),
                local_backend=manager.live('local-stub'), local_database=manager.live('mysql'),
                clients=game_processes()), ensure_ascii=False, indent=2))


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        if os.name == 'nt' and Path(sys.executable).name.lower() == 'pythonw.exe':
            ctypes.windll.user32.MessageBoxW(None, str(error), '鬼武者魂：环境未切换', 0x10)
        else:
            print(str(error), file=sys.stderr)
        sys.exit(1)
