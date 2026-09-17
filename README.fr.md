# snowth_my_net

*[English](README.md)*

Un outil léger de cartographie réseau en SNMP, **en lecture seule**. snowth_my_net interroge vos
switches, routeurs, pare-feu et points d'accès, fusionne leurs tables MAC et ARP, suit LLDP et
CDP, et répond à trois questions :

* **Quels équipements existent ?** Modèle, numéro de série, système et version, IP de
  management, type.
* **Qui est branché où ?** MAC, IP, nom DNS, switch, port, VLAN, dernière observation, historique
  d'itinérance.
* **Comment les équipements sont-ils reliés ?** Liens LLDP et CDP, en CSV et en carte.

Tout est exporté en CSV à format fixe, en JSON et en cartes, et peut être poussé en HTTP selon
un planning vers n'importe quel outil. Une interface en terminal permet de consulter, de régler à
la main et de tester des OID.

## Pourquoi cet outil

* **Lecture seule stricte.** Seuls SNMP GET, GETNEXT et GETBULK existent dans le code ; un test le
  vérifie sur le réseau.
* **Il ne se fie jamais à ce que l'équipement annonce.** Un pare-feu qui n'annonce pas le niveau 3
  voit quand même sa table ARP lue : chaque MIB standard est tentée sur chaque équipement, et
  chaque fonction peut être forcée ou désactivée par équipement. **Le type n'est qu'une
  étiquette**, jamais une condition.
* **Des positions fiables.**
  * Une MAC est placée sur un port d'accès, jamais sur un uplink. Un port est un uplink s'il a un
    voisin LLDP/CDP, s'il est déclaré, s'il porte trop de MAC ou, en option, s'il fait partie
    d'un LAG.
  * Les téléphones IP et les points d'accès sont gérés.
  * Une MAC vue en même temps sur plusieurs ports est tranchée.
  * `explain` dit pourquoi une MAC est à tel endroit.
