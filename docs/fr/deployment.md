# Déploiement

Deux façons de premier ordre, qui partagent le même fichier de configuration : une installation
sur l'hôte planifiée par cron ou systemd, et Docker Compose. snowth_my_net ne tourne jamais
lui-même en démon : chaque exécution est un processus qui se termine. Son propre verrou
(`state.lock`) garantit que deux exécutions ne se chevauchent jamais, quel que soit le
planificateur.

Avant toute chose : `snowth_my_net check` diagnostique les identifiants et le support des MIB,
équipement par équipement.

## 1. Hôte : pipx + cron ou systemd

```bash
sudo useradd --system --home /var/lib/snowth_my_net --shell /usr/sbin/nologin snowth
sudo install -d -o snowth -g snowth -m 0750 /var/lib/snowth_my_net
sudo install -d -o root -g snowth -m 0750 /etc/snowth_my_net /etc/snowth_my_net/secrets

# Depuis le dépôt git (PyPI plus tard) :
sudo PIPX_HOME=/opt/pipx PIPX_BIN_DIR=/usr/local/bin pipx install git+ssh://git@github.com/ShonenNoSeishin/snowth_my_net.git
#   ou : pipx install ./snowth_my_net   (un clone local)

sudo -u snowth snowth_my_net init --output /etc/snowth_my_net/config.yml   # puis l'adapter
printf '%s' 'the-v3-auth-key' | sudo install -o snowth -g snowth -m 0600 /dev/stdin /etc/snowth_my_net/secrets/snmp_v3_auth
printf '%s' 'the-v3-priv-key' | sudo install -o snowth -g snowth -m 0600 /dev/stdin /etc/snowth_my_net/secrets/snmp_v3_priv

sudo -u snowth snowth_my_net check
sudo -u snowth snowth_my_net collect
sudo -u snowth snowth_my_net tui        # ou simplement : snowth_my_net
```

### cron

La planification se trouve dans `schedule:` ; générez les lignes (avec des chemins absolus, car
le `PATH` de cron contient rarement celui de pipx) :

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

Les rapports qui ont un `schedule:` ajoutent chacun une ligne `report run <name>` (voir
[extensions.md](extensions.md#planification-et-push)).

Régénérez après avoir modifié `schedule:` ou la planification d'un rapport. `CRON_TZ=` est écrit
quand `schedule.timezone` est défini (cronie le prend en charge ; avec les autres crons, réglez le
fuseau horaire de l'hôte).

### Timers systemd

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

La même paire pour l'export et le push figure ci-dessous (ajoutez un fuseau horaire comme
`Europe/Brussels` à `OnCalendar` si nécessaire). Ajoutez le répertoire de sortie à
`ReadWritePaths` quand il n'est pas sous le répertoire d'état.

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
# mêmes lignes de durcissement que snowth-collect.service
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

Supervision : `snowth_my_net health` sort avec le code 1 quand la dernière collecte réussie est
plus ancienne que deux fois le plus long intervalle de `schedule.collect` (ou que
`schedule.health_max_age`).

## 2. Docker Compose

Un seul service, `snowth`, fait tourner [supercronic](https://github.com/aptible/supercronic)
(compatible cron, journaux sur stdout, sans root). Au démarrage, il génère la crontab à partir de
`schedule:` — aucune crontab à maintenir sur l'hôte — et lance une collecte.

```bash
git clone git@github.com:ShonenNoSeishin/snowth_my_net.git && cd snowth_my_net
cp .env.example .env                          # régler SNOWTH_UID/SNOWTH_GID sur "id -u"/"id -g"
mkdir -p config/extensions data output secrets
docker compose build
# configuration d'exemple commentée, écrite dans ./config (puis l'adapter)
docker run --rm -u "$(id -u):$(id -g)" -v "$PWD/config:/work" snowth_my_net:latest \
  init --output /work/snowth_my_net.yml
printf '%s' 'the-v3-auth-key' > secrets/snmp_v3_auth
printf '%s' 'the-v3-priv-key' > secrets/snmp_v3_priv
printf '%s' 'the-push-token'  > secrets/cmdb_token
chmod 600 secrets/*
docker compose run --rm snowth check
docker compose up -d
```

Dans `config/snowth_my_net.yml`, les fichiers de secrets sont désignés par leur nom
(`auth_key_file: snmp_v3_auth`) : le conteneur définit `SNOWTH_SECRETS_DIR=/run/secrets`, où
Compose les monte.

### Image

* Construction en plusieurs étapes sur `python:3.13-slim` ; ni outil de construction ni pip dans
  l'image finale ; environ 200 Mo décompressée (la base Python pèse 126 Mo). Une image distroless
  n'a pas été retenue car supercronic lance les tâches via `/bin/sh -c`.
* supercronic est téléchargé à la construction et vérifié avec son SHA-256 publié.
* Tourne sous un utilisateur non root (`SNOWTH_UID:SNOWTH_GID`, 10001 par défaut).

### Volumes

| Hôte | Conteneur | |
|---|---|---|
| `./config/snowth_my_net.yml` | `/etc/snowth_my_net/config.yml` | lecture seule |
| `./config/extensions/` | `/etc/snowth_my_net/extensions/` | lecture seule, collecteurs et rapports personnalisés |
| `./data/` | `/var/lib/snowth_my_net` | état, verrou, base des constructeurs |
| `./output/` | `/output` | CSV, JSON, cartes, lisibles sur l'hôte |

### Secrets

Déclarés sous `secrets:` et montés dans `/run/secrets/`. Avec Compose hors Swarm, ce sont des
montages qui gardent le propriétaire et les droits de l'hôte (`uid`/`gid`/`mode` sont ignorés) :
c'est pourquoi le conteneur tourne avec votre UID/GID, et les fichiers peuvent rester en
`chmod 600`.

### Réseau

Le réseau bridge par défaut suffit : SNMP (UDP/161) et HTTPS sont sortants. **Le SNMP sort avec
l'adresse IP de l'hôte** (NAT) : cette adresse doit être autorisée dans les ACL SNMP des
équipements. `network_mode: host` n'est pas nécessaire, et aucun port n'est exposé. Pour le DNS
interne, réglez `dns.resolvers` (sinon le conteneur utilise le résolveur de Docker).

### Durcissement

`read_only: true`, `tmpfs: /tmp`, `cap_drop: [ALL]`, `no-new-privileges`, `init: true`,
`restart: unless-stopped`, rotation des journaux JSON (10 Mo × 3), contrôle de santé
`snowth_my_net health` (période de démarrage de 30 minutes).

### Exploitation

```bash
docker compose run --rm snowth check
docker compose run --rm snowth explain 00:11:22:33:44:55
docker compose run --rm snowth run --wait
docker compose run --rm snowth tui
docker compose logs -f snowth
docker compose ps                  # état de santé
```

### Tests

```bash
docker compose --profile test run --rm tests
```

Démarre deux simulateurs SNMP et un faux serveur d'import HTTPS sous forme de conteneurs, puis
lance toute la suite de tests ainsi qu'un test de bout en bout à travers eux (collecte, export,
push avec une AC autosignée).
