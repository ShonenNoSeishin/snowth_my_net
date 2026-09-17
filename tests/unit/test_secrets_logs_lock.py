import os

import pytest

from snowth_my_net.config.secrets import Secret, SecretError, read_secret_file, resolve_secret
from snowth_my_net.export.atomic import atomic_write
from snowth_my_net.lock import LockBusy, StateLock
from snowth_my_net.logs import REDACTOR, get_logger, setup_logging


def test_secret_file_strips_bom_and_line_endings(tmp_path):
    f = tmp_path / "token"
    f.write_bytes(b"\xef\xbb\xbfs3cr3t-token\r\n")
    f.chmod(0o600)
    value, warnings = read_secret_file(f)
    assert value == "s3cr3t-token"
    assert warnings == []


def test_group_readable_secret_file_warns(tmp_path):
    f = tmp_path / "token"
    f.write_text("value")
    f.chmod(0o644)
    _, warnings = read_secret_file(f)
    assert warnings and "mode 0644" in warnings[0]


def test_empty_or_missing_secrets_fail(tmp_path, monkeypatch):
    (tmp_path / "empty").write_text(" \n")
    with pytest.raises(SecretError, match="is empty"):
        read_secret_file(tmp_path / "empty")
    with pytest.raises(SecretError, match="cannot read"):
        read_secret_file(tmp_path / "absent")
    monkeypatch.delenv("ABSENT_VAR", raising=False)
    with pytest.raises(SecretError, match="not set"):
        resolve_secret(None, "ABSENT_VAR", tmp_path, "x")
    with pytest.raises(SecretError, match="not both"):
        resolve_secret("a", "B", tmp_path, "x")


def test_secret_value_never_appears_in_repr():
    s = Secret("very-secret-value", "test")
    assert "very-secret-value" not in repr(s)
    assert "very-secret-value" not in f"{s}"
    with pytest.raises(TypeError):
        import pickle

        pickle.dumps(s)


def test_logs_mask_registered_secrets(capsys):
    setup_logging("debug")
    secret = Secret("hunter2-community", "test")
    log = get_logger("test")
    log.warning("polling with community %s@10", secret.reveal())
    try:
        raise RuntimeError(f"failure using {secret.reveal()}")
    except RuntimeError:
        log.exception("boom")
    err = capsys.readouterr().err
    assert "hunter2-community" not in err
    assert "***@10" in err
    assert "failure using ***" in err
    assert REDACTOR.redact("x hunter2-community y") == "x *** y"


def test_lock_is_exclusive_and_reports_its_holder(tmp_path):
    path = tmp_path / "state.lock"
    first = StateLock(path, "collect")
    first.acquire(0)
    second = StateLock(path, "export")
    with pytest.raises(LockBusy) as exc:
        second.acquire(0.3)
    assert exc.value.holder["command"] == "collect"
    assert exc.value.holder["pid"] == os.getpid()
    assert "collect" in str(exc.value)
    first.release()
    second.acquire(0)
    second.release()


def test_atomic_write_keeps_the_old_file_on_failure(tmp_path, monkeypatch):
    target = tmp_path / "out" / "devices.csv"
    atomic_write(target, b"old")
    assert target.read_bytes() == b"old"
    assert oct(target.stat().st_mode & 0o777) == "0o644"

    def broken_replace(src, dst):
        raise OSError("disk full")

    monkeypatch.setattr(os, "replace", broken_replace)
    with pytest.raises(OSError):
        atomic_write(target, b"new")
    assert target.read_bytes() == b"old"
    assert sorted(p.name for p in target.parent.iterdir()) == ["devices.csv"]
