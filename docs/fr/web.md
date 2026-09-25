# Interface web

Une petite page en lecture seule sur l'état : équipements, nœuds, liens, collectes et fichiers
exportés. Elle est servie par le serveur HTTP de Python — aucun cadriciel, aucune base à elle,
aucune étape de construction.

```bash
snowth_my_net web                     # http://127.0.0.1:8080
snowth_my_net web --bind 0.0.0.0 --port 9000
```

Avec Docker Compose, c'est le service `web`, atteint à travers le service `nginx` qui termine
le TLS devant lui :

```bash
docker compose up -d                  # https://<host>:8443 (http://<host>:8080 y redirige)
SNOWTH_HTTPS_PORT=9443 docker compose up -d
```

## Ce qu'elle montre

| Page | Contenu |
|---|---|
| Équipements | l'inventaire, comme `devices.csv` : nom, IP, constructeur, modèle, système, type, dernière collecte |
| Nœuds | les adresses MAC et où elles se trouvent, comme `nodes.csv` ; une MAC ouvre son explication |
| Liens | les liens physiques trouvés par LLDP/CDP, comme `links.csv` |
| Collectes | les 50 dernières exécutions, leur état et le nombre d'équipements qui ont répondu |
| Fichiers | les fichiers exportés présents dans le répertoire de sortie, à télécharger |

Chaque page s'ouvre sur **Comment lire ce tableau**, un panneau replié qui dit d'où vient chaque
colonne : quelle MIB, quelle règle, et pourquoi une case peut être vide. Chaque tableau a un champ
de filtre (la touche `/` y place le curseur) et des colonnes triables ; le filtre et le tri se
font dans le navigateur, sur les lignes déjà envoyées. La ligne sous le
titre indique quand la dernière collecte a eu lieu et comment elle s'est passée. Cliquer sur une
MAC affiche la même explication que `snowth_my_net explain`, dans la langue de l'interface.

## Ce qu'elle ne fait pas

**Elle est en lecture seule par construction.** Seul `GET` est servi, l'état est ouvert en
lecture seule, et aucune page ne propose d'action : ni collecte, ni export, ni réglage. C'est
volontaire — le verrou de l'état, les identifiants SNMP et toutes les écritures restent dans la
ligne de commande et dans l'interface en terminal (`snowth_my_net tui`), où l'on règle aussi un
type à la main ou construit un rapport.

## Connexion

Sans compte, il n'y a pas d'authentification et l'interface n'écoute que sur la boucle locale.
Déclarer un nom suffit — produire le mot de passe n'est pas votre travail :

```yaml
web:
  auth:
    session_hours: 12
    users:
      - name: alice
```

Au démarrage, l'interface voit un compte sans mot de passe, en invente un et l'écrit :

```
WARNING web user 'alice' has no password yet - sign in once with: k7m3-qp9x-4tvr
        (the interface then asks you to choose your own)
```

Connectez-vous une fois avec ; l'interface demande alors le vôtre avant de montrer quoi que ce
soit. Qui lit ce journal administre déjà la machine, et rien n'a à être collé nulle part. Le mot
de passe inventé reste valable tant qu'il n'a pas servi : un redémarrage ne le change pas.

Pour définir ou réinitialiser un mot de passe à tout moment, sans éditer de fichier :

```bash
snowth_my_net web passwd alice                         # demandé deux fois, masqué
docker compose exec web snowth_my_net web passwd alice # idem, dans le conteneur qui tourne
```

Les mots de passe vivent dans `web_accounts.json`, à côté de l'état (mode 0600), sous forme
d'empreintes scrypt, jamais en clair. Supprimer ce fichier oublie tous les mots de passe : le
démarrage suivant en invente d'autres et les journalise. Le fichier est relu à chaque connexion,
donc `web passwd` atteint une interface qui tourne sans redémarrage — les sessions déjà ouvertes
le restent.

* La session est un jeton opaque dans un témoin (`HttpOnly`, `SameSite=Strict`, et `Secure`
  quand la requête arrive par un proxy TLS). Elle dure `session_hours` et vit dans le processus :
  redémarrer l'interface déconnecte tout le monde.
* Après cinq échecs, une adresse patiente une minute, bon mot de passe ou non ; les échecs sont
  journalisés avec l'adresse et leur raison — `no such account` ou `wrong password` — alors que
  la page, elle, reste volontairement vague.
* `/healthz` et la feuille de style de la page restent ouverts, pour qu'une sonde n'ait pas
  besoin de compte.
