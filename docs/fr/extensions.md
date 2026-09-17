# Extensions

snowth_my_net peut lire davantage que les MIB standard sans toucher à son code. Tout reste en
lecture seule (GET/GETNEXT/GETBULK, mêmes délais et même cadence), et une extension ne fait
qu'**ajouter** des données : elle ne désactive jamais une collecte standard.

## Collecteurs personnalisés (OID en plus)

Un collecteur dit quoi lire, sur quels équipements, et comment interpréter les valeurs. Deux
façons d'en créer un :

1. **Depuis l'interface en terminal :** équipement → *Testeur d'OID* → tester un préréglage ou un
   OID → *Enregistrer comme OID personnalisé* → choisir un nom, la façon d'interpréter la valeur,
   et où la lire (cet équipement, ce constructeur, ce type, tous les équipements). Il est lu à la
   collecte suivante.
2. **En YAML :** des fichiers `*.yml` dans `general.extensions_dir` (par défaut : `extensions/` à
   côté du fichier de configuration ; `config/extensions/` avec Docker). Un fichier invalide est
   une erreur de configuration (code 2) qui cite le fichier. Partez de
   [`examples/extensions/examples.yml`](../../examples/extensions/examples.yml).

```yaml
version: 1
collectors:
  - name: fortigate-version              # minuscules, chiffres, - et _
    description: FortiOS version
    applies_to:                          # tous les critères doivent correspondre ; omis = partout
      vendors: [Fortinet]
      # types: [firewall]
      # addresses: [192.0.2.0/24]
      # sys_object_ids: [1.3.6.1.4.1.12356.101.1]
    get:                                 # des scalaires…
      version: {oid: 1.3.6.1.4.1.12356.101.4.1.1.0, type: text}
    fills: {os_version: version}         # compléter un champ standard vide
    # fill_override: true                # …même s'il n'est pas vide
    every: 6h                            # par défaut : à chaque collecte
    # mode: force                        # aucune valeur = erreur (code 1)

  - name: poe-ports
    applies_to: {types: [switch]}
    walk:                                # …ou des tables (colonnes alignées par index)
      index: raw                         # ou "port" quand l'index est un ifIndex
      columns:
        detection: {oid: 1.3.6.1.2.1.105.1.1.1.6, type: enum,
                    values: {1: disabled, 2: searching, 3: delivering, 4: fault}}
    limit: 10000                         # lignes par colonne
```

**Types de valeur :** `auto` (par défaut : texte, MAC, nombre ou hexadécimal, deviné), `text`,
`integer` (avec `scale` et `unit`), `enum` (`values`), `bits` (`values` = numéro de bit → nom),
`mac`, `ip`, `hex`, `oid`, `timeticks`, `lldp_caps`.

**Champs complétables :** `os_name`, `os_version`, `model`, `serial`, `location`, `device_type`
(l'un des types d'équipement ; la règle du type devient `custom`).

### Commandes

```bash
snowth_my_net custom list                          # collecteurs et leur origine
snowth_my_net custom test fortigate-version 192.0.2.1   # exécuter maintenant sur un équipement, rien n'est stocké
snowth_my_net custom show 192.0.2.1                # valeurs lues à la dernière collecte
snowth_my_net custom export > extensions/from-tui.yml   # collecteurs créés dans l'interface
snowth_my_net custom import extensions/from-tui.yml
snowth_my_net custom delete fortigate-version      # seulement pour les collecteurs créés dans l'interface
```

`check` exécute les collecteurs qui s'appliquent à chaque équipement, et `snapshot.json` contient
les valeurs sous `devices[].custom`.

## Rapports personnalisés

Un rapport transforme l'état en un fichier de votre choix : un **jeu de données**, les
**colonnes** voulues, des **filtres**, un **tri** et un **format** (CSV, JSON, Markdown, ou une
page HTML autonome qui trie et filtre dans le navigateur). Quand les filtres ne suffisent pas, un
rapport peut être une **requête SQL en lecture seule** sur les mêmes jeux de données. Les rapports
n'écrivent jamais dans l'état et ne parlent jamais aux équipements : ils peuvent tourner à tout
moment, même pendant une collecte.

Deux façons d'en créer un :

