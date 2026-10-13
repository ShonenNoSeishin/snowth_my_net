# Web interface

A small read-only page over the state: devices, nodes, links, runs, and the exported files.
It is served by Python's own HTTP server — no framework, no database of its own, no build step.

```bash
snowth_my_net web                     # http://127.0.0.1:8080
snowth_my_net web --bind 0.0.0.0 --port 9000
```

With Docker Compose it is the `web` service, reached through the `nginx` service that
terminates TLS in front of it:

```bash
docker compose up -d                  # https://<host>:8443 (http://<host>:8080 redirects there)
SNOWTH_HTTPS_PORT=9443 docker compose up -d
```

## What it shows

| Page | Content |
|---|---|
| Devices | the inventory, as `devices.csv`: name, IP, vendor, model, OS, type, last collect — plus every address that was polled and did not answer, in red, with the reason |
| Nodes | MAC addresses and where they are, as `nodes.csv`; the name and the description are written straight in the table |
| SNMP | which addresses are polled, with which credential, and why one does not answer (an account and its password again) |
| Links | the physical links found through LLDP/CDP, as `links.csv` |
| Unreachable | what cannot be polled over SNMP, which neighbours are not polled, which nodes state no name — each with what was tried and why not |
| Runs | the last 50 runs, their status and how many devices answered |
| Files | the exported files present in the output directory, to download |

A MAC seen in several places takes several lines, each marked with its number of positions; the
IP column shows the elected address and then, in grey, the other addresses known for that MAC. In
Devices, '+n MAC' marks a device known by several addresses.

Times are shown in the time zone of the machine that serves the page (`TZ`, set in `.env`
for the Compose stack), and the footer says which one; hovering a time shows the UTC value that
is stored. Everything written — `nodes.csv`, `snapshot.json`, the logs — stays in UTC, because
that is what an importer and a log reader need.

Each page opens with **How to read this table**, a collapsed panel saying where every column
comes from: which MIB, which rule, and why a cell can be empty. The ☾/☀ button in the header switches between light and dark (the choice is kept by the browser,
otherwise the system one applies), and EN/FR changes the language.

Each table has a filter box (the `/` key focuses it) and sortable columns; the filter and the
sort happen in the browser, on the rows already sent. **Columns** chooses which ones to show,
dragging the right edge of a heading sets its width, and hovering a value that had to be cut
shows the whole of it. Those three are kept by the browser, per page, and nothing of them
reaches the state. The line under the title says when the
last collect ran and how it went. Clicking a MAC shows the same explanation as
`snowth_my_net explain`, in the interface's language.

## Inventory, or memory

A MAC table keeps what it has learned for `nodes.retention_days` (30 days), so the Nodes page is
part inventory and part memory. Two pills above the table tell them apart:

| | |
|---|---|
| Seen at the last collect | what was still there the last time every device was polled |
| Everything, history included | the same, plus what the network no longer shows |

The reference is the last **full** collect — testing one address alone never makes the rest of
the network look gone. A line under the table says how many rows are memory.

To empty that memory and let the next collect fill it from what the network says today:

```bash
snowth_my_net node reset --yes
```

The devices, the links and the names given by hand stay; only the MAC and ARP observations go.
The same button is at the bottom of the SNMP page, folded away and behind the password.

## Naming a MAC

Six hundred rows say little until the ones that matter carry a name. Write it straight in the
first column of the Nodes page — `imprimante compta`, `poste de Julie`, `caméra hall` — and it
saves itself when you leave the cell or press `Enter`, without reloading the page, losing your
filter or your place in the list. `Escape` puts back what was there. The same field is on a
MAC's own page, and the filter box finds a name like anything else.

A **Description** column sits next to it, written the same way, for what a name cannot hold:
where it hangs, what it is for, whom to call.

The `DNS Name` column is a reverse lookup (`dns check IP` says which resolver answers and
whether a reverse zone holds that address). When no zone holds it, a host can still be asked its
own name — `dns probe IP` tries NetBIOS, LLMNR and mDNS, the way `nbtstat -A` and a scanner do.
That is a diagnostic, not a source: on a hardened fleet all three are silent, and a name a host
declares about itself is weaker evidence than one the network holds. A DHCP lease (MAC, address,
the name the client announced) is the reliable source for devices no DNS zone knows, and a name
given to a MAC survives the address changing.

