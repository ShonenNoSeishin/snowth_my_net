# Deployment

Two first-class ways, sharing the same configuration file: a host installation scheduled by cron
or systemd, and Docker Compose. snowth_my_net never runs as a daemon itself: every run is one
process that exits. Its own lock (`state.lock`) guarantees that two runs never overlap, whatever
the scheduler.

Before anything: `snowth_my_net check` diagnoses credentials and MIB support device by device.

## 1. Host: pipx + cron or systemd

```bash
sudo useradd --system --home /var/lib/snowth_my_net --shell /usr/sbin/nologin snowth
sudo install -d -o snowth -g snowth -m 0750 /var/lib/snowth_my_net
sudo install -d -o root -g snowth -m 0750 /etc/snowth_my_net /etc/snowth_my_net/secrets

# From the git repository (PyPI later):
sudo PIPX_HOME=/opt/pipx PIPX_BIN_DIR=/usr/local/bin pipx install git+ssh://git@github.com/ShonenNoSeishin/snowth_my_net.git
#   or: pipx install ./snowth_my_net   (a local clone)

sudo -u snowth snowth_my_net init --output /etc/snowth_my_net/config.yml   # then edit it
printf '%s' 'the-v3-auth-key' | sudo install -o snowth -g snowth -m 0600 /dev/stdin /etc/snowth_my_net/secrets/snmp_v3_auth
printf '%s' 'the-v3-priv-key' | sudo install -o snowth -g snowth -m 0600 /dev/stdin /etc/snowth_my_net/secrets/snmp_v3_priv

sudo -u snowth snowth_my_net check
sudo -u snowth snowth_my_net collect
sudo -u snowth snowth_my_net tui        # or just: snowth_my_net
```

### cron

