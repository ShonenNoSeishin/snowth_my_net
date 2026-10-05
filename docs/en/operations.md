# Running it

How the Docker stack is laid out, which commands to type every day, how to make a change take
effect, how to update, and how to back up. The installation itself is in
[getting started](getting-started.md), the networking and hardening in
[deployment](deployment.md).

## What is where

```text
snowth_my_net/
├── .env                    ports, user, time zone, TLS names     yours, ignored by git
├── compose.yml             the stack — never edited, so git pull never conflicts
├── compose.override.yml    anything else you need to change      yours, ignored by git
├── config/
│   ├── snowth_my_net.yml   your configuration                    yours, ignored by git
│   └── extensions/         custom collectors and reports         yours, ignored by git
├── secrets/                one file per secret, chmod 600        yours, ignored by git
├── data/                   the state, see below                  ignored by git
└── output/                 the exported files                    ignored by git
```

| File in `data/` | What it holds | If it is deleted |
|---|---|---|
| `state.sqlite` | the inventory — devices, MAC and ARP observations, links, runs — **and what you set by hand in it**: per-device settings (`device set`), collectors and reports built in the terminal interface | the next collect rebuilds the inventory, not the hand-made settings |
| `node_names.json` | the names and descriptions you gave to MAC addresses | the names are gone |
| `web_accounts.json` | the password hashes of the web accounts | the passwords are gone; new first-login passwords are invented and written to the log |
| `oui.tsv.gz` | the vendor database fetched by `oui-update` | the copy built into the tool is used again |
| `state.lock` | the lock that lets only one writer at a time in | nothing |

## The services

| Service | What it does | Reached at |
|---|---|---|
| `snowth` | the scheduler: collects every ten minutes, exports twice a day | nothing is published |
| `web` | the web interface | only through `nginx` |
| `nginx` | ends TLS in front of the interface | `https://<host>:8443`, and `http://<host>:8080` which redirects there |

`sim-access`, `sim-cisco`, `fakepush` and `tests` belong to the test profile and never start on
their own.

## Everyday commands

```bash
docker compose ps                                  # what runs, and whether it is healthy
docker compose logs -f snowth                      # follow the scheduler
docker compose logs --tail=50 web                  # the interface; a first-login password is here
docker compose exec web snowth_my_net <command>    # any command, see commands.md
docker compose exec -it web snowth_my_net tui      # the terminal interface needs -it
docker compose restart web                         # after changing the configuration
docker compose up -d --build                       # after a git pull
docker compose down                                # remove the containers; data/ stays
```

`snowth` and `web` run the same image over the same configuration, state and output: type
commands in either. A command that writes takes the state lock, so a manual `collect` waits up to
a minute when a scheduled one is running (`general.lock_wait`), and other commands up to fifteen.

## Making a change take effect

A scheduled job is a new process every time, so it reads the configuration afresh. The web server
reads it once, when it starts, and the scheduler builds its crontab once, when its container
starts. That is the whole rule; here it is by what you changed.

| What you changed | What to do | Why |
|---|---|---|
| a key of `config/snowth_my_net.yml` | nothing for the scheduler, `docker compose restart web` for the interface | every job reads the file; the web server reads it at start |
| `schedule:` | `docker compose restart snowth` | the crontab is generated when the container starts |
| a file of `secrets/` | nothing for the scheduler; restart `web` if it is a web password file | jobs read secrets when they run |
| a file of `config/extensions/` | nothing for the scheduler, `docker compose restart web` | same as the configuration |
| a name or a description, from the table or `node name` | nothing | read again on every request |
| a web password, from the page or `web passwd` | nothing | read again on every sign-in |
| `.env` | `docker compose up -d` | Compose recreates the services whose settings changed |
| `SNOWTH_TLS_HOSTS`, after the first start | `docker compose down`, `docker volume rm snowth_my_net_certs_web`, `docker compose up -d` | the certificate is made once and kept |
| `compose.override.yml` | `docker compose up -d` | same as `.env` |
| the tool itself, after a `git pull` | `docker compose up -d --build` | the image is rebuilt |

Check a configuration before restarting anything. `cron print` loads the whole file and refuses
a typo with a suggestion; `check` goes further and polls every device:

```bash
docker compose exec snowth snowth_my_net cron print
docker compose exec snowth snowth_my_net check
```

## Updating

```bash
cd ~/snowth_my_net
git pull
docker compose up -d --build
docker compose exec web snowth_my_net collect      # the first write upgrades the state if needed
```

* Nothing of yours is overwritten: `.env`, `config/`, `secrets/`, `data/`, `output/` and
  `compose.override.yml` are not tracked by git.
* A new version may upgrade the schema of the state the first time something writes to it. Until
  then the web interface answers *503*: it refuses to read a state older than itself. The next
  scheduled collect does it, or run `collect` yourself.
* **The upgrade goes one way.** An older version refuses a newer state. To go back, restore a
  backup of `data/` taken before the update.
* If `git pull` complains about local changes to `compose.yml`, that file was edited and must not
  be: move the change to `compose.override.yml` and run `git checkout -- compose.yml`.

## Backing up and restoring

| Keep | Why |
|---|---|
| `config/` and `secrets/` | your configuration and the values it points at: the only part that cannot be rebuilt |
| `data/node_names.json` | the names and descriptions written by hand |
| `data/web_accounts.json` | the web passwords |
| `data/state.sqlite` | the inventory and its 30 days of history, plus the settings made by hand |
| `.env`, `compose.override.yml` | your Compose settings |

The state runs in WAL mode, so a file copied while a collect is writing can be inconsistent. The
`backup()` call of SQLite takes a consistent snapshot while everything keeps running:

```bash
docker compose exec -T snowth python -c "import sqlite3; s = sqlite3.connect('/var/lib/snowth_my_net/state.sqlite'); d = sqlite3.connect('/var/lib/snowth_my_net/state.backup.sqlite'); s.backup(d)"
tar czf snowth-backup-$(date +%F).tgz config secrets .env data/node_names.json data/web_accounts.json data/state.backup.sqlite
```

To restore, stop everything, put the files back, and drop the write-ahead files of the state you
are replacing — they belong to the old database and would corrupt the restored one:

```bash
docker compose down
tar xzf snowth-backup-2026-10-05.tgz
mv data/state.backup.sqlite data/state.sqlite
rm -f data/state.sqlite-wal data/state.sqlite-shm
docker compose up -d
```

## Starting over

| I want to | Command | What it loses |
|---|---|---|
| forget every MAC and ARP observation and keep the rest | `node reset --yes` | the 30 days of memory; devices, links, names and settings stay |
| ask the DNS again | `dns flush` | the cached names; `--misses-only` keeps the ones found |
| begin with an empty inventory | stop, delete `data/state.sqlite*`, start | devices, observations, runs **and the settings made by hand** — export them first with `device export-settings`, `custom export` and `report export` |
| forget every web password | delete `data/web_accounts.json`, `docker compose restart web` | the passwords; new ones are invented and logged |

## Without Docker

With pipx and cron or systemd, every command here is the same without the
`docker compose exec web` in front, and the files live where `general.state_dir`,
`general.output_dir` and `general.secrets_dir` say. See [deployment](deployment.md).
