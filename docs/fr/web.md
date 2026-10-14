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
| Équipements | l'inventaire, comme `devices.csv` : nom, IP, constructeur, modèle, système, type, dernière collecte — plus toute adresse interrogée qui n'a pas répondu, en rouge, avec la raison |
| Nœuds | les adresses MAC et où elles se trouvent, comme `nodes.csv` ; le nom et la description s'écrivent directement dans le tableau |
| SNMP | quelles adresses sont interrogées, avec quel identifiant, et pourquoi l'une ne répond pas (un compte et son mot de passe redemandé) |
| Liens | les liens physiques trouvés par LLDP/CDP, comme `links.csv` |
| Inaccessibles | ce qui ne peut pas être interrogé en SNMP, quels voisins ne le sont pas, quels nœuds n'annoncent aucun nom — chacun avec ce qui a été essayé et pourquoi pas |
| Collectes | les 50 dernières exécutions, leur état et le nombre d'équipements qui ont répondu |
| Fichiers | les fichiers exportés présents dans le répertoire de sortie, à télécharger |

Les heures sont affichées dans le fuseau de la machine qui sert la page (`TZ`, réglé dans
`.env` pour la pile Compose), et le pied de page dit lequel ; survoler une heure montre la valeur
UTC stockée. Tout ce qui est écrit — `nodes.csv`, `snapshot.json`, les journaux — reste en UTC,
parce que c'est ce qu'attendent un importateur et un lecteur de journaux.

Chaque page s'ouvre sur **Comment lire ce tableau**, un panneau replié qui dit d'où vient chaque
colonne : quelle MIB, quelle règle, et pourquoi une case peut être vide. Chaque tableau a un champ de filtre (la touche `/` y place le curseur) et des colonnes
triables ; le filtre et le tri se font dans le navigateur, sur les lignes déjà envoyées.
**Colonnes** choisit lesquelles afficher, tirer le bord droit d'un en-tête règle sa largeur, et
survoler une valeur qui a dû être coupée en montre l'entier. Ces trois réglages sont gardés par
le navigateur, par page, et rien n'en atteint l'état. La ligne sous le
titre indique quand la dernière collecte a eu lieu et comment elle s'est passée. Cliquer sur une
MAC affiche la même explication que `snowth_my_net explain`, dans la langue de l'interface.

## Inventaire, ou mémoire

Une table MAC garde ce qu'elle a appris pendant `nodes.retention_days` (30 jours), donc la page
Nœuds est en partie un inventaire, en partie une mémoire. Deux pastilles au-dessus du tableau
font la différence :

| | |
|---|---|
| Vues à la dernière collecte | ce qui était encore là au dernier passage sur tous les équipements |
| Sans MAC aléatoires / MAC aléatoires seulement | les MAC administrés localement (les téléphones et portables les changent), écartés ou seuls ; ils portent une pastille « MAC aléatoire » et, seuls, sont triés par port |

Un MAC qui tourne est un autre nœud : rien n'est fusionné sur une supposition, et deux MAC
aléatoires entendus sur un même port sont une coïncidence de lieu, pas un seul appareil.
`export.nodes.random_macs: skip` les retire de `nodes.csv` et de la carte.
| Tout, historique compris | la même chose, plus ce que le réseau ne montre plus |

La référence est la dernière collecte **complète** — tester une seule adresse ne fait jamais
paraître le reste du réseau disparu. Une ligne sous le tableau dit combien de lignes sont de la
mémoire.

Pour vider cette mémoire et laisser la prochaine collecte la remplir avec ce que dit le réseau
aujourd'hui :

```bash
snowth_my_net node reset --yes
```

Les équipements, les liens et les noms donnés à la main restent ; seules les observations MAC et
ARP partent. Le même bouton est en bas de la page SNMP, replié et derrière le mot de passe.

## Nommer une MAC

