"""Find, parse, validate and resolve the configuration.

Path precedence for ``state_dir``, ``output_dir`` and ``secrets_dir`` is: command-line option,
then environment variable (``SNOWTH_STATE_DIR``, ``SNOWTH_OUTPUT_DIR``, ``SNOWTH_SECRETS_DIR``),
then the YAML value, then the built-in default. This lets one YAML file serve both the host
installation and the container, where Compose sets the variables. Relative paths written in the
YAML are relative to the directory of the configuration file.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from snowth_my_net.config.schema import Config, CredentialCfg
from snowth_my_net.config.secrets import Secret, SecretError, resolve_secret
from snowth_my_net.config.validate import ConfigError, build

DEFAULT_CONFIG_CANDIDATES = (Path("snowth_my_net.yml"), Path("/etc/snowth_my_net/config.yml"))
DEFAULT_STATE_DIR = Path("/var/lib/snowth_my_net")
DEFAULT_SECRETS_DIR = Path("/etc/snowth_my_net/secrets")


@dataclass(frozen=True)
class Paths:
    config_file: Path
    state_dir: Path
    output_dir: Path
    secrets_dir: Path
    extensions_dir: Path | None = None

    @property
    def state_file(self) -> Path:
        return self.state_dir / "state.sqlite"

    @property
    def lock_file(self) -> Path:
        return self.state_dir / "state.lock"

    @property
    def oui_file(self) -> Path:
        return self.state_dir / "oui.tsv.gz"


@dataclass
class ResolvedCredential:
    cfg: CredentialCfg
    community: Secret | None = None
    auth_key: Secret | None = None
    priv_key: Secret | None = None

    @property
    def name(self) -> str:
        return self.cfg.name


@dataclass
class LoadedConfig:
    cfg: Config
    paths: Paths
    warnings: list[str] = field(default_factory=list)
    collectors: list = field(default_factory=list)       # LoadedCollector from extension files
    reports: list = field(default_factory=list)          # LoadedReport from extension files

    def resolve_credentials(self) -> tuple[list[ResolvedCredential], list[str]]:
        """Read every SNMP secret. Raises :class:`ConfigError` listing all unreadable ones."""
        resolved, errors, warnings = [], [], []
        base = self.paths.secrets_dir
        for cred in self.cfg.credentials:
            item = ResolvedCredential(cred)
            try:
                if cred.version == "2c":
                    item.community, w = resolve_secret(
                        cred.community_file, cred.community_env, base,
                        f"credential '{cred.name}' community")
                    warnings += w
                else:
                    if cred.auth_protocol:
                        item.auth_key, w = resolve_secret(
                            cred.auth_key_file, cred.auth_key_env, base,
                            f"credential '{cred.name}' auth key")
                        warnings += w
                    if cred.priv_protocol:
                        item.priv_key, w = resolve_secret(
                            cred.priv_key_file, cred.priv_key_env, base,
                            f"credential '{cred.name}' privacy key")
                        warnings += w
            except SecretError as exc:
                errors.append(str(exc))
                continue
            for secret in (item.auth_key, item.priv_key):
                if secret is not None and len(secret.reveal()) < 8:
                    errors.append(
                        f"credential '{cred.name}': SNMPv3 keys must be at least 8 characters "
                        f"({secret.source})")
            resolved.append(item)
        if errors:
            raise ConfigError(errors)
        return resolved, warnings


def find_config(cli_path: str | None) -> Path:
    if cli_path:
        return Path(cli_path)
    env = os.environ.get("SNOWTH_CONFIG")
    if env:
        return Path(env)
    for candidate in DEFAULT_CONFIG_CANDIDATES:
        if candidate.exists():
            return candidate
    tried = ", ".join(str(c) for c in DEFAULT_CONFIG_CANDIDATES)
    raise ConfigError(
        [f"no configuration file found (tried --config, $SNOWTH_CONFIG, {tried}); "
         "create one with 'snowth_my_net init'"])


def parse_config_text(text: str, origin: str = "<config>") -> Config:
    try:
        data = yaml.safe_load(text.removeprefix("﻿"))
    except yaml.YAMLError as exc:
        raise ConfigError([f"{origin}: invalid YAML: {exc}"]) from None
    if data is None:
        data = {}
    if not isinstance(data, dict):
        raise ConfigError([f"{origin}: the top level must be a mapping"])
    return build(Config, data)


def load_config(
    path: Path, *, state_dir: str | None = None, output_dir: str | None = None
) -> LoadedConfig:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ConfigError([f"cannot read configuration {path}: {exc.strerror}"]) from None
    cfg = parse_config_text(text, str(path))
    base = path.resolve().parent

    def pick(cli: str | None, env_name: str, yaml_value: str | None, default: Path) -> Path:
        for value, relative_to_config in ((cli, False), (os.environ.get(env_name), False),
                                          (yaml_value, True)):
            if value:
                p = Path(value).expanduser()
                if not p.is_absolute():
                    p = (base / p) if relative_to_config else p.resolve()
                return p
        return default

    g = cfg.general
    state = pick(state_dir, "SNOWTH_STATE_DIR", g.state_dir, DEFAULT_STATE_DIR)
    paths = Paths(
        config_file=path,
        state_dir=state,
        output_dir=pick(output_dir, "SNOWTH_OUTPUT_DIR", g.output_dir, state / "output"),
        secrets_dir=pick(None, "SNOWTH_SECRETS_DIR", g.secrets_dir, DEFAULT_SECRETS_DIR),
        extensions_dir=pick(None, "SNOWTH_EXTENSIONS_DIR", g.extensions_dir, base / "extensions"),
    )
    from snowth_my_net.config.extensions import load_extensions

    collectors, reports = load_extensions(paths.extensions_dir)
    return LoadedConfig(cfg=cfg, paths=paths, collectors=collectors, reports=reports)
