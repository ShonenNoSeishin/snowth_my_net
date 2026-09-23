# Interface web

Une petite page en lecture seule sur l'état : équipements, nœuds, liens, collectes et fichiers
exportés. Elle est servie par le serveur HTTP de Python — aucun cadriciel, aucune base à elle,
aucune étape de construction.

```bash
snowth_my_net web                     # http://127.0.0.1:8080
snowth_my_net web --bind 0.0.0.0 --port 9000
```

Avec Docker Compose, c'est le service `web`, publié sur la boucle locale de l'hôte :

```bash
docker compose up -d web              # http://127.0.0.1:8080
SNOWTH_WEB_PORT=9000 docker compose up -d web
```

## Ce qu'elle montre

| Page | Contenu |
|---|---|
| Équipements | l'inventaire, comme `devices.csv` : nom, IP, constructeur, modèle, système, type, dernière collecte |
| Nœuds | les adresses MAC et où elles se trouvent, comme `nodes.csv` ; une MAC ouvre son explication |
| Liens | les liens physiques trouvés par LLDP/CDP, comme `links.csv` |
| Collectes | les 50 dernières exécutions, leur état et le nombre d'équipements qui ont répondu |
| Fichiers | les fichiers exportés présents dans le répertoire de sortie, à télécharger |

Chaque tableau a un champ de filtre (la touche `/` y place le curseur) et des colonnes triables ;
le filtre et le tri se font dans le navigateur, sur les lignes déjà envoyées. La ligne sous le
titre indique quand la dernière collecte a eu lieu et comment elle s'est passée. Cliquer sur une
MAC affiche la même explication que `snowth_my_net explain`, dans la langue de l'interface.

## Ce qu'elle ne fait pas

**Elle est en lecture seule par construction.** Seul `GET` est servi, l'état est ouvert en
lecture seule, et aucune page ne propose d'action : ni collecte, ni export, ni réglage. C'est
volontaire — le verrou de l'état, les identifiants SNMP et toutes les écritures restent dans la
ligne de commande et dans l'interface en terminal (`snowth_my_net tui`), où l'on règle aussi un
type à la main ou construit un rapport.

## Configuration

```yaml
web:
  bind: 127.0.0.1        # 0.0.0.0 seulement derrière un proxy inverse
  port: 8080
  node_limit: 2000       # lignes envoyées au navigateur sur la page Nœuds
```

La page Nœuds envoie au plus `node_limit` lignes et le dit quand elle tronque ; le fichier
`nodes.csv` exporté contient toujours l'ensemble. `--bind` et `--port` priment sur le fichier
pour une exécution.

## Sécurité

* **Aucune authentification.** Elle écoute sur `127.0.0.1` par défaut et le conteneur la publie
  sur la boucle locale de l'hôte. Pour y accéder depuis une autre machine, placez un proxy
  inverse devant (TLS et l'authentification de votre choix) et laissez l'interface sur la
  boucle locale.
* **Aucun secret n'est jamais affiché** : l'état ne garde que le nom des identifiants, jamais
  leur valeur.
* Les réponses portent `X-Content-Type-Options: nosniff`, une `Content-Security-Policy` qui
  n'autorise que la feuille de style et le script de la page, et `Referrer-Policy: no-referrer`.
  Aucun formulaire, aucun témoin, aucune ressource externe, aucune télémétrie.
* Les téléchargements sont limités aux noms de fichiers exportés connus (`devices.csv`,
  `nodes.csv`, `links.csv`, `snapshot.json`, `map.html`, `map.dot`, `map.mmd`) : aucun chemin
  venant d'une requête n'atteint le système de fichiers.

## La garder en fonctionnement (installation sur l'hôte)

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

Le répertoire d'état est accessible en écriture parce que SQLite en a besoin même pour lire
(`-shm`, `-wal`) ; l'interface, elle, n'écrit jamais.

## Derrière un proxy inverse

Les pages utilisent des liens absolus depuis la racine (`/nodes`, `/static/style.css`) :
servez-la à la racine d'un nom d'hôte plutôt que sous un sous-chemin.

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

`GET /healthz` répond `ok` en texte brut, pour une sonde ou une supervision.