```bash
snowth_my_net node name 00:11:22:33:44:55 "imprimante compta"
snowth_my_net node describe 00:11:22:33:44:55 "2e étage, local technique"
snowth_my_net node name 00:11:22:33:44:55        # empty: forget it
snowth_my_net node                               # everything given so far
```

**The name belongs to the MAC address, not to the row.** Positions move, addresses change, a
collect rewrites everything it read: the name stays. It is kept in `node_names.json` next to the
state, never in the database, so that a schema upgrade or a state thrown away keeps the names —
that file is the one to copy when you move an installation.

It reaches `snapshot.json` and `explain` too. It is left out of `nodes.csv` unless
`export.nodes.include_name: true`, so that whatever reads that file keeps finding the columns it
knows.

## Naming many MACs from a CSV

The **Import names from a CSV** link above the Nodes table opens `/import`, in three steps.

1. **Get the list.** The download is every node the network has shown, as `mac,name,ip,vendor`,
   with the name each one has now (empty when none). Only the first two columns are read back;
   the address and the vendor are there to help you fill the names in.
2. **Fill the name column** in a spreadsheet. You can also add MACs the network has not shown
   yet: the name is kept and the node carries it once a collect sees it (a name does not invent
   a node). A line with no name changes nothing, and `,` or `;` both work as the separator.
3. **Send it back.** Nothing is written yet: the page shows, line by line, what would be
   `added`, `updated` (with the name it had), `unchanged`, `skipped` (no name on the line) or
   an `error` (not a MAC, a name over 60 characters, a MAC already given on an earlier line).
   If it suits you, **Apply** writes the names in one atomic write, and the result page keeps
   the same table and offers the **log** as a CSV (`line`, `mac`, `name`, `before`, `result`,
   `detail`, and a last row of totals).

A bad line is skipped and the others still go through. An empty name never erases one: use
`node name MAC` for that. Lines starting with `#` and blank lines are ignored; a file holds at
most 5000 lines and 1 MiB. The file travels in the page between the steps, so nothing is
applied that was not shown. It follows the rules of naming by hand — the account when accounts
are configured — and writes `node_names.json` only.

## SNMP connections

The **SNMP** tab exists only when an account is configured, and it **asks for that password
again** before it opens — a session left on an unlocked screen is enough to read the inventory,
not to change what the tool talks to. The confirmation lasts fifteen minutes, a sign-out ends it,
and a wrong answer counts towards the same limiter as a login.

It lists every address that is polled: where it came from (a seed, a neighbour, a sweep, or a
hand), the credential chosen for it, the result of the last attempt and, when it failed, the
reason. From there you can add an address, remove one, pin one to a credential — or let the tool
try them all again — and test one, which runs a collect for that address alone.

**A community is never shown here**, and never leaves its file: the state holds the *name* of a
credential, never its value, and this page reads nothing else. Credentials themselves are
declared in the configuration file, with their secrets in `secrets/`; this page can choose one
for an address, never create one.

`web.actions: false` removes this tab as well as the buttons below.

## Running something

The Runs page carries the buttons: **Collect**, **Discover**, **Export**, **Push** when a push
target is configured, and **Ask names** when `names.probe` lists a protocol — it asks every node
its own name at once, whatever the cache holds. The interface does not do the work itself — it starts the very
command you would have typed, as a separate process, and shows what it reported:

```
Last: Collect, done, 47 s — 12/13 devices, 1 error(s)
```

One at a time: while something runs the buttons are disabled and the page comes back on its own
every five seconds until it ends. The scheduler keeps its own pace; whoever gets the state lock
first makes the other wait, exactly as two shells would.

`web.actions: false` removes the buttons and refuses the requests, for an installation that
wants the interface strictly read-only. **With no account configured the buttons do not exist**:
the interface is read-only, and so are the names, the import and the scan. Declare an account
under `web.auth.users` to write.

## Scanning one address

With `web.nmap: true`, an account and the buttons on, the IP of a device in the Devices tab opens
its scan page, and so does the link at the top of a node's page. Pick a profile and press the
button:

| Profile | What it asks | Takes |
|---|---|---|
| quick | the 100 most common TCP ports | a few seconds |
| common | the 1000 most common TCP ports, and the version of each service | about a minute |
| all | the 65535 TCP ports and versions | many minutes |

In `quick` the service name is only the usual name of that port; `common` and `all` ask the
service itself, which is what makes a name or a version worth believing.

It is `nmap` run without privilege, a plain TCP connection to each port: it changes nothing on the
device and cannot guess the operating system. What it found is kept, one scan per address, and
shown on the same page with its date. A scan counts as the one job that may run, like a collect.

