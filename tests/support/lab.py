"""Local snmpsim lab: one simulator process per synthetic device on 127.0.0.x addresses.

Shared by the integration tests and by developers:

    python -m tests.support.lab            # starts the lab, writes a config, waits for Ctrl-C

Linux routes the whole 127.0.0.0/8 range to the loopback interface, so every simulated device
gets its own IP address without any setup.
"""

from __future__ import annotations

import argparse
import asyncio
import importlib.util
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "snmprec"
V3_USER, V3_AUTH, V3_PRIV = "snowth", "authkey-lab-1", "privkey-lab-1"
# snmpsim serves a data file per community name. Not "public": every secret is masked in any
# output, so a trivial community would also be masked inside unrelated words.
COMMUNITY = "lab-ro-community"

# agent name -> (loopback addresses, serves our SNMPv3 user)
LAB = {
    "sw-access": (["127.0.0.11"], True),
    "sw-generic": (["127.0.0.12"], True),
    "fw": (["127.0.0.13"], False),          # v2c only: exercises the credential fallback
    "printer": (["127.0.0.14"], True),
    "ups": (["127.0.0.15"], True),
    "linux": (["127.0.0.16"], True),
    "dual": (["127.0.0.17", "127.0.0.18"], True),
    "ap": (["127.0.0.20"], True),
}
DEAD = "127.0.0.19"


def responder_path() -> str | None:
    exe = Path(sys.executable).with_name("snmpsim-command-responder")
    if exe.exists():
        return str(exe)
    return shutil.which("snmpsim-command-responder")


def have_snmpsim() -> bool:
    return responder_path() is not None and importlib.util.find_spec("pysmi") is not None


@dataclass
class RunningLab:
    port: int
    root: Path
    procs: list[subprocess.Popen] = field(default_factory=list)

    def address(self, host: str) -> str:
        return f"{host}:{self.port}"

    def agent(self, name: str, index: int = 0) -> str:
        return self.address(LAB[name][0][index])

    def all_seeds(self, with_dead: bool = True) -> list[str]:
        seeds = [self.address(h) for hosts, _ in LAB.values() for h in hosts]
        return seeds + ([self.address(DEAD)] if with_dead else [])

    def stop(self) -> None:
        for proc in self.procs:
            proc.terminate()
        for proc in self.procs:
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


async def _wait_ready(hosts: list[str], port: int, deadline: float) -> list[str]:
    from pysnmp.hlapi.v3arch.asyncio import (
        CommunityData,
        ContextData,
        ObjectIdentity,
        ObjectType,
        SnmpEngine,
        UdpTransportTarget,
        get_cmd,
    )

    engine = SnmpEngine()
    pending = list(hosts)
    try:
        while pending and time.monotonic() < deadline:
            for host in list(pending):
                transport = await UdpTransportTarget.create((host, port), timeout=0.3, retries=0)
                err, _, _, _ = await get_cmd(engine, CommunityData(COMMUNITY, mpModel=1),
                                             transport, ContextData(),
                                             ObjectType(ObjectIdentity("1.3.6.1.2.1.1.5.0")),
                                             lookupMib=False)
                if not err:
                    pending.remove(host)
    finally:
        engine.close_dispatcher()
    return pending


def start_lab(root: Path, port: int | None = None, timeout: float = 60) -> RunningLab:
    responder = responder_path()
    if responder is None:
        raise RuntimeError("snmpsim-command-responder not found (pip install snmpsim pysmi)")
    lab = RunningLab(port or _free_port(), root)
    for name, (hosts, v3) in LAB.items():
        data = root / name / "data"
        shutil.copytree(FIXTURES / name, data)
        (data / "public.snmprec").rename(data / f"{COMMUNITY}.snmprec")
        # snmpsim unregisters the default SNMPv3 context and registers it again only for a
        # data file named "self.snmprec" (empty context name), which real agents use.
        shutil.copy(data / f"{COMMUNITY}.snmprec", data / "self.snmprec")
        cmd = [responder, f"--data-dir={data}", f"--cache-dir={root / name / 'cache'}",
               "--logging-method=null"]
        cmd += [f"--agent-udpv4-endpoint={h}:{lab.port}" for h in hosts]
        if v3:
            cmd += [f"--v3-user={V3_USER}", f"--v3-auth-key={V3_AUTH}", "--v3-auth-proto=SHA256",
                    f"--v3-priv-key={V3_PRIV}", "--v3-priv-proto=AES128"]
        lab.procs.append(subprocess.Popen(cmd, stdout=subprocess.DEVNULL,
                                          stderr=subprocess.DEVNULL))
    hosts = [h for spec, _ in LAB.values() for h in spec]
    missing = asyncio.run(_wait_ready(hosts, lab.port, time.monotonic() + timeout))
    if missing:
        lab.stop()
        raise RuntimeError(f"snmpsim did not start on {missing}")
    return lab


def write_config(tmp: Path, lab: RunningLab, *, seeds: list[str], extra_devices: str = "",
                 tolerate_dead: bool = True, files: str = "[devices]") -> Path:
    secrets = tmp / "secrets"
    secrets.mkdir(parents=True, exist_ok=True)
    for name, value in (("v3_auth", V3_AUTH), ("v3_priv", V3_PRIV), ("community", COMMUNITY)):
        path = secrets / name
        path.write_text(value + "\n")
        path.chmod(0o600)
    seed_lines = "\n".join(f"    - '{s}'" for s in seeds)
    cfg = tmp / "snowth_my_net.yml"
    cfg.write_text(f"""
general:
  state_dir: {tmp / 'state'}
  output_dir: {tmp / 'out'}
  secrets_dir: {secrets}
  snmp:
    timeout: 1
    retries: 0
    probe_timeout: 0.5
    table_timeout: 20
    device_timeout: 60
credentials:
  - name: v3-main
    version: 3
    username: {V3_USER}
    auth_protocol: sha256
    auth_key_file: v3_auth
    priv_protocol: aes128
    priv_key_file: v3_priv
  - name: v2c-lab
    version: 2c
    community_file: community
discovery:
  seeds:
{seed_lines}
  allowed: [127.0.0.0/8]
devices:
  - address: {DEAD}
    tolerate_failure: {'true' if tolerate_dead else 'false'}
{extra_devices}
export:
  files: {files}
""")
    return cfg


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the snmpsim lab until Ctrl-C.")
    parser.add_argument("--dir", help="working directory (default: a new temporary one)")
    parser.add_argument("--port", type=int, help="UDP port (default: a free one)")
    args = parser.parse_args()
    root = Path(args.dir or tempfile.mkdtemp(prefix="snowth-lab-"))
    lab = start_lab(root / "agents", args.port)
    cfg = write_config(root, lab, seeds=lab.all_seeds())
    print(f"lab running on UDP port {lab.port}; configuration: {cfg}", flush=True)
    print(f"try: snowth_my_net --config {cfg} check", flush=True)

    def _terminate(signum, frame):
        raise KeyboardInterrupt

    # Background jobs of non-interactive shells ignore SIGINT: accept SIGTERM too, so the
    # simulators are always stopped with the lab.
    signal.signal(signal.SIGTERM, _terminate)
    signal.signal(signal.SIGINT, signal.default_int_handler)
    try:
        signal.pause()
    except KeyboardInterrupt:
        pass
    finally:
        lab.stop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