The schedule lives in `schedule:`; generate the lines (absolute paths, since cron's `PATH` rarely
contains pipx's):

```bash
sudo -u snowth snowth_my_net --config /etc/snowth_my_net/config.yml cron print --format cron.d --user snowth \
  | sudo tee /etc/cron.d/snowth_my_net
```

```
# poll the devices (ARP entries expire quickly)
*/10 * * * * snowth /usr/local/bin/snowth_my_net --config /etc/snowth_my_net/config.yml -q collect
# export the files and push them
0 11,18 * * * snowth /usr/local/bin/snowth_my_net --config /etc/snowth_my_net/config.yml -q run --no-collect
```

Reports with a `schedule:` add one `report run <name>` line each (see
[extensions.md](extensions.md#schedule-and-push)).

Regenerate after changing `schedule:` or a report schedule. `CRON_TZ=` is written when `schedule.timezone` is set
(cronie supports it; with other crons, set the host time zone).

### systemd timers

```ini
# /etc/systemd/system/snowth-collect.service
[Unit]
Description=snowth_my_net collect
Wants=network-online.target
After=network-online.target

[Service]
Type=oneshot
User=snowth
Group=snowth
ExecStart=/usr/local/bin/snowth_my_net --config /etc/snowth_my_net/config.yml -q collect
TimeoutStartSec=55min
NoNewPrivileges=yes
ProtectSystem=strict
ProtectHome=yes
PrivateTmp=yes
ReadWritePaths=/var/lib/snowth_my_net
CapabilityBoundingSet=
RestrictAddressFamilies=AF_INET AF_INET6 AF_UNIX
SystemCallArchitectures=native
```

```ini
# /etc/systemd/system/snowth-collect.timer      (= "*/10 * * * *")
[Timer]
OnCalendar=*:0/10
Persistent=true

[Install]
WantedBy=timers.target
```

The same pair for export and push is shown below (append a time zone such as `Europe/Brussels`
to `OnCalendar` if needed). Add the output directory to `ReadWritePaths` when it is not under the
state directory.

```ini
# /etc/systemd/system/snowth-export.service
[Unit]
Description=snowth_my_net export and push
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
User=snowth
Group=snowth
ExecStart=/usr/local/bin/snowth_my_net --config /etc/snowth_my_net/config.yml -q run --no-collect
# same hardening lines as snowth-collect.service
```

```ini
# /etc/systemd/system/snowth-export.timer       (= "0 11,18 * * *")
[Timer]
OnCalendar=*-*-* 11,18:00:00
Persistent=true

[Install]
WantedBy=timers.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now snowth-collect.timer snowth-export.timer
```

Monitoring: `snowth_my_net health` exits 1 when the last successful collect is older than twice
the longest gap of `schedule.collect` (or `schedule.health_max_age`).

## 2. Docker Compose

Three services: `snowth` runs [supercronic](https://github.com/aptible/supercronic)
(cron-compatible, logs on stdout, no root), `web` serves the read-only interface, and `nginx`
terminates TLS in front of it — the interface itself is published nowhere. At start-up it generates the crontab from `schedule:` — no crontab to
maintain on the host — and runs one collect.

```bash
git clone git@github.com:ShonenNoSeishin/snowth_my_net.git && cd snowth_my_net
cp .env.example .env                          # uncomment SNOWTH_UID/SNOWTH_GID = "id -u"/"id -g"
mkdir -p config/extensions data output secrets
docker compose build
# commented example configuration, written into ./config (then edit it)
docker run --rm -u "$(id -u):$(id -g)" -v "$PWD/config:/work" snowth_my_net:latest \
  init --output /work/snowth_my_net.yml
printf '%s' 'the-v3-auth-key' > secrets/snmp_v3_auth
printf '%s' 'the-v3-priv-key' > secrets/snmp_v3_priv
printf '%s' 'the-push-token'  > secrets/cmdb_token
chmod 600 secrets/*
docker compose run --rm snowth check
docker compose up -d                          # https://<host>:8443 for the web interface
```

In `config/snowth_my_net.yml`, secret files are referenced by name (`auth_key_file: snmp_v3_auth`):
the container sets `SNOWTH_SECRETS_DIR=/run/secrets`, where Compose mounts them.

### Image

* Multi-stage build on `python:3.13-slim`; no build tool, no pip in the final image; about 200 MB
  uncompressed (the Python base is 126 MB). Distroless was not chosen because supercronic runs
  jobs through `/bin/sh -c`.
* supercronic is downloaded at build time and checked against its published SHA-256.
* Runs as a non-root user (`SNOWTH_UID:SNOWTH_GID`, default 10001).

### Volumes

| Host | Container | |
|---|---|---|
| `./config/snowth_my_net.yml` | `/etc/snowth_my_net/config.yml` | read-only |
| `./config/extensions/` | `/etc/snowth_my_net/extensions/` | read-only, custom collectors and reports |
| `./data/` | `/var/lib/snowth_my_net` | state, lock, vendor database |
| `./secrets/` | `/run/secrets/` | read-only, one file per secret |
| `./output/` | `/output` | CSV, JSON, maps, readable on the host |

### Secrets

The whole `./secrets/` directory is mounted read-only on `/run/secrets/`, the directory the image
reads (`SNOWTH_SECRETS_DIR`). A file dropped there is reached by its name — `community_file:
community_office` — and **`compose.yml` never changes**, which is the point: a file that is never
edited never conflicts with `git pull`.

A bind mount keeps the owner and mode of the host (`uid`/`gid`/`mode` of Compose secrets are
ignored outside Swarm), which is why the container runs with your UID/GID: the files can stay
`chmod 600`.

### Nothing to edit in `compose.yml`

What differs from one site to another lives outside it: `.env` (ports, user, time zone),
`config/snowth_my_net.yml` (devices, credentials, schedule) and `secrets/` (their values). All
three are ignored by git. For anything else — another volume, a second interface, a network —
write a `compose.override.yml` next to it: Compose merges it automatically and git ignores it
too.

### Network

The default bridge network is enough: SNMP (UDP/161) and HTTPS are outgoing. **SNMP leaves with
the host's IP address** (NAT): that address must be allowed in the SNMP ACLs of the devices.
`network_mode: host` is not needed, and no port is exposed. For the internal DNS, set
`dns.resolvers` (the container otherwise uses Docker's resolver).

### Hardening

`read_only: true`, `tmpfs: /tmp`, `cap_drop: [ALL]`, `no-new-privileges`, `init: true`,
`restart: unless-stopped`, JSON log rotation (10 MB × 3), health check `snowth_my_net health`
(start period 30 minutes).

### Operations

```bash
docker compose run --rm snowth check
docker compose run --rm snowth explain 00:11:22:33:44:55
docker compose run --rm snowth run --wait
docker compose run --rm snowth tui
docker compose logs -f snowth
docker compose ps                  # health status
```

### Tests

```bash
docker compose --profile test run --rm tests
```

Starts two SNMP simulators and a fake HTTPS import server as containers, then runs the whole test
suite plus an end-to-end test through them (collect, export, push with a self-signed CA).