Six cents lignes ne disent pas grand-chose tant que celles qui comptent n'ont pas de nom.
Écrivez-le directement dans la première colonne de la page Nœuds — `imprimante compta`,
`poste de Julie`, `caméra hall` — il s'enregistre en quittant la case ou avec `Enter`, sans
recharger la page, sans perdre votre filtre ni votre place dans la liste. `Escape` remet ce qui
était là. Le même champ est sur la page d'une MAC, et le filtre trouve un nom comme le reste.

Une colonne **Description** est à côté, écrite de la même façon, pour ce qu'un nom ne peut pas
porter : où c'est accroché, à quoi ça sert, qui appeler.

La colonne `DNS Name` est une résolution inverse (`dns check IP` dit quel résolveur répond et si
une zone inverse contient cette adresse). Quand aucune zone ne la contient, on peut encore
demander son nom à l'hôte lui-même — `dns probe IP` essaie NetBIOS, LLMNR et mDNS, comme le font
`nbtstat -A` et un scanner. C'est un diagnostic, pas une source : sur un parc durci les trois
sont muets, et un nom qu'un hôte déclare sur lui-même est une preuve plus faible qu'un nom que
le réseau détient. Un bail DHCP (MAC, adresse, nom annoncé par le client) est la source fiable
pour les appareils qu'aucune zone DNS ne connaît, et un nom donné à une MAC survit au changement
d'adresse.

```bash
snowth_my_net node name 00:11:22:33:44:55 "imprimante compta"
snowth_my_net node describe 00:11:22:33:44:55 "2e étage, local technique"
snowth_my_net node name 00:11:22:33:44:55        # vide : l'oublier
snowth_my_net node                               # tout ce qui a été donné
```

**Le nom appartient à l'adresse MAC, pas à la ligne.** Les positions bougent, les adresses
changent, une collecte réécrit tout ce qu'elle a lu : le nom reste. Il est gardé dans
`node_names.json` à côté de l'état, jamais dans la base, pour qu'une montée de schéma ou un état
jeté n'emporte pas les noms — c'est ce fichier qu'on copie quand on déplace une installation.

Il arrive aussi dans `snapshot.json` et dans `explain`. Il est absent de `nodes.csv` sauf si
`export.nodes.include_name: true`, pour que ce qui lit ce fichier continue d'y trouver les
colonnes qu'il connaît.

## Nommer beaucoup de MAC depuis un CSV

Le lien **Importer des noms depuis un CSV** au-dessus du tableau Nœuds ouvre `/import`, en trois
étapes.

1. **Récupérer la liste.** Le téléchargement contient tous les nœuds que le réseau a montrés,
   sous la forme `mac,name,ip,vendor`, avec le nom que chacun a aujourd'hui (vide s'il n'en a
   pas). Seules les deux premières colonnes sont relues ; l'adresse et le fabricant sont là pour
   vous aider à remplir les noms.