* **Léger.** Un processus par exécution, un fichier SQLite, quatre dépendances (plus Textual pour
  l'interface), ni serveur web ni serveur de base de données.

## Démarrage rapide

### Avec pipx (cron ou systemd de l'hôte)

```bash
pipx install git+ssh://git@github.com/ShonenNoSeishin/snowth_my_net.git
snowth_my_net init --output snowth_my_net.yml     # exemple commenté, à adapter
mkdir -p secrets && printf '%s' 'la-clé-auth-v3' > secrets/snmp_v3_auth && chmod 600 secrets/*
snowth_my_net check                               # le diagnostic à lancer en premier
snowth_my_net collect
snowth_my_net export                              # ./output ou general.output_dir
snowth_my_net                                     # interface en terminal
snowth_my_net cron print                          # lignes de crontab issues de schedule:
```

### Avec Docker Compose

```bash
cp .env.example .env && mkdir -p config/extensions data output secrets
docker compose build
docker run --rm -u "$(id -u):$(id -g)" -v "$PWD/config:/work" snowth_my_net:latest \
  init --output /work/snowth_my_net.yml
# secrets dans ./secrets (chmod 600), puis adapter config/snowth_my_net.yml
docker compose run --rm snowth check
docker compose up -d
docker compose logs -f snowth
```

Détails, unités systemd, durcissement et réseau : [docs/deployment.md](docs/deployment.md) (en
anglais).

## Interface en terminal

`snowth_my_net` (ou `snowth_my_net tui`, `docker compose run --rm snowth tui`) :

* **Équipements** : liste filtrable, le type réglé à la main est marqué ✎. La fiche d'un
  équipement montre :
  * *Identité*, avec **pourquoi ce type** ;
  * *Réglages* : listes de choix pour le type, les fonctions (`auto` / `force` / `off`) et les
    réglages SNMP, avec la source de chaque valeur ;
  * *Testeur d'OID* : préréglages proposés selon le type, ou n'importe quel OID ;
  * *Voisins*, valeurs *Personnalisées*, *Dernière collecte*.
* **Nœuds** : recherche par MAC, IP, nom DNS, port… ; Entrée explique la position.
* **Rapports** : construire un rapport avec aperçu en direct (données, colonnes, filtres, tri,
  format), l'enregistrer, l'exporter.
* **Liens**, **Extensions** (collecteurs personnalisés), **Collectes**.
* Collecte d'un équipement ou de tout le parc, avec journal en direct. Aucun secret n'est jamais
  affiché.

## Commandes

| Commande | Rôle |
|---|---|
| `init` | Écrire une configuration d'exemple commentée |
| `check [ADDR…] [--quick]` | Par équipement : joignable, identifiant, MIB qui répondent, identité et type, avertissements |
| `discover [--dry-run]` | Identifier les points de départ et explorer les voisins LLDP/CDP sans lire les tables |
| `collect [--device ADDR]` | Interroger les équipements et mettre l'état à jour |
| `export [--only …]` | Écrire `devices.csv`, `nodes.csv`, `links.csv`, `snapshot.json`, les cartes |
| `push [--target] [--file] [--wait] [--dry-run]` | Envoyer les fichiers exportés |
| `run [--no-collect] [--no-push] [--wait]` | Collecte, export et push d'un coup |
| `show devices\|nodes\|links\|runs [--filter]` | Consulter l'état |
| `explain <mac\|ip>` | Pourquoi une MAC est sur un port (observations, uplinks écartés, transit, ARP) |
| `probe ADDR [PRÉRÉGLAGE\|OID…]` | Tester des OID à la main (préréglages proposés selon le type) |
| `device show\|set\|unset\|add\|remove\|export-settings\|import-settings` | Réglages manuels |
| `custom list\|show\|test\|export\|import\|delete` | Collecteurs personnalisés (OID en plus) |
| `report list\|fields\|show\|preview\|run\|export\|import\|delete` | Rapports personnalisés (CSV, JSON, Markdown, HTML ; SQL en lecture seule) |
| `hooks list\|test` | Programmes externes lancés après collecte, export, push, rapport |
| `oui-update [--from-file DIR]` | Mettre à jour la base des constructeurs IEEE |
| `cron print [--format crontab\|cron.d\|supercronic]` | Lignes de planification issues de `schedule:` |
| `health [--max-age]` | Code 1 si la dernière collecte réussie est trop ancienne |
| `tui` | Interface en terminal |

Toutes les commandes acceptent `--json` (scripts), `--config`, `--log-level`, `--log-file`, `-q`.
Les journaux vont sur stderr. Codes de sortie : **0** OK, **1** échec partiel, **2** erreur de
configuration, **3** état verrouillé par une autre exécution.

## Sorties

| Fichier | Contenu |
|---|---|
| `devices.csv` | Un équipement par ligne ; `Device Name` est la clé de jointure |
| `nodes.csv` | Une ligne par (MAC, position), la plus récente d'abord ; `Switch` = un `Device Name` |
| `links.csv` | Une ligne par lien physique (`LLDP`, `CDP`, `LLDP+CDP`) |
| `snapshot.json` | Tout, avec un schéma versionné, pour les scripts |
| `map.dot`, `map.mmd`, `map.html` | Graphviz, Mermaid, et une page interactive hors ligne |

Colonne par colonne : [docs/formats.md](docs/formats.md). Toutes les heures sont en UTC ; un CSV
vide n'écrase jamais le précédent et n'est jamais poussé.

## Personnaliser

Lire d'autres OID sans écrire de code : créez un collecteur personnalisé depuis le testeur d'OID,
ou dans `extensions/*.yml`. Les valeurs peuvent compléter des champs standard comme la version
du système.

Construire ses propres rapports : un jeu de données (équipements, interfaces, nœuds, historique
IP, VLAN, liens, voisins, collectes, valeurs personnalisées), des colonnes, des filtres et un tri,
ou une requête SQL en lecture seule ; en CSV, JSON, Markdown ou page HTML autonome, à la demande,
planifié ou envoyé vers une cible.

Pour le reste, les extensions Python ajoutent des collecteurs, des jeux de données et des
exports via une petite API en lecture seule (avec un harnais de test), et les hooks lancent vos
propres programmes après une collecte, un export, un push ou un rapport. Voir
[docs/extensions.md](docs/extensions.md) et
[examples/extensions](examples/extensions/).

## Documentation

La documentation détaillée est en anglais :

* [Référence de configuration](docs/config.md), avec chaque clé et sa valeur par défaut
* [Formats de sortie et push HTTP](docs/formats.md)
* [Déploiement : pipx + cron/systemd, Docker Compose](docs/deployment.md)
* [Dépannage et notes par constructeur](docs/troubleshooting.md)
* [Extensions](docs/extensions.md)
* [Notes de conception](DESIGN.md) (en français)

## Sécurité

* Lecture seule par construction : aucun chemin de code SNMP SET, aucun shell. Le seul
  processus jamais lancé est un hook que vous configurez (liste d'arguments, délai,
  environnement nettoyé) ; les extensions Python ne sont chargées que si elles sont nommées.
* Secrets uniquement dans des fichiers ou des variables d'environnement. Le YAML les refuse, les
  journaux les masquent, et l'état ne garde que le nom des identifiants.
* SNMPv3 authPriv recommandé (`check` signale le v2c) ; TLS vérifié par défaut pour le push,
  redirections refusées.
* Délais partout ; le conteneur tourne en non-root, système de fichiers en lecture seule, sans
  aucune capacité.

## Développement

```bash
uv venv --python 3.13 && uv pip install -e ".[dev]"
.venv/bin/python -m pytest          # tests unitaires et d'intégration (simulateurs SNMP sur 127.0.0.x)
.venv/bin/ruff check src tests
docker compose --profile test run --rm tests
python -m tests.support.lab         # un labo local d'équipements simulés, affiche une configuration
```

## Licence

Apache-2.0 — voir [LICENSE](LICENSE) et [NOTICE](NOTICE). Fourni « tel quel », sans garantie ni
responsabilité.
