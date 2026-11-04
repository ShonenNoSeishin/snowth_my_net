# Prise en main : déclarer vos équipements et lancer un scan

Suivez les étapes dans l'ordre. Chacune se termine par une commande qui vous dit si vous pouvez
passer à la suivante. Rien ici n'écrit sur un équipement : snowth_my_net n'envoie que des
lectures SNMP.

## 1. Installer

```bash
pipx install git+https://github.com/ShonenNoSeishin/snowth_my_net.git
snowth_my_net version
```

Avec Docker Compose à la place, voir le [déploiement](deployment.md#2-docker-compose) ; chaque
commande ci-dessous devient `docker compose run --rm snowth <commande>`.

## 2. Créer la configuration

```bash
snowth_my_net init -o snowth_my_net.yml
```

Le fichier est commenté et chaque clé est listée dans la
[référence de configuration](config.md). Indiquez-le avec `--config snowth_my_net.yml`, ou
définissez `SNOWTH_CONFIG` une fois pour toutes :

```bash
export SNOWTH_CONFIG=$PWD/snowth_my_net.yml
```

## 3. Mettre les secrets SNMP dans des fichiers

Les secrets ne vont jamais dans le YAML : l'outil les y refuse. Écrivez un fichier par secret,
lisible par vous seul (`check` avertit quand un fichier est lisible par le groupe ou par tous).

```bash
mkdir -p secrets && chmod 700 secrets
printf '%s' 'la-clé-d-authentification' > secrets/v3_auth
printf '%s' 'la-clé-de-chiffrement'     > secrets/v3_priv
printf '%s' 'la-communauté-en-lecture'  > secrets/community
chmod 600 secrets/*
```

Une variable d'environnement fonctionne aussi (`community_env: SNMP_COMMUNITY`), c'est ce
qu'utilise le déploiement Docker.

## 4. Déclarer les identifiants

Dans `snowth_my_net.yml`, listez les identifiants que l'outil a le droit d'essayer. `scope`
limite un identifiant à une plage d'adresses, pour qu'une mauvaise communauté ne soit jamais
essayée sur un équipement qui ne l'attend pas (en SNMPv2c, une mauvaise communauté ne répond
rien, ce qui coûte un délai d'attente).

```yaml
general:
  state_dir: ./data
  output_dir: ./output
  secrets_dir: ./secrets           # base des chemins relatifs ci-dessous

credentials:
  - name: v3-main                  # SNMPv3 authPriv : recommandé
    version: 3
    username: snowth
    auth_protocol: sha256
    auth_key_file: v3_auth
    priv_protocol: aes128
    priv_key_file: v3_priv
  - name: v2c-old-switches         # seulement là où v3 n'est pas disponible
    version: 2c
    community_file: community
    scope: [192.0.2.0/24]
```

Côté équipement, l'accès en lecture seule doit être autorisé pour cet utilisateur ou cette
communauté, depuis l'adresse de la machine qui exécute snowth_my_net.

## 5. Déclarer les équipements

Il y a trois façons de faire, et elles se cumulent.

**a. Points de départ et exploration** — la façon habituelle. Donnez quelques équipements bien
connectés (commutateurs de cœur, pare-feu) ; leurs voisins LLDP/CDP sont suivis à l'intérieur
d'`allowed`.

```yaml
discovery:
  seeds: [192.0.2.1, 192.0.2.11, sw-core-01.example.net]
  allowed: [192.0.2.0/24, 198.51.100.0/24]   # rien en dehors n'est jamais interrogé
  exclude: [192.0.2.99]                      # ne jamais interroger celui-ci
  follow_neighbors: true
  max_depth: 3
```

**b. Un équipement à la fois** — ajouté à l'état, conservé d'une exécution à l'autre :

```bash
snowth_my_net device add 192.0.2.42
snowth_my_net device remove 192.0.2.42       # l'oublier, lui et son historique
```

Dans l'interface en terminal (`snowth_my_net tui`), c'est la touche `a` de l'onglet
Équipements, et `suppr` (`del`) retire.

**c. Réglages par équipement** — seulement quand un équipement demande autre chose. Rien ici
n'est nécessaire pour qu'un scan fonctionne :

```yaml
devices:
  - address: 192.0.2.1
    type: firewall                 # seulement si le type automatique est faux ou vide
    features: {arp: force}         # auto | force | off, par fonction
    snmp: {pace_ms: 50}            # ménager un petit processeur
    tolerate_failure: true         # son échec ne doit pas faire échouer toute l'exécution
  - address: 192.0.2.0/24          # une plage : l'entrée la plus précise gagne
    uplinks: [Te1/1/1]
```

## 6. Vérifier avant de scanner

`check` interroge chaque cible une fois et affiche, par équipement : si elle répond, quel
identifiant a fonctionné, quelles MIB ont des lignes, l'identité et le type, plus des
avertissements.

```bash
snowth_my_net check                       # toutes les cibles
snowth_my_net check 192.0.2.1 --quick     # un équipement, une requête par MIB
```

Lisez la ligne `mibs` : `ok(1834)` signifie que la MIB a répondu avec ce nombre de lignes,
`absent` que l'équipement ne sert rien là, `timeout` qu'il n'a pas répondu à temps. Un
équipement qui répond à `system` mais à rien d'autre est en général un identifiant dont la vue
est restreinte.

Pour tester un OID à la main, avec des propositions selon le type d'équipement :

```bash
snowth_my_net probe 192.0.2.1                  # lister les préréglages
snowth_my_net probe 192.0.2.1 arp-media        # un préréglage
snowth_my_net probe 192.0.2.1 1.3.6.1.2.1.1.5.0
```

## 7. Lancer le scan

```bash
snowth_my_net discover        # identité seulement : qui répond, ce que c'est, qui sont ses voisins
snowth_my_net collect         # le vrai scan : interfaces, tables MAC, ARP, LLDP/CDP
```

`discover` est le galop d'essai de l'exploration et écrit peu ; `collect` est celui que vous
planifierez. Les deux affichent une ligne par équipement et un résumé. Le code de sortie vaut
**0** quand tout s'est bien passé, **1** quand un équipement ou une fonction a échoué, **2** en
cas d'erreur de configuration, **3** quand une autre exécution tient le verrou de l'état.

Ne scanner qu'un équipement (pratique après avoir changé ses réglages) :

```bash
snowth_my_net collect --device 192.0.2.11
```

## 8. Regarder ce qui a été collecté

```bash
snowth_my_net show devices                 # inventaire, type et comment il a été décidé
snowth_my_net show nodes --filter 192.0.2  # adresses MAC et où elles se trouvent
snowth_my_net show uplinks                 # ports tenus pour des uplinks, et ce que coûte chacun
snowth_my_net show excluded                # MAC que la liste des nœuds écarte, et pourquoi
snowth_my_net show tables                  # ce que chaque table SNMP a rendu, par équipement
snowth_my_net dns check 192.0.2.121       # le résolveur est-il le bon, la zone inverse existe-t-elle ?
snowth_my_net dns probe 192.0.2.121       # demander à l'hôte lui-même : NetBIOS, LLMNR, mDNS
snowth_my_net show links                   # les liens physiques trouvés
snowth_my_net show runs                    # les dernières exécutions et leur état
snowth_my_net explain 00:00:5e:00:53:a0    # pourquoi cette MAC est sur ce port
```

`explain` accepte aussi une adresse IP. Il montre toutes les observations, les ports écartés
comme uplinks ou comme transit, et les entrées ARP derrière l'IP actuelle.

## 9. Produire les fichiers

```bash
snowth_my_net export
```

Il écrit `devices.csv`, `nodes.csv`, `links.csv`, `snapshot.json` et les cartes dans le
répertoire de sortie (voir [formats](formats.md)). Un CSV vide n'écrase jamais le précédent.
Ouvrez `map.html` dans un navigateur : elle fonctionne hors ligne.

## 10. Le répéter automatiquement

Réglez la planification dans la configuration, puis générez les lignes du planificateur :

```yaml
schedule:
  collect: "*/10 * * * *"        # les entrées ARP expirent en quelques minutes
  export_push: "0 11,18 * * *"
```

```bash
snowth_my_net cron print --format cron.d --user snowth | sudo tee /etc/cron.d/snowth_my_net
snowth_my_net health             # sort en 1 quand la dernière collecte réussie est trop ancienne
```

Avec Docker Compose, le planificateur du conteneur lit le même `schedule:` au démarrage.
Détails et unités systemd : [déploiement](deployment.md).

## 11. Travailler au quotidien dans l'interface

```bash
snowth_my_net tui
```

Équipements, Nœuds, Liens, Topologie, Rapports, Extensions et Collectes sont des onglets (et
la fiche d'un équipement a un onglet Ports) ; `?` affiche les touches. Vous pouvez collecter un équipement ou tout le parc avec un journal en direct, régler
un type ou un réglage par équipement à la main, tester un OID et construire un rapport. Aucun
secret n'y est jamais affiché.

## 12. Ou dans un navigateur

```bash
snowth_my_net web                # http://127.0.0.1:8080
```

Les mêmes vues, en lecture seule, avec un filtre et des colonnes triables ; une MAC ouvre son
explication. Détails : [interface web](web.md).

## Si quelque chose ne fonctionne pas

* `check` répond `no answer` : l'identifiant, une ACL sur l'équipement, ou un pare-feu sur le
  chemin.
* Le type est vide : c'est volontaire quand rien ne le prouve ; réglez-le à la main dans
  l'interface ou avec `devices[].type`.
* Une MAC est sur un trunk au lieu de son port d'accès : `explain` montre la règle qui a décidé.

D'autres cas, et les notes par constructeur : [dépannage](troubleshooting.md).