2. **Remplir la colonne des noms** dans un tableur. Vous pouvez aussi ajouter des MAC que le
   réseau n'a pas encore montrées : le nom est gardé et le nœud le porte dès qu'une collecte le
   voit (un nom n'invente pas un nœud). Une ligne sans nom ne change rien, et `,` comme `;`
   fonctionnent comme séparateur.
3. **Le renvoyer.** Rien n'est encore écrit : la page montre, ligne par ligne, ce qui serait
   `added`, `updated` (avec le nom qu'il avait), `unchanged`, `skipped` (pas de nom sur la
   ligne) ou une `error` (pas une MAC, un nom de plus de 60 caractères, une MAC déjà donnée plus
   haut). Si cela convient, **Appliquer** écrit les noms en une seule écriture atomique, et la
   page de résultat garde le même tableau et propose le **log** en CSV (`line`, `mac`, `name`,
   `before`, `result`, `detail`, et une dernière ligne de totaux).

Une mauvaise ligne est sautée et les autres passent. Un nom vide n'en efface jamais un : pour
cela, `node name MAC`. Les lignes qui commencent par `#` et les lignes vides sont ignorées ; un
fichier fait au plus 5000 lignes et 1 Mio. Le fichier voyage dans la page d'une étape à l'autre,
donc rien n'est appliqué qui n'ait été montré. Les règles sont celles de nommer à la main — le
compte quand des comptes sont configurés — et seul `node_names.json` est écrit.

## Connexions SNMP

L'onglet **SNMP** n'existe que si un compte est configuré, et il **redemande ce mot de passe**
avant de s'ouvrir — une session laissée sur un écran déverrouillé suffit à lire l'inventaire, pas
à changer ce à quoi l'outil parle. La confirmation dure quinze minutes, une déconnexion y met
fin, et une mauvaise réponse compte dans le même verrou qu'une connexion.

Il liste toutes les adresses interrogées : d'où elles viennent (une amorce, un voisin, un
balayage, ou la main), l'identifiant choisi pour chacune, le résultat de la dernière tentative
et, en cas d'échec, la raison. De là vous pouvez ajouter une adresse, en retirer une, en épingler
une à un identifiant — ou laisser l'outil les essayer tous — et en tester une, ce qui lance une
collecte pour cette seule adresse.

**Une communauté n'est jamais affichée ici**, et ne quitte jamais son fichier : l'état garde le
*nom* d'un identifiant, jamais sa valeur, et cette page ne lit rien d'autre. Les identifiants
eux-mêmes se déclarent dans le fichier de configuration, avec leurs secrets dans `secrets/` ;
cette page peut en choisir un pour une adresse, jamais en créer un.

`web.actions: false` retire cet onglet comme les boutons plus bas.

## Lancer quelque chose

La page Collectes porte les boutons : **Collecter**, **Découvrir**, **Exporter**, **Envoyer**
quand une cible de push est configurée, et **Demander les noms** quand `names.probe` liste un
protocole — il demande son nom à chaque nœud d'un coup, quoi que contienne le cache. L'interface ne fait pas le travail elle-même — elle
lance exactement la commande que vous auriez tapée, dans un processus séparé, et montre ce
qu'elle a rapporté :

```
Dernier : Collecter, terminé, 47 s — 12/13 devices, 1 error(s)
```

Une à la fois : pendant qu'une commande tourne, les boutons sont désactivés et la page revient
d'elle-même toutes les cinq secondes jusqu'à la fin. Le planificateur garde son propre rythme ;
le premier qui prend le verrou de l'état fait attendre l'autre, exactement comme deux terminaux.

`web.actions: false` retire les boutons et refuse les requêtes, pour une installation qui veut
l'interface strictement en lecture seule. **Sans compte configuré, les boutons n'existent pas** :
l'interface est en lecture seule, de même que les noms, l'import et le scan. Déclarez un compte
sous `web.auth.users` pour écrire.

## Scanner une adresse

Avec `web.nmap: true`, un compte et les boutons actifs, l'IP d'un équipement de l'onglet
Équipements ouvre sa page de scan, tout comme le lien en haut de la page d'un nœud. Choisissez un
profil et appuyez sur le bouton :

| Profil | Ce qu'il demande | Durée |
|---|---|---|
| quick | les 100 ports TCP les plus courants | quelques secondes |
| common | les 1000 ports TCP les plus courants, et la version de chaque service | environ une minute |
| all | les 65535 ports TCP et les versions | de nombreuses minutes |

Avec `quick`, le nom du service n'est que le nom habituel de ce port ; `common` et `all`
interrogent le service lui-même, ce qui rend un nom ou une version crédibles.

C'est `nmap` lancé sans privilège, une simple connexion TCP à chaque port : il ne change rien sur
l'équipement et ne peut pas deviner le système d'exploitation. Ce qu'il a trouvé est conservé, un
scan par adresse, et affiché sur la même page avec sa date. Un scan compte comme l'unique tâche
qui peut tourner, comme une collecte.

