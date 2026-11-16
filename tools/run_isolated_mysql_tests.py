"""Run the complete suite against a disposable loopback MySQL on Linux.

Uses a new temporary data directory, never the system MySQL data/config files.
The test instance exists only for this run; each integration test owns its UUID
database. Windows DPAPI and native Unity acceptance remain separate checks.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=33365)
    parser.add_argument("--temp-root", type=Path, help="existing private directory allowed by the host MySQL profile")
    parser.add_argument("--output", type=Path, required=True, help="new evidence directory")
    args = parser.parse_args()
    if sys.platform != "linux" or os.geteuid() == 0:
        parser.error("run as the non-root Linux developer account")
    if not 1024 <= args.port <= 65535 or args.port == 3306:
        parser.error("a nondefault unprivileged test port is required")
    binary = shutil.which("mysqld")
    if not binary:
        parser.error("mysqld is not installed")
    import pymysql

    with socket.socket() as check:
        check.bind(("127.0.0.1", args.port))
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    process = None
    result = 1
    version = "unavailable"
    started = time.monotonic()

    def stop_requested(signum, frame):
        raise KeyboardInterrupt

    previous = signal.signal(signal.SIGTERM, stop_requested)
    try:
        with tempfile.TemporaryDirectory(prefix="oni-test-", dir=args.temp_root) as folder:
            temp = Path(folder)
            data = temp / "data"
            data.mkdir(mode=0o700)
            mysql_log = output / "mysql.log"
            with (output / "mysql-console.log").open("wb") as console:
                subprocess.run([binary, "--no-defaults", "--initialize-insecure",
                                f"--datadir={data}", f"--log-error={mysql_log}"],
                               stdout=console, stderr=subprocess.STDOUT, check=True, timeout=120)
                process = subprocess.Popen([
                    binary, "--no-defaults", f"--datadir={data}",
                    "--bind-address=127.0.0.1", f"--port={args.port}",
                    f"--socket={temp / 'mysql.sock'}", f"--pid-file={temp / 'mysql.pid'}",
                    f"--log-error={mysql_log}", "--mysqlx=OFF", "--skip-log-bin",
                    "--performance-schema=OFF", "--innodb-buffer-pool-size=64M",
                    "--max-connections=50", "--key-buffer-size=8M"],
                    stdout=console, stderr=subprocess.STDOUT)
                try:
                    deadline = time.monotonic() + 60
                    while True:
                        if process.poll() is not None:
                            raise RuntimeError(f"test MySQL exited; see {mysql_log}")
                        try:
                            with pymysql.connect(host="127.0.0.1", port=args.port,
                                                 user="root", password="", connect_timeout=2) as conn:
                                with conn.cursor() as cursor:
                                    cursor.execute("SELECT VERSION()")
                                    version = cursor.fetchone()[0]
                            break
                        except pymysql.Error:
                            if time.monotonic() >= deadline:
                                raise RuntimeError(f"test MySQL readiness timeout; see {mysql_log}")
                            time.sleep(0.2)
                    env = os.environ.copy()
                    for group in ("I", "E", "TUTORIAL"):
                        env[f"ONI_{group}_MYSQL_TEST"] = "1"
                        env[f"ONI_{group}_TEST_PORT"] = str(args.port)
                        env[f"ONI_{group}_TEST_HOST"] = "127.0.0.1"
                        env[f"ONI_{group}_TEST_USER"] = "root"
                        env[f"ONI_{group}_TEST_PASSWORD"] = ""
                    env.update(ONI_DB_HOST="127.0.0.1", ONI_DB_PORT=str(args.port),
                               ONI_DB_USER="root", ONI_DB_PASSWORD="", ONI_DB_NAME="oni_test_unused")
                    with (output / "tests.log").open("wb") as log:
                        result = subprocess.run([sys.executable, "-m", "unittest", "discover",
                                                 "-s", "tests", "-v"], cwd=ROOT, env=env,
                                                stdout=log, stderr=subprocess.STDOUT).returncode
                finally:
                    if process.poll() is None:
                        process.terminate()
                        try:
                            process.wait(timeout=30)
                        except subprocess.TimeoutExpired:
                            process.kill()
                            process.wait(timeout=10)
    finally:
        signal.signal(signal.SIGTERM, previous)
        summary = {"exit_code": result, "mysql_version": version,
                   "seconds": round(time.monotonic() - started, 2),
                   "test_port": args.port, "disposable_datadir": True,
                   "system_database_used": False,
                   "mysql_process_stopped": process is None or process.poll() is not None,
                   "code_commit": subprocess.check_output(
                       ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()}
        (output / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(summary))
    return result


if __name__ == "__main__":
    raise SystemExit(main())