Only what `discovery.allowed` permits and `discovery.exclude` spares is scanned, and a name is
never accepted, only an address. For many addresses at once the page prints the command to paste
in a shell, which applies the same rules and keeps its results where this page shows them:

```bash
docker compose exec web snowth_my_net scan 198.51.100.0/24 --profile common
```

**A firewall or proxy in the path can answer for every address.** Without privilege, nmap decides
that a host is up by connecting to ports 80 and 443, so a device that accepts those connections
for everyone makes every address look up, with exactly those two ports open. When one same set
of open ports comes back from at least 5 addresses and from half of those that answered, a
network scan marks them `suspect` instead of `ok`, keeps the ports without presenting them as
the host's own, and says so. If you see it, scan from inside the segment or look at the device
in between. A single-address scan cannot make that comparison.

A port scan can look like reconnaissance to an IPS: tell whoever runs it before you start.

## What it does not do

**It never changes what was collected.** Only names given by hand are written, and pressing a
button starts a command instead of doing the work in the server: the state lock, the SNMP
credentials, the device types set by hand and the report builder stay in the CLI and in the
terminal interface (`snowth_my_net tui`).

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
* Changing a password in the browser asks for the current one first — a session left open on
  an unlocked screen is not enough to take the account over — and wrong answers count towards
  the same limiter as a login. `web passwd`, in a shell on the machine, does not ask: it is
  the way back in when the password is lost.

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
* **Writes must come from this site.** A POST carrying an `Origin` other than the page's own host,
  or `Sec-Fetch-Site: cross-site`, is refused with 403, so a page open in another tab cannot start
  a job or rename a node; with no account every write is refused anyway (404). On a loopback
  listener the `Host` header must also be a loopback name (`localhost`, `127.0.0.1`, `::1`),
  which stops a DNS-rebinding page.
* **Failed logins are counted before they are checked**, so a burst of parallel guesses cannot
  pass the lockout together. Changing a password closes the account's other sessions.
* **The SNMP page stays inside discovery.** It refuses `add`, `test` and a credential pin for an
  address outside `discovery.allowed` or inside `discovery.exclude`, and a pinned credential is
  still only sent where its `scope` says. For anything else use `snowth_my_net device add` from a
  shell.
* **The first password is printed on the console of the process, never in the log**, and
  `general.log_file` is created with mode 0640.

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

## The TLS front

The Compose stack answers on `https://<host>:8443`, and redirects `http://<host>:8080` there.
Both ports are `.env` matters (`SNOWTH_HTTPS_PORT`, `SNOWTH_HTTP_PORT`), and the interface
itself is published nowhere: the proxy is the only way in.

The certificate is **self-signed**, generated on the first start and kept in the `certs_web`
volume. Say who it is for before that first start, so that it at least matches the address
people type:

```bash
SNOWTH_TLS_HOSTS=inventory.example.net,192.0.2.10,localhost,127.0.0.1
```

Be honest about what it buys: it hides the password and the session cookie from anyone
listening on the network, and browsers will warn on every visit because nothing vouches for it.
To get rid of the warning, replace `server.crt` and `server.key` in that volume with a
certificate signed by your own CA, or by Let's Encrypt — nginx reads the same two paths:

```bash
docker compose cp your.crt nginx:/etc/nginx/certs/server.crt
docker compose cp your.key nginx:/etc/nginx/certs/server.key
docker compose restart nginx
```

### The reader's own address

The interface would otherwise see every request come from the proxy: one address in the log for
everybody, and five wrong passwords locking everybody out. So the `web` service is started with
`--trusted-proxy 172.16.0.0/12` (where Docker puts its bridge networks), and the front states
the address it is talking to in `X-Forwarded-For`. A header from anyone else is ignored — the
same key is what stops a reader from inventing an address to dodge the limiter. The
configuration key is `web.trusted_proxies`.

### Your own proxy instead

The pages use absolute links from the root (`/nodes`, `/static/style.css`), so serve the
interface at the root of a host name rather than under a sub-path, and pass
`X-Forwarded-Proto: https` so that the session cookie is marked `Secure`:

```nginx
server {
    server_name inventory.example.com;
    location / {
        proxy_pass http://127.0.0.1:8080;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-For $remote_addr;
        proxy_set_header X-Forwarded-Proto https;
    }
}
```

`GET /healthz` answers `ok` in plain text, for a probe or a monitoring check.