* `check` avertit quand `web.bind` n'est pas la boucle locale et qu'aucun compte n'est défini.
* Un mot de passe fait au moins 8 caractères ; l'interface refuse plus court.
* Changer de mot de passe dans le navigateur demande d'abord l'actuel — une session laissée
  ouverte sur un écran déverrouillé ne suffit pas à s'emparer du compte — et les erreurs
  comptent dans le même verrou qu'une connexion. `web passwd`, dans un terminal sur la
  machine, ne le demande pas : c'est la porte de secours quand le mot de passe est perdu.

### Un mot de passe géré ailleurs

Quand la configuration doit tout contenir (une image construite par une chaîne d'intégration, un
secret venu d'un coffre), un compte peut pointer vers une empreinte. Elle est alors en lecture
seule pour l'interface, et `web passwd` refuse d'y toucher :

```bash
snowth_my_net web --hash-password > /etc/snowth_my_net/secrets/web_alice
chmod 600 /etc/snowth_my_net/secrets/web_alice
```

```yaml
      - name: alice
        password_file: web_alice      # relatif à general.secrets_dir ; password_env marche aussi
```

Ce fichier doit contenir cette seule ligne `scrypt$…`, rien d'autre. Une ligne coupée en deux par
un copier-coller depuis le terminal, ou les invites de la commande collées avec elle, est refusée
**au démarrage**, avec le nom du compte : l'interface ne se rabat jamais sur un service sans
authentification.

## Configuration

```yaml
web:
  bind: 127.0.0.1        # 0.0.0.0 seulement derrière un proxy inverse, ou avec des comptes
  port: 8080
  node_limit: 2000       # lignes envoyées au navigateur sur la page Nœuds
```

La page Nœuds envoie au plus `node_limit` lignes et le dit quand elle tronque ; le fichier
`nodes.csv` exporté contient toujours l'ensemble. `--bind` et `--port` priment sur le fichier
pour une exécution.

## Sécurité

* **Authentification optionnelle, boucle locale par défaut.** Sans `web.auth.users`, il n'y a
  aucune authentification, ce qui n'est sûr que sur `127.0.0.1`. Sur un réseau, ajoutez des
  comptes *et* du TLS : le formulaire de connexion et le témoin de session circulent en clair
  en HTTP simple, donc placez un proxy inverse TLS devant.
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

## La façade TLS

La pile Compose répond sur `https://<host>:8443`, et y redirige `http://<host>:8080`. Les deux
ports se règlent dans `.env` (`SNOWTH_HTTPS_PORT`, `SNOWTH_HTTP_PORT`), et l'interface elle-même
n'est publiée nulle part : le proxy est la seule porte d'entrée.

Le certificat est **auto-signé**, généré au premier démarrage et conservé dans le volume
`certs_web`. Dites pour qui avant ce premier démarrage, pour qu'il corresponde au moins à
l'adresse que les gens saisissent :

```bash
SNOWTH_TLS_HOSTS=inventory.example.net,192.0.2.10,localhost,127.0.0.1
```

Soyons honnêtes sur ce qu'il apporte : il cache le mot de passe et le témoin de session à qui
écoute le réseau, et le navigateur avertira à chaque visite parce que rien ne le cautionne. Pour
faire disparaître l'avertissement, remplacez `server.crt` et `server.key` dans ce volume par un
certificat signé par votre propre autorité, ou par Let's Encrypt — nginx lit les deux mêmes
chemins :

```bash
docker compose cp votre.crt nginx:/etc/nginx/certs/server.crt
docker compose cp votre.key nginx:/etc/nginx/certs/server.key
docker compose restart nginx
```

### L'adresse du lecteur

Sans précaution, l'interface verrait toutes les requêtes venir du proxy : une seule adresse dans
le journal pour tout le monde, et cinq mauvais mots de passe verrouillant tout le monde. Le
service `web` est donc lancé avec `--trusted-proxy 172.16.0.0/12` (là où Docker place ses
réseaux bridge), et la façade annonce dans `X-Forwarded-For` l'adresse à laquelle elle parle. Un
en-tête venant de quelqu'un d'autre est ignoré — c'est la même clé qui empêche un lecteur
d'inventer une adresse pour contourner le verrou. La clé de configuration est
`web.trusted_proxies`.

### Votre propre proxy à la place

Les pages utilisent des liens absolus depuis la racine (`/nodes`, `/static/style.css`) :
servez-la à la racine d'un nom d'hôte plutôt que sous un sous-chemin, et passez
`X-Forwarded-Proto: https` pour que le témoin de session soit marqué `Secure` :

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

`GET /healthz` répond `ok` en texte brut, pour une sonde ou une supervision.
