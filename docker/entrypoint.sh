#!/bin/sh
# snowth_my_net container entrypoint.
#   (no argument) or "scheduler": generate the crontab from schedule: and run supercronic
#   anything else: run "snowth_my_net <arguments>" (check, run --wait, explain <mac>, tui…)
set -eu

if [ "$#" -eq 0 ] || [ "$1" = "scheduler" ]; then
    crontab=/tmp/snowth_my_net.crontab
    if ! snowth_my_net cron print --format supercronic --binary snowth_my_net > "$crontab"; then
        echo "snowth_my_net: the configuration is invalid, see the errors above" >&2
        exit 2
    fi
    echo "snowth_my_net: schedule in use:" >&2
    grep -v '^#' "$crontab" >&2 || true
    if [ "${SNOWTH_COLLECT_ON_START:-true}" = "true" ]; then
        # Detached (double fork): the process is reparented to the init process, which reaps it.
        ( snowth_my_net collect >/dev/null 2>&1 & )
    fi
    exec supercronic -passthrough-logs "$crontab"
fi

exec snowth_my_net "$@"