1. **Depuis l'interface en terminal :** onglet *Rapports* → `n`. Choisissez les données, cochez
   les colonnes, ajoutez des filtres, tapez le tri, et regardez l'aperçu se mettre à jour au fur
   et à mesure. `ctrl+s` l'enregistre (dans l'état), `ctrl+e` écrit le fichier tout de suite. Dans
   la liste, `x` exporte un rapport, `suppr` (`del`) supprime un rapport créé dans l'interface.
2. **En YAML :** une liste `reports:` dans les mêmes fichiers `extensions/*.yml` que les
   collecteurs. Partez de [`examples/extensions/reports.yml`](../../examples/extensions/reports.yml).

```yaml
version: 1
reports:
  - name: stale-nodes                    # minuscules, chiffres, - et _
    title: Nodes not seen for a week     # optionnel, utilisé par Markdown/HTML/JSON
    description: To clean the IPAM       # optionnel
    dataset: nodes                       # voir « Jeux de données » plus bas
    columns:                             # par défaut : les colonnes par défaut du jeu
      - mac
      - ip
      - {field: last_seen, label: Last Seen}   # renommer une colonne
    filters:                             # tous doivent correspondre
      - {field: current, op: eq, value: true}
      - {field: last_seen, op: older_than, value: 7d}
    sort: [last_seen, -ip]               # "-" = décroissant ; valeurs vides toujours en dernier
    limit: 500                           # optionnel
    format: csv                          # csv | json | markdown | html
    output: reports/stale-nodes.csv      # optionnel, relatif à general.output_dir
    schedule: "0 7 * * 1"                # optionnel : une ligne dans "cron print"
    push: [cmdb]                         # optionnel : cibles de push.targets
    allow_empty: true                    # false par défaut : un rapport vide n'est pas écrit
```

