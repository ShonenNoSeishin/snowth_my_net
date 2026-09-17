"""Run one simulated device of the lab in a container (compose test profile).

    python -m tests.support.sim_container sw-access

Listens on 0.0.0.0:1161 (unprivileged port), SNMPv2c community and SNMPv3 user of the lab.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from tests.support.lab import COMMUNITY, FIXTURES, LAB, V3_AUTH, V3_PRIV, V3_USER, responder_path

PORT = 1161


def main() -> int:
    name = sys.argv[1]
    if name not in LAB:
        print(f"unknown agent {name!r}: {', '.join(LAB)}", file=sys.stderr)
        return 2
    root = Path(tempfile.mkdtemp(prefix=f"sim-{name}-"))
    data = root / "data"
    shutil.copytree(FIXTURES / name, data)
    (data / "public.snmprec").rename(data / f"{COMMUNITY}.snmprec")
    for instance in sorted(data.glob("public@*.snmprec")):
        vlan = instance.stem.split("@", 1)[1]
        shutil.copy(instance, data / f"vlan-{vlan}.snmprec")
        instance.rename(data / f"{COMMUNITY}@{vlan}.snmprec")
    shutil.copy(data / f"{COMMUNITY}.snmprec", data / "self.snmprec")
    cmd = [responder_path() or "snmpsim-command-responder", f"--data-dir={data}",
           f"--cache-dir={root / 'cache'}", f"--agent-udpv4-endpoint=0.0.0.0:{PORT}",
           f"--v3-user={V3_USER}", f"--v3-auth-key={V3_AUTH}", "--v3-auth-proto=SHA256",
           f"--v3-priv-key={V3_PRIV}", "--v3-priv-proto=AES128", "--logging-method=stderr",
           "--log-level=error"]
    print(f"simulating {name} on UDP {PORT}", file=sys.stderr, flush=True)
    return subprocess.call(cmd)


if __name__ == "__main__":
    sys.exit(main())
