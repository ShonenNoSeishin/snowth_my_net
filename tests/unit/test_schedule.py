from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from snowth_my_net.config.loader import LoadedConfig, Paths, parse_config_text
from snowth_my_net.config.validate import ConfigError
from snowth_my_net.schedule.cron import CronError, longest_gap, parse_cron
from snowth_my_net.schedule.planning import max_collect_age, render_crontab

UTC = ZoneInfo("UTC")


def at(text):
    return datetime.fromisoformat(text).replace(tzinfo=UTC)


@pytest.mark.parametrize("expr, moment, expected", [
    ("*/10 * * * *", "2026-09-17 11:20", True),
    ("*/10 * * * *", "2026-09-17 11:21", False),
    ("0 11,18 * * *", "2026-09-17 18:00", True),
    ("0 7 * * mon", "2026-09-21 07:00", True),        # a Monday
    ("0 7 * * 7", "2026-09-20 07:00", True),          # 7 = Sunday
    ("0 0 1 * mon", "2026-09-21 00:00", True),        # Vixie OR: a Monday, not the 1st
    ("0 0 1 * mon", "2026-10-01 00:00", True),        # the 1st, a Thursday
    ("0 0 1 * mon", "2026-10-02 00:00", False),
    ("15 2-4/2 * jan-mar *", "2026-02-10 04:15", True),
    ("@hourly", "2026-09-17 11:00", True),
])
def test_matching(expr, moment, expected):
    assert parse_cron(expr).matches(at(moment)) is expected


@pytest.mark.parametrize("expr, message", [
    ("* * * *", "expected 5 fields"), ("61 * * * *", "outside 0-59"), ("*/0 * * * *", "step"),
    ("5-2 * * * *", "reversed"), ("@reboot", "not a schedule"), ("* * * foo *", "not a number"),
])
def test_invalid_expressions(expr, message):
    with pytest.raises(CronError, match=message):
        parse_cron(expr)


def test_longest_gap():
    now = at("2026-09-17 00:00")
    assert longest_gap(parse_cron("*/10 * * * *"), now=now) == timedelta(minutes=10)
    assert longest_gap(parse_cron("0 11,18 * * *"), now=now) == timedelta(hours=17)
    assert longest_gap(parse_cron("0 7 * * 1"), now=now) == timedelta(days=7)


def cfg(tmp_path, schedule, push=""):
    config = parse_config_text(f"schedule:\n{schedule}\n{push}")
    return LoadedConfig(config, Paths(tmp_path / "config.yml", tmp_path, tmp_path, tmp_path))


def test_crontab_lines(tmp_path):
    loaded = cfg(tmp_path, "  timezone: Europe/Brussels",
                 "push:\n  targets: [{name: t, url: 'https://x/import'}]")
    text = render_crontab(loaded, binary="/opt/pipx/bin/snowth_my_net")
    config = str((tmp_path / "config.yml").resolve())
    assert "CRON_TZ=Europe/Brussels" in text
    assert f"*/10 * * * * /opt/pipx/bin/snowth_my_net --config {config} -q collect" in text
    assert f"0 11,18 * * * /opt/pipx/bin/snowth_my_net --config {config} -q run --no-collect" \
        in text
    crond = render_crontab(loaded, "cron.d", user="snowth", binary="/usr/bin/snowth_my_net")
    assert "*/10 * * * * snowth /usr/bin/snowth_my_net" in crond and "SHELL=/bin/sh" in crond
    no_push = render_crontab(cfg(tmp_path, "  collect: null"), binary="s")
    assert "collect\n" not in no_push and "run --no-collect --no-push" in no_push


def test_health_max_age(tmp_path):
    assert max_collect_age(cfg(tmp_path, "  collect: '*/15 * * * *'"))[0] == 1800
    assert max_collect_age(cfg(tmp_path, "  health_max_age: 45m"))[0] == 2700


def test_invalid_schedule_is_a_config_error():
    with pytest.raises(ConfigError, match=r"schedule\.collect"):
        parse_config_text("schedule: {collect: '*/10 * *'}")