Le fichier par défaut est `output/reports/<name>.<csv|json|md|html>`, écrit de façon atomique. Les
fichiers CSV suivent `export.csv.line_terminator` ; les valeurs sont celles des exports standard
(heures UTC au format `2026-09-17T10:00:00Z`, noms d'équipements comme dans `devices.csv`).

### Jeux de données

`snowth_my_net report fields` les liste, `snowth_my_net report fields <dataset>` liste les champs
avec leur type et s'ils sont affichés par défaut.

| Jeu de données | Une ligne par |
|---|---|
| `devices` | équipement dans la fenêtre de rétention (comme `devices.csv`, plus règle et raison du type, sysObjectID, nom de l'identifiant, uptime, nombres d'interfaces, dernière collecte…) |
| `interfaces` | interface : nom du port, alias, état, vitesse, PVID, rôle (`access`/`uplink`, tel qu'utilisé pour `nodes.csv`) et pourquoi, nombre de MAC, voisins LLDP/CDP |
| `nodes` | position d'un nœud (comme `nodes.csv`), plus `current`, verdict, MAC aléatoire, nombre d'IP |
| `ip_history` | adresse IP vue pour un nœud, avec `current` et `superseded_by` |
| `vlans` | VLAN déclaré sur un équipement |
| `links` | lien (comme `links.csv`, extrémités incluses, avec `endpoint`) |
| `neighbors` | voisin LLDP/CDP actuel tel qu'annoncé, rattaché ou non à un équipement géré |
| `runs` | exécution (collecte, export…), avec durée et nombres d'équipements |
| `custom` | valeur de n'importe quel collecteur personnalisé (équipement, collecteur, index, colonne, valeur) |
| `custom:<collector>` | équipement (`get:`) ou ligne de table (`walk:`) d'un collecteur, une colonne par valeur |

### Filtres

Les types de champ sont `text`, `integer`, `time` et `bool`. Les comparaisons de texte ignorent
la casse. Une comparaison ne correspond jamais à une valeur vide : utilisez `empty` / `not_empty`
pour celles-ci.

| `op` | Valeur | Signification |
|---|---|---|
| `eq`, `ne` | une valeur | égal / différent (`ne` garde aussi les valeurs vides) |
| `contains`, `not_contains`, `startswith`, `endswith` | texte | tests de sous-chaîne |
| `regex` | expression régulière | syntaxe Python, insensible à la casse |
| `gt`, `ge`, `lt`, `le` | nombre, ou date pour les heures (`2026-09-01`, `2026-09-01T10:00:00Z`) | comparaisons |
| `in`, `not_in` | liste | parmi / aucun de |
| `empty`, `not_empty` | — | pas de valeur / une valeur |
| `older_than`, `newer_than` | durée (`30m`, `12h`, `7d`) | champs d'heure seulement, par rapport à maintenant |

Les booléens acceptent `true`/`false` (et aussi `yes`/`no`).

### Rapports SQL

```yaml
  - name: vendors-per-switch
    sql: >
      SELECT device, vendor, count(*) AS nodes, iso(max(last_seen)) AS last_seen
      FROM nodes WHERE current AND device <> ''
      GROUP BY device, vendor ORDER BY device, nodes DESC
    format: json
```

* Chaque jeu de données est une table du même nom (`custom:poe-ports` devient
  `custom_poe_ports`). Les heures sont des entiers (secondes depuis 1970, UTC), les booléens
  valent 0/1.
* Fonctions : `iso(time)` formate une heure, `age_days(time)` donne son âge en jours, `now()` est
  l'heure actuelle.
* La requête tourne dans une base SQLite privée en mémoire qui contient des copies des jeux de
  données qu'elle nomme, jamais sur le fichier d'état. Un seul `SELECT` (ou `WITH … SELECT`) est
  accepté ; un autorisateur refuse tout le reste (`ATTACH`, `PRAGMA`, écritures, chargement
  d'extensions), et une requête est arrêtée après 20 secondes ; un résultat de plus de 200 000 lignes est refusé (ajoutez un `LIMIT`).
* `columns`, `filters` et `sort` ne s'appliquent pas : écrivez-les dans la requête.

### Commandes

```bash
snowth_my_net report list                        # rapports, source, format, planification, origine
snowth_my_net report fields [DATASET]            # les jeux de données, ou les champs de l'un d'eux
snowth_my_net report show stale-nodes            # la définition, en YAML
snowth_my_net report preview stale-nodes         # premières lignes dans le terminal (--limit N)
snowth_my_net report run stale-nodes [--format html] [--output FILE|-] [--no-push]
snowth_my_net report run --all                   # tous les rapports
snowth_my_net report export > extensions/from-tui.yml   # rapports créés dans l'interface
snowth_my_net report import extensions/from-tui.yml
snowth_my_net report delete stale-nodes          # seulement pour les rapports créés dans l'interface
```

Rapports ponctuels, pratiques dans des scripts (le résultat va sur stdout sauf si `--output` est
donné) :

```bash
snowth_my_net report run --dataset interfaces --columns device,port,mac_count \
    --filter "role eq access" --filter "mac_count gt 1" --sort=-mac_count --format csv
snowth_my_net report preview --sql "SELECT vendor, count(*) FROM devices GROUP BY vendor"
```

Écrivez `--sort=-field` avec un signe égal quand le premier champ est décroissant ; sinon
l'analyseur de la ligne de commande prend `-field` pour une option.

**Codes de sortie :** 0 quand chaque rapport a été écrit (et poussé), 1 quand l'un d'eux était
vide (sans `allow_empty`), invalide à l'exécution, ou n'a pas pu être poussé, 2 pour une erreur de
définition.

### Planification et push

* `schedule:` ajoute `report run <name>` à `snowth_my_net cron print`, que le rapport vienne d'un
  fichier ou de l'interface. Régénérez la crontab après avoir ajouté ou modifié une planification
  (avec Docker Compose, redémarrez le service `snowth` : le point d'entrée la régénère).
* `push:` envoie le fichier écrit vers des cibles de push, avec leurs règles d'authentification,
  de TLS et de nouvelles tentatives ; le résultat nomme le fichier `report:<name>`.
  `report run --target NAME` pousse vers une autre cible, `--no-push` saute l'envoi, `--dry-run`
  montre ce qui serait envoyé.
* `check` signale les rapports qui nomment une cible de push inconnue.

## Extensions Python

Pour ce qu'une déclaration ne peut pas exprimer : combiner plusieurs OID, calculer des valeurs,
lire un inventaire externe, produire un fichier dans un autre format. Une extension est un fichier
Python dans le répertoire des extensions, ou un paquet installé, et n'est chargée **que si son nom
est listé** :

```yaml
general:
  python_extensions: [host_storage]      # extensions/host_storage.py, ou un point d'entrée
```

Une extension tourne dans snowth_my_net, avec ses droits : n'activez que du code de confiance.
Elle reçoit le même accès SNMP en lecture seule que tout le reste (`get` et `walk`), avec les
identifiants, les délais et la cadence de l'équipement, mais rien n'empêche techniquement du code
Python de faire autre chose.

```python
from snowth_my_net.api import Extension, Field, text

extension = Extension("host_storage")              # au niveau du module, obligatoire

@extension.collector("host-storage", table=True,
                     columns=["kind", "description", "used_pct"],
                     applies_to={"sys_object_ids": ["1.3.6.1.4.1.8072.3.2"]}, every="1h")
async def host_storage(device, snmp):
    rows = []
    for index, descr in await snmp.walk("1.3.6.1.2.1.25.2.3.1.3"):
        rows.append({"index": index, "description": text(descr)})
    return rows

@extension.report_dataset("disk-usage", fields=[Field("device"), Field("used_pct", "integer")])
def disk_usage(ctx):
    return [{"device": r["device"], "used_pct": int(r["used_pct"] or 0)}
            for r in ctx.dataset_rows("custom:host-storage")]

@extension.exporter("metrics/snowth_my_net.prom")
def prometheus(snapshot):
    return f"snowth_devices {len(snapshot['devices'])}\n".encode()
```

Un exemple complet et testé : [`examples/extensions/host_storage.py`](../../examples/extensions/host_storage.py)
(occupation disque des hôtes net-snmp, un jeu de données typé, un export au format textfile de
Prometheus).

### Points d'extension

| Décorateur | Fonction | Résultat |
|---|---|---|
| `collector(name, columns=[…], table=False, index="raw", applies_to={…}, every=0, mode="auto", fills={…}, description="", limit=10000)` | `async def f(device, snmp)` qui renvoie un dict des `columns`, ou avec `table=True` une liste de dicts avec une clé `index` (`index="port"` quand c'est un ifIndex) | Stocké comme un collecteur YAML : fiche de l'équipement, `custom show`, `snapshot.json`, jeu de données `custom:<name>`, `fills` des champs standard. |
| `report_dataset(name, fields=[Field(…)], description="")` | `def f(ctx)` qui renvoie une liste de dicts | Jeu de données `py:<name>` pour les rapports (table SQL `py_<name>`). `ctx.now` est l'heure actuelle, `ctx.dataset_rows("devices")` donne un autre jeu de données, `ctx.config_dir` le répertoire de configuration. |
| `exporter(filename, description="")` | `def f(snapshot)` qui renvoie des octets (ou du texte) | Écrit de façon atomique sous le répertoire de sortie par `export` (pas avec `--only`). |
| `driver(name, object_ids=[…], description="")` puis `@drv.identity` / `@drv.observations` | `async def f(device, snmp)` qui renvoie un dict (`model`, `serial`, `os_name`, `os_version`) / `Observations(stations, arp, access_points)` | Un driver constructeur, essayé avant les drivers intégrés ; voir [drivers](drivers.md#écrire-un-driver). |

`device` est un `DeviceView` (`address`, `name`, `vendor`, `model`, `os_name`, `os_version`,
`device_type`, `object_id`). `snmp.get("oid", …)` renvoie `{oid: value}` ; `snmp.walk("oid")`
renvoie `[(index, value)]`, l'index étant relatif à l'OID parcouru. Les valeurs sont des `bytes`
(OCTET STRING), des `int` (entiers, compteurs, timeticks), des `str` (OID, adresses) ou `None`
(objet inexistant) ; `text()`, `number()`, `mac()` et `ip()` les convertissent.

Un collecteur qui lève une exception, ou qui renvoie autre chose que ce qu'il déclare, est
enregistré comme une erreur pour cet équipement, comme une erreur SNMP : l'équipement est
`partial` et la collecte sort avec le code 1 (sauf `devices[].tolerate_failure`) ; il n'arrête jamais la collecte. Un jeu de
données qui lève une exception fait échouer le rapport ; un export qui lève une exception est
signalé par `export` (code de sortie 1) et les autres fichiers sont quand même écrits.

**Chargement :** `<extensions_dir>/<name>.py` d'abord, puis une distribution installée qui
déclare le point d'entrée `snowth_my_net.extensions`, par exemple dans son `pyproject.toml` :

```toml
[project.entry-points."snowth_my_net.extensions"]
acme = "acme_snowth.extension:extension"
```

Une erreur d'import, l'absence d'un `extension` au niveau du module, un nom déjà utilisé par un
autre collecteur, ou une extension écrite pour une autre version de l'API est une erreur de
configuration (code 2) qui cite l'extension. L'API est versionnée
(`snowth_my_net.api.API_VERSION`, actuellement 1).

### Tester une extension

`snowth_my_net.testing` exécute le code d'une extension sans équipement ni état :

```python
from snowth_my_net import testing

ext = testing.load("extensions/host_storage.py")
snmp = testing.FakeSnmp({"1.3.6.1.2.1.25.2.3.1.3.31": b"/", "1.3.6.1.2.1.25.2.3.1.6.31": 42})
rows = testing.run_collector(ext, "host-storage", snmp, vendor="Linux")   # valeurs stockées
usage = testing.run_dataset(ext, "disk-usage", {"custom:host-storage": rows})
data = testing.export(ext, "metrics/snowth_my_net.prom", {"devices": [], "nodes": []})
```

Un driver déclaré par une extension (voir [drivers](drivers.md#écrire-un-driver)) se teste de la
même façon : `identity, observations = testing.run_driver(ext, "acme-os", snmp)`.

Ensuite, sur un vrai équipement et sans rien stocker : `snowth_my_net custom test host-storage
192.0.2.16`.

## Hooks

Les hooks lancent des programmes externes après `collect`, `export`, `push` ou un rapport, dans
n'importe quel langage :

```yaml
hooks:
  after_export:
    - name: publish
      command: [/usr/local/bin/publish-inventory, --devices, "{devices}", --nodes, "{nodes}"]
      timeout: 120
  after_collect:
    - name: alert
      when: failed                      # seulement si la collecte est partielle ou en échec
      command: [/usr/local/bin/notify, "collect {status}", "{summary}"]
      pass_env: [HTTPS_PROXY]
  after_report:
    - name: mail-report
      command: [/usr/local/bin/mail-file, "{report_file}"]
```

Comment ils s'exécutent, par conception :

* **Pas de shell.** `command` est une liste ; les champs sont remplacés à l'intérieur de chaque
  argument, si bien qu'une valeur ne peut jamais ajouter d'arguments ni de syntaxe shell. Les
  tubes ou redirections demandent un script à vous.
* **Un délai** (60 s par défaut), après lequel tout le groupe de processus est terminé.
* **Un environnement propre :** `PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin`,
  `LANG=C.UTF-8`, `HOME` = le répertoire d'état, `TZ` s'il est défini, les valeurs de `env:`, les
  variables nommées dans `pass_env:`, et :

  | Variable | Contenu |
  |---|---|
  | `SNOWTH_EVENT` | `after_collect`, `after_export`, `after_push` ou `after_report` |
  | `SNOWTH_STATUS` | `ok`, `partial` ou `failed` |
  | `SNOWTH_RUN_ID` | l'identifiant d'exécution de la collecte (vide sinon) |
  | `SNOWTH_OUTPUT_DIR` | le répertoire de sortie (aussi le répertoire de travail) |
  | `SNOWTH_SUMMARY` | un fichier JSON qui décrit l'étape : le rapport de collecte, les fichiers écrits et en échec, les résultats du push, ou le nom, le chemin et le nombre de lignes du rapport |

  Les secrets lus par snowth_my_net (communautés, clés, jetons) ne sont jamais transmis.
* **Après la libération du verrou de l'état**, si bien qu'un hook peut lui-même appeler
  snowth_my_net. Dans `run`, les hooks des trois étapes s'exécutent à la fin, dans l'ordre.
* **Les échecs sont signalés, jamais bloquants :** un hook qui sort avec un code non nul ou
  dépasse son délai fait sortir la commande avec le code 1 (la fin de son stderr est journalisée
  et figure dans `--json`) ; les autres hooks s'exécutent quand même, les fichiers déjà écrits
  restent.
* Les hooks ne s'exécutent pas pour les collectes lancées depuis l'interface en terminal, pour
  `--dry-run`, pour les rapports envoyés sur stdout, ni avec `--no-hooks`.

```bash
snowth_my_net hooks list
snowth_my_net hooks test after_export              # les exécuter maintenant avec un résumé de test
snowth_my_net hooks test after_export publish --dry-run   # afficher seulement la commande
```

`check` signale les programmes introuvables (utilisez des chemins absolus : le PATH de cron est
court) et les variables de `pass_env` qui contiennent un secret de la configuration.

Dans le conteneur, les hooks tournent sous l'utilisateur non privilégié `snowth`, sur un système
de fichiers en lecture seule : montez les scripts (en lecture seule) et assurez-vous qu'ils n'ont
besoin que du répertoire de sortie ou de `/tmp`.
