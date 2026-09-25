"""Static guarantees: no SNMP write path and no shell anywhere in the source tree."""

import ast
from pathlib import Path

SRC = Path(__file__).resolve().parents[2] / "src" / "snowth_my_net"
SNMP_CLIENT = SRC / "snmp" / "client.py"

FORBIDDEN_NAMES = {
    "set_cmd", "setCmd", "SetRequestPDU", "SetRequest", "SetCommandGenerator", "snmpset",
}
FORBIDDEN_MODULES = {"subprocess", "pty", "pexpect"}
# The two documented exceptions, both argv-only, no shell, with a timeout: hooks run the
# programs the configuration names, and the interface's buttons run this tool's own command.
HOOKS = SRC / "hooks.py"
JOBS = SRC / "web" / "jobs.py"
MAY_SPAWN = (HOOKS, JOBS)


def is_os_process_call(node) -> bool:
    """``os.system``, ``os.popen``, ``os.exec*``, ``os.spawn*``, ``os.fork``…"""
    return (isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name)
            and node.value.id == "os"
            and (node.attr in {"system", "popen", "fork", "forkpty"}
                 or node.attr.startswith(("exec", "spawn", "posix_spawn"))))


def sources():
    files = sorted(SRC.rglob("*.py"))
    assert files, SRC
    for path in files:
        yield path, ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def names_in(tree):
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            yield node.id
        elif isinstance(node, ast.Attribute):
            yield node.attr
        elif isinstance(node, ast.ImportFrom | ast.Import):
            for alias in node.names:
                yield alias.name.rsplit(".", 1)[-1]
                if alias.asname:
                    yield alias.asname


def test_no_snmp_write_and_no_shell_primitives():
    offenders = []
    for path, tree in sources():
        for name in names_in(tree):
            if name in FORBIDDEN_NAMES:
                offenders.append(f"{path.relative_to(SRC)}: {name}")
        for node in ast.walk(tree):
            if isinstance(node, ast.keyword) and node.arg == "shell":
                offenders.append(f"{path.relative_to(SRC)}: shell= keyword")
            if is_os_process_call(node):
                offenders.append(f"{path.relative_to(SRC)}: os.{node.attr}")
    assert offenders == []


def test_no_process_spawning_modules():
    offenders = []
    for path, tree in sources():
        for node in ast.walk(tree):
            modules = []
            if isinstance(node, ast.Import):
                modules = [a.name.split(".")[0] for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                modules = [node.module.split(".")[0]]
            offenders += [f"{path.relative_to(SRC)}: {m}" for m in modules
                          if m in FORBIDDEN_MODULES
                          and not (m == "subprocess" and path in MAY_SPAWN)]
    assert offenders == []


def test_the_buttons_never_use_a_shell():
    """The interface starts this tool, by a list of arguments, with a deadline."""
    tree = ast.parse(JOBS.read_text(encoding="utf-8"))
    calls = [node for node in ast.walk(tree) if isinstance(node, ast.Call)
             and isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Name)
             and node.func.value.id == "subprocess"]
    assert [c.func.attr for c in calls] == ["run"]
    run = calls[0]
    assert isinstance(run.args[0], ast.Name)                   # an argv list, not a string
    keywords = {k.arg for k in run.keywords}
    assert "shell" not in keywords and "executable" not in keywords
    assert "timeout" in keywords                               # it can never hang forever


def test_hooks_never_use_a_shell():
    tree = ast.parse(HOOKS.read_text(encoding="utf-8"))
    calls = [node for node in ast.walk(tree) if isinstance(node, ast.Call)
             and isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Name)
             and node.func.value.id == "subprocess"]
    assert [c.func.attr for c in calls] == ["Popen"]
    popen = calls[0]
    assert isinstance(popen.args[0], ast.Name)                 # an argv list, not a string
    keywords = {k.arg: k.value for k in popen.keywords}
    assert "shell" not in keywords and "executable" not in keywords
    assert isinstance(keywords["env"], ast.Name)               # always an explicit environment


def test_pysnmp_is_only_imported_by_the_client():
    importers = set()
    for path, tree in sources():
        for node in ast.walk(tree):
            if isinstance(node, ast.Import) and any(
                    a.name.startswith("pysnmp") for a in node.names):
                importers.add(path)
            if isinstance(node, ast.ImportFrom) and (node.module or "").startswith("pysnmp"):
                importers.add(path)
    assert importers == {SNMP_CLIENT}
