# Web interface

A small read-only page over the state: devices, nodes, links, runs, and the exported files.
It is served by Python's own HTTP server — no framework, no database of its own, no build step.

```bash
snowth_my_net web                     # http://127.0.0.1:8080
snowth_my_net web --bind 0.0.0.0 --port 9000
```

With Docker Compose it is the `web` service, published on the loopback of the host:

```bash
docker compose up -d web              # http://127.0.0.1:8080
SNOWTH_WEB_PORT=9000 docker compose up -d web
```

## What it shows

| Page | Content |
|---|---|
| Devices | the inventory, as `devices.csv`: name, IP, vendor, model, OS, type, last collect |
| Nodes | MAC addresses and where they are, as `nodes.csv`; a MAC opens its explanation |
| Links | the physical links found through LLDP/CDP, as `links.csv` |
| Runs | the last 50 runs, their status and how many devices answered |
| Files | the exported files present in the output directory, to download |

A MAC seen in several places takes several lines, each marked with its number of positions; the
IP column shows the elected address and then, in grey, the other addresses known for that MAC. In
Devices, '+n MAC' marks a device known by several addresses.

Each page opens with **How to read this table**, a collapsed panel saying where every column
comes from: which MIB, which rule, and why a cell can be empty. The ☾/☀ button in the header switches between light and dark (the choice is kept by the browser,
otherwise the system one applies), and EN/FR changes the language.

Each table has a filter box (the
`/` key focuses it) and sortable columns; the filter and the sort happen in the browser, on the
rows already sent. The line under the title says when the
last collect ran and how it went. Clicking a MAC shows the same explanation as
`snowth_my_net explain`, in the interface's language.

## What it cannot do

**It is read-only by design.** Only `GET` is answered, the state is opened in read-only mode,
and no page offers an action: no collect, no export, no setting. That is deliberate — the state
lock, the SNMP credentials and every write stay in the CLI and in the terminal interface
(`snowth_my_net tui`), which is also where you set a device type by hand or build a report.

## Login

Without accounts there is no login, and the interface only listens on the loopback. Declaring a
name is all it takes — the password is not your business to produce:

```yaml
web:
  auth:
    session_hours: 12
    users:
      - name: alice
```

At startup the interface sees an account without a password, invents one and prints it:

```
WARNING web user 'alice' has no password yet - sign in once with: k7m3-qp9x-4tvr
        (the interface then asks you to choose your own)
```

Sign in with it once; the interface then asks for a password of your own before showing
anything. Whoever reads that log already administers the machine, and nothing has to be pasted
anywhere. The invented password stays valid until it is used, so a restart does not change it.

To set or reset a password at any time, without editing a file:

```bash
snowth_my_net web passwd alice                         # asks twice, hidden
docker compose exec web snowth_my_net web passwd alice # the same, in the running container
```

The passwords live in `web_accounts.json`, next to the state (mode 0600), and hold scrypt
hashes, never a password. Deleting that file forgets every password: the next start invents new
ones and logs them. The file is re-read at every sign-in, so `web passwd` reaches a running
interface without a restart — the sessions already open stay open.

* The session is an opaque token in a cookie (`HttpOnly`, `SameSite=Strict`, and `Secure` when
  the request arrived through a TLS proxy). It lasts `session_hours` and lives in the process:
  restarting the interface signs everybody out.
* After five failures an address waits a minute, right password or not; failures are logged with
  the address and their reason — `no such account` or `wrong password` — while the page itself
  stays vague on purpose.
* `/healthz` and the page's own stylesheet stay open, so that a probe needs no account.
* `check` warns when `web.bind` is not the loopback and no account is configured.
* A password must be at least 8 characters; the interface refuses shorter ones.

### A password managed elsewhere

When a configuration must hold everything (an image built by a pipeline, a secret from a vault),
an account can point at a hash instead. It is then read-only for the interface, and
`web passwd` refuses to touch it:

```bash
snowth_my_net web --hash-password > /etc/snowth_my_net/secrets/web_alice
chmod 600 /etc/snowth_my_net/secrets/web_alice
```

```yaml
      - name: alice
        password_file: web_alice      # relative to general.secrets_dir; password_env works too
```

That file must hold the one `scrypt$…` line and nothing else. A line cut in two by a copy from a
terminal, or the command's prompts pasted along with it, is refused **at startup**, naming the
account: the interface never falls back to serving without a login.

## Configuration

```yaml
web:
  bind: 127.0.0.1        # 0.0.0.0 only behind a reverse proxy, or with accounts
  port: 8080
  node_limit: 2000       # rows sent to the browser on the Nodes page
```

The Nodes page sends at most `node_limit` rows and says so when it truncates; the exported
`nodes.csv` always holds everything. `--bind` and `--port` override the file for one run.

## Security

* **Login optional, loopback by default.** Without `web.auth.users` there is no login at all,
  which is only safe on `127.0.0.1`. Over a network, add accounts *and* TLS: the login form and
  the session cookie travel in clear over plain HTTP, so put a TLS reverse proxy in front.
* **No secret is ever rendered**: the state holds credential names, never their values.
* Answers carry `X-Content-Type-Options: nosniff`, a `Content-Security-Policy` that allows only
  the page's own stylesheet and script, and `Referrer-Policy: no-referrer`. There is no form,
  no cookie, no external resource, no telemetry.
* Downloads are limited to the known exported file names (`devices.csv`, `nodes.csv`,
  `links.csv`, `snapshot.json`, `map.html`, `map.dot`, `map.mmd`): no path from a request ever
  reaches the file system.

## Keep it running (host install)

```ini
# /etc/systemd/system/snowth-web.service
[Unit]
Description=snowth_my_net web interface (read-only)
Wants=network-online.target
After=network-online.target

[Service]
User=snowth
Group=snowth
ExecStart=/usr/local/bin/snowth_my_net --config /etc/snowth_my_net/config.yml web
Restart=on-failure
NoNewPrivileges=yes
ProtectSystem=strict
ProtectHome=yes
PrivateTmp=yes
ReadWritePaths=/var/lib/snowth_my_net
CapabilityBoundingSet=
RestrictAddressFamilies=AF_INET AF_INET6 AF_UNIX
SystemCallArchitectures=native

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now snowth-web.service
```

The state directory is writable because SQLite needs it even to read (`-shm`, `-wal`); the
interface itself never writes.

## Behind a reverse proxy

The pages use absolute links from the root (`/nodes`, `/static/style.css`), so serve it at the
root of a host name rather than under a sub-path:

```nginx
server {
    server_name inventory.example.com;
    location / {
        proxy_pass http://127.0.0.1:8080;
        proxy_set_header Host $host;
        auth_basic "snowth_my_net";
        auth_basic_user_file /etc/nginx/snowth.htpasswd;
    }
}
```

`GET /healthz` answers `ok` in plain text, for a probe or a monitoring check.