Seul ce que `discovery.allowed` permet et que `discovery.exclude` épargne est scanné, et un nom
n'est jamais accepté, seulement une adresse. Pour beaucoup d'adresses à la fois, la page affiche
la commande à coller dans un shell, qui applique les mêmes règles et garde ses résultats là où
cette page les montre :

```bash
docker compose exec web snowth_my_net scan 198.51.100.0/24 --profile common
```

**Un pare-feu ou un proxy sur le chemin peut répondre pour toutes les adresses.** Sans
privilège, nmap décide qu'un hôte est up en se connectant aux ports 80 et 443 : un équipement qui
accepte ces connexions pour tout le monde fait paraître toutes les adresses up, avec exactement
ces deux ports ouverts. Quand un même ensemble de ports ouverts revient d'au moins 5 adresses et
de la moitié de celles qui ont répondu, un scan de réseau les marque `suspect` au lieu de `ok`,
garde les ports sans les présenter comme ceux de l'hôte, et le dit. Si vous le voyez, scannez
depuis l'intérieur du segment ou regardez l'équipement intermédiaire. Un scan d'une seule adresse
ne peut pas faire cette comparaison.

Un scan de ports peut ressembler à de la reconnaissance pour un IPS : prévenez celui qui
l'exploite avant de commencer.

## Ce qu'elle ne fait pas

**Elle ne change jamais ce qui a été collecté.** Seuls les noms donnés à la main sont écrits, et
appuyer sur un bouton lance une commande au lieu de faire le travail dans le serveur : le verrou
de l'état, les identifiants SNMP, les types réglés à la main et le constructeur de rapports
restent dans la ligne de commande et dans l'interface en terminal (`snowth_my_net tui`).

## Connexion

Sans compte, il n'y a pas d'authentification et l'interface n'écoute que sur la boucle locale.
Déclarer un nom suffit — produire le mot de passe n'est pas votre travail :

```yaml
web:
  auth:
    session_hours: 12
    session_max_hours: 168
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
  quand la requête arrive par un proxy TLS). Elle se termine après `session_hours` sans requête
  (l'usage la renouvelle) et au plus tard `session_max_hours` après la connexion. Le dossier d'état
  garde une empreinte de chaque jeton dans `web_sessions.json` (mode 0600) : un redémarrage ou un
  redéploiement ne déconnecte personne. Le journal dit pourquoi un cookie est refusé : `idle`,
  `cap`, `closed` ou `unknown` (émis avant l'existence du fichier).
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
* **Les écritures doivent venir de ce site.** Un POST portant un `Origin` autre que l'hôte de la
  page, ou `Sec-Fetch-Site: cross-site`, est refusé avec un 403 : une page ouverte dans un autre
  onglet ne peut ni lancer une tâche ni renommer un nœud ; sans compte, toute écriture est de
  toute façon refusée (404). Sur une écoute en boucle locale, l'en-tête `Host` doit aussi être un nom de boucle
  locale (`localhost`, `127.0.0.1`, `::1`), ce qui arrête une page de DNS rebinding.
* **Les échecs de connexion sont comptés avant d'être vérifiés** : une rafale d'essais en
  parallèle ne passe donc pas le verrouillage ensemble. Changer un mot de passe ferme les autres
  sessions du compte.
* **La page SNMP reste dans la découverte.** Elle refuse `add`, `test` et l'épinglage d'un
  identifiant pour une adresse hors de `discovery.allowed` ou dans `discovery.exclude`, et un
  identifiant épinglé n'est envoyé que là où son `scope` le permet. Pour le reste, utilisez
  `snowth_my_net device add` depuis un shell.
* **Le premier mot de passe est écrit sur la console du processus, jamais dans le journal**, et
  `general.log_file` est créé avec le mode 0640.

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
