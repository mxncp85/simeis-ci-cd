#!/usr/bin/env python3
"""
Tests fonctionnels Simeis.

Lance le serveur en mode `testing` (port 9345), exécute des scénarios utilisateurs
documentés via le SDK Python, puis arrête le serveur.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT / "tests" / "functional"))

from scenarios import USER_SCENARIOS, unique_username  # noqa: E402
from sdk_loader import SimeisSDK  # noqa: E402

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 9345
DEFAULT_SERVER_BIN = ROOT / "target" / "debug" / "simeis-server"
STARTUP_TIMEOUT_S = 90


def resolve_server_bin(path: Path) -> Path:
    if path.exists():
        return path
    if sys.platform == "win32":
        windows_bin = path.with_suffix(".exe")
        if windows_bin.exists():
            return windows_bin
    return path


def build_server() -> None:
    print("Compilation du serveur (features=testing)...")
    subprocess.run(
        ["cargo", "build", "-p", "simeis-server", "--features", "testing"],
        cwd=ROOT,
        check=True,
    )


def wait_for_ping(host: str, port: int, timeout_s: int = STARTUP_TIMEOUT_S) -> None:
    url = f"http://{host}:{port}/ping"
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=2) as response:
                if response.status == 200:
                    return
        except (urllib.error.URLError, TimeoutError):
            time.sleep(0.5)
    raise RuntimeError(f"Le serveur ne répond pas sur {url} après {timeout_s}s")


def start_server(server_bin: Path, workspace: Path) -> subprocess.Popen[bytes]:
    print(f"Démarrage du serveur: {server_bin}")
    return subprocess.Popen(
        [str(server_bin)],
        cwd=workspace,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def run_scenarios(host: str, port: int, workspace: Path) -> int:
    failures = 0
    previous_cwd = Path.cwd()
    os.chdir(workspace)

    try:
        for scenario in USER_SCENARIOS:
            username = unique_username()
            print(f"\n=== Scénario: {scenario.name} ({scenario.mechanic}) ===")
            for index, step in enumerate(scenario.steps, start=1):
                print(f"  Plan [{index}] {step.action} -> {step.expected}")

            print(f"[RUN] {scenario.name} ({username})")
            try:
                sdk = SimeisSDK(username, host, port)
                scenario.run(sdk)
                print(f"[OK]  {scenario.name}")
            except Exception as err:
                failures += 1
                print(f"[FAIL] {scenario.name}: {err}")
    finally:
        os.chdir(previous_cwd)

    return failures


def main() -> int:
    host = os.environ.get("SIMEIS_HOST", DEFAULT_HOST)
    port = int(os.environ.get("SIMEIS_PORT", str(DEFAULT_PORT)))
    server_bin = resolve_server_bin(
        Path(os.environ.get("SIMEIS_SERVER_BIN", DEFAULT_SERVER_BIN))
    )

    if os.environ.get("SIMEIS_SKIP_BUILD", "").lower() not in {"1", "true", "yes"}:
        if not server_bin.exists():
            build_server()
            server_bin = resolve_server_bin(server_bin)
    elif not server_bin.exists():
        print(f"Binaire serveur introuvable: {server_bin}", file=sys.stderr)
        return 1

    workspace = Path(tempfile.mkdtemp(prefix="simeis-functional-"))
    process: subprocess.Popen[bytes] | None = None

    try:
        process = start_server(server_bin, workspace)
        wait_for_ping(host, port)
        failures = run_scenarios(host, port, workspace)
    finally:
        if process is not None and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
        shutil.rmtree(workspace, ignore_errors=True)

    if failures:
        print(f"\n{failures} scénario(s) fonctionnel(s) en échec.")
        return 1

    print(f"\nTous les scénarios fonctionnels ({len(USER_SCENARIOS)}) ont réussi.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
