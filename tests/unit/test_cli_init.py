from snowth_my_net.cli import main
from snowth_my_net.config.loader import parse_config_text


def test_init_writes_a_valid_commented_config(tmp_path, capsys):
    dest = tmp_path / "snowth_my_net.yml"
    assert main(["init", "--output", str(dest)]) == 0
    text = dest.read_text()
    assert text.startswith("# snowth_my_net configuration")
    assert parse_config_text(text).credentials[0].name == "v3-main"
    assert oct(dest.stat().st_mode & 0o777) == "0o640"
    assert "check" in capsys.readouterr().out


def test_init_never_overwrites_without_force(tmp_path, capsys):
    dest = tmp_path / "snowth_my_net.yml"
    dest.write_text("keep me")
    assert main(["init", "--output", str(dest)]) == 2
    assert dest.read_text() == "keep me"
    assert main(["init", "--output", str(dest), "--force"]) == 0
    assert dest.read_text() != "keep me"


def test_no_command_is_a_usage_error(capsys):
    assert main([]) == 2


def test_missing_config_is_a_config_error(tmp_path, capsys):
    assert main(["--config", str(tmp_path / "absent.yml"), "collect"]) == 2
