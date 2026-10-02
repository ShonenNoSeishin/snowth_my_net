"""``.env.example`` documents every variable the Compose stack and the image use."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
COMPOSE = (ROOT / "compose.yml").read_text(encoding="utf-8")
DOCKERFILE = (ROOT / "Dockerfile").read_text(encoding="utf-8")
EXAMPLE = (ROOT / ".env.example").read_text(encoding="utf-8")

USED = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)(?::-([^}]*))?\}")
DOCUMENTED = re.compile(r"^#?\s*([A-Z][A-Z0-9_]*)=(.*)$", re.MULTILINE)


def documented() -> dict[str, str]:
    return {name: value.strip() for name, value in DOCUMENTED.findall(EXAMPLE)}


def test_every_compose_variable_is_documented_with_its_default():
    used = dict(USED.findall(COMPOSE))
    assert set(used) == {"SNOWTH_VERSION", "SNOWTH_UID", "SNOWTH_GID", "TZ",
                         "SNOWTH_COLLECT_ON_START", "SNOWTH_HTTP_PORT", "SNOWTH_HTTPS_PORT",
                         "SNOWTH_TLS_HOSTS"}
    known = documented()
    assert [name for name in used if name not in known] == []
    mismatched = {name: (default, known[name]) for name, default in used.items()
                  if default and known[name] != default}
    assert mismatched == {}


def test_every_variable_is_commented_out():
    """Copying the file must change nothing until a line is uncommented."""
    active = [line for line in EXAMPLE.splitlines()
              if line.strip() and not line.lstrip().startswith("#")]
    assert active == []


def test_the_paths_baked_into_the_image_are_listed():
    image = dict(re.findall(r"(SNOWTH_[A-Z_]+)=(\S+)", DOCKERFILE))
    assert set(image) == {"SNOWTH_CONFIG", "SNOWTH_STATE_DIR", "SNOWTH_OUTPUT_DIR",
                          "SNOWTH_SECRETS_DIR", "SNOWTH_EXTENSIONS_DIR"}
    known = documented()
    assert [f"{name}={value}" for name, value in image.items()
            if known.get(name) != value] == []


def test_compose_needs_no_editing_to_add_a_secret():
    """A tracked file that has to be edited per site conflicts on every 'git pull'."""
    assert "\nsecrets:" not in COMPOSE                  # no per-site secret declarations
    assert COMPOSE.count("./secrets:/run/secrets:ro") == 2   # both services, whole directory
    assert (ROOT / ".gitignore").read_text().count("compose.override.yml") == 1


def test_the_interface_is_only_reachable_through_the_tls_front():
    """Nothing publishes the interface in clear: the proxy is the way in."""
    import yaml

    services = yaml.safe_load(COMPOSE)["services"]
    assert services["nginx"]["build"]["context"] == "./nginx"
    assert "ports" not in services["web"]                    # no clear-text port on the host
    assert len(services["nginx"]["ports"]) == 2              # 80 (redirect) and 443
    assert "--trusted-proxy" in services["web"]["command"]   # the reader's own address is kept


def test_the_front_resolves_the_interface_again_instead_of_pinning_an_address():
    """A name resolved once at start-up answers 502 to everything after the app is recreated."""
    template = (ROOT / "nginx" / "nginx.conf.template").read_text(encoding="utf-8")
    assert "resolver 127.0.0.11" in template          # Docker's own DNS
    assert "proxy_pass http://$interface;" in template   # a variable: resolved per request
    assert "proxy_pass http://web:8080" not in template  # the pinned form


def test_the_interface_can_write_what_its_buttons_produce():
    """The Export and Push buttons run in the web container: a read-only /output broke them."""
    import yaml

    services = yaml.safe_load(COMPOSE)["services"]
    for name in ("snowth", "web"):
        mounts = {entry.split(":")[1]: entry for entry in services[name]["volumes"]}
        assert not mounts["/output"].endswith(":ro"), name
        assert not mounts["/var/lib/snowth_my_net"].endswith(":ro"), name
    assert services["web"]["volumes"][0].endswith(":ro")        # the configuration stays read-only
