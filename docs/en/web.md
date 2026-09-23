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

Each table has a filter box (the `/` key focuses it) and sortable columns; the filter and the
sort happen in the browser, on the rows already sent. The line under the title says when the
last collect ran and how it went. Clicking a MAC shows the same explanation as
`snowth_my_net explain`, in the interface's language.

## What it cannot do

**It is read-only by design.** Only `GET` is answered, the state is opened in read-only mode,
and no page offers an action: no collect, no export, no setting. That is deliberate — the state
lock, the SNMP credentials and every write stay in the CLI and in the terminal interface
(`snowth_my_net tui`), which is also where you set a device type by hand or build a report.

## Configuration

```yaml
web:
  bind: 127.0.0.1        # 0.0.0.0 only behind a reverse proxy
  port: 8080
  node_limit: 2000       # rows sent to the browser on the Nodes page
```

The Nodes page sends at most `node_limit` rows and says so when it truncates; the exported
`nodes.csv` always holds everything. `--bind` and `--port` override the file for one run.

## Security

* **No login.** It binds to `127.0.0.1` by default and the container publishes it on the
  loopback of the host. To reach it from another machine, put a reverse proxy in front of it
  (TLS plus the authentication of your choice) and keep the interface itself on the loopback.
* **No secret is ever rendered**: the state holds credential names, never their values.
* Answers carry `X-Content-Type-Options: nosniff`, a `Content-Security-Policy` that allows only
  the page's own stylesheet and script, and `Referrer-Policy: no-referrer`. There is no form,
  no cookie, no external resource, no telemetry.
* Downloads are limited to the known exported file names (`devices.csv`, `nodes.csv`,
  `links.csv`, `snapshot.json`, `map.html`, `map.dot`, `map.mmd`): no path from a request ever
  reaches the file system.

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
