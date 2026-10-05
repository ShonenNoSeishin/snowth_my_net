# Commandes

Toutes les commandes de `snowth_my_net`, ce qu'elles font et leurs options. Les options viennent
de l'aide du programme lui-même, et un test échoue quand une commande manque dans cette page. Les
clés qu'elles lisent sont dans la [référence de configuration](config.md) ; ce qu'il faut taper
quand quelque chose manque est dans les [diagnostics](diagnostics.md).

## Lancer une commande

Avec Docker Compose, tapez-la dans le conteneur `web` ou `snowth`, qui partagent leurs fichiers :

```bash
docker compose exec web snowth_my_net <commande>        # une commande qui affiche
docker compose exec -T web snowth_my_net <commande>     # dans un tube ou un script : sans terminal
docker compose exec -it web snowth_my_net tui           # l'interface en terminal en demande un
```

Sans Docker, c'est la même commande sans le préfixe. Ces options appartiennent à toutes les
commandes et se placent avant leur nom :

| Option | Effet |
|---|---|
| `-c`, `--config` | le fichier de configuration ; par défaut `$SNOWTH_CONFIG`, `./snowth_my_net.yml`, puis `/etc/snowth_my_net/config.yml` |
| `--state-dir`, `--output-dir` | remplacent `general.state_dir` et `general.output_dir` |
| `--json` | affiche une sortie lisible par une machine sur stdout |
| `--log-level` | `debug`, `info`, `warning` ou `error` |
| `--log-file` | écrit aussi le journal dans ce fichier |
| `-q`, `--quiet` | seulement les avertissements et erreurs sur stderr |

Le code de sortie vaut 0 quand tout s'est bien passé, 1 quand quelque chose a échoué en partie, 2
pour un problème de configuration, 3 quand l'état est verrouillé par un autre écrivain, et 130
quand la commande a été interrompue. Une commande qui écrit attend le verrou de l'état, jusqu'à
`general.lock_wait`.

## Mettre en place

| Commande | Ce qu'elle fait | Options |
|---|---|---|
| `init` | écrit un exemple de configuration commenté | `--output`, `--force` |
| `check` | diagnostique la configuration, les identifiants et la prise en charge des MIB de chaque équipement ; elle les interroge | `--quick` (une requête par MIB), `--save` (retenir les identifiants qui marchent), des adresses |
| `version` | affiche la version | |

## Collecter et exporter

| Commande | Ce qu'elle fait | Options |
|---|---|---|
| `discover` | identifie les équipements, depuis les amorces et le balayage, sans collecter leurs tables | `--device`, `--dry-run` |
| `collect` | interroge chaque équipement et met à jour l'état | `--device` (une adresse), `--no-hooks` |
| `export` | écrit les fichiers CSV, JSON et les cartes | `--only devices,nodes,links,snapshot,map`, `--no-hooks` |
| `push` | envoie les fichiers exportés aux cibles de push | `--target`, `--file`, `--wait`, `--dry-run`, `--no-hooks` |
| `run` | collecte, exporte et pousse d'un seul geste | `--no-collect`, `--no-push`, `--wait`, `--no-hooks` |
| `names ask` | demande son nom à chaque nœud via `names.probe`, réponses mises en cache | `--force` (redemander quoi que dise le cache) |
| `cron print` | affiche les lignes de crontab générées depuis `schedule:` | `--format` (`crontab`, `cron.d`, `supercronic`) |
| `health` | échoue quand la dernière collecte réussie est trop ancienne | `--max-age` (par exemple `30m`) |

## Regarder ce qu'il sait

| Commande | Ce qu'elle fait | Options |
|---|---|---|
| `show devices` | l'inventaire, avec son type et la règle qui l'a décidé | |
| `show nodes` | les adresses MAC et où elles se trouvent | `--limit`, `--filter` |
| `show links` | les liens physiques trouvés en LLDP et CDP | `--filter` |
| `show runs` | les dernières collectes et leur état | `--limit` |
| `show uplinks` | les ports tenus pour des uplinks, par preuve ou par supposition, et les MAC que chacun laisse sans position | `--filter` |
| `show excluded` | les MAC que la liste des nœuds écarte, et pourquoi | `--filter` |
| `show tables` | ce que chaque table SNMP a rendu sur chaque équipement à la dernière collecte | `--filter` |
| `explain` | pourquoi une MAC, ou les MAC d'une IP, sont où elles sont : chaque observation, les ports écartés, les trois noms d'hôte | une MAC ou une IP |
| `tui` | ouvre l'interface de gestion en terminal | |

## Diagnostiquer

| Commande | Ce qu'elle fait | Options |
|---|---|---|
| `probe` | teste des OID à la main sur un équipement : des préréglages, ou des OID numériques | `--get`, `--walk`, `--limit`, `--all` |
| `dns check` | demande une résolution inverse aux résolveurs configurés et dit lequel a répondu | des adresses |
| `dns probe` | demande son nom à un hôte, en NetBIOS, LLMNR et mDNS, et montre chaque réponse | des adresses |

## Changer ce qu'il sait

| Commande | Ce qu'elle fait | Options |
|---|---|---|
| `node name` | donne un nom à une MAC, conservé d'une collecte à l'autre ; sans texte, il est oublié | une MAC, puis le texte |
| `node describe` | donne une description à une MAC | une MAC, puis le texte |
| `node reset` | oublie toutes les observations MAC et ARP ; équipements, liens et noms restent | `--yes` est obligatoire |
| `dns flush` | oublie les résolutions de noms en cache | `--misses-only` garde les noms déjà trouvés |
| `device` | ajoute ou retire une adresse interrogée ; `set`, `unset` et `show` ses réglages ; `export-settings` et `import-settings` les emportent ailleurs | |
| `custom` | collecteurs personnalisés : `list`, `show`, `test`, `import`, `export`, `delete` | |
| `report` | rapports personnalisés : `list`, `fields`, `show`, `preview`, `run`, `export`, `import`, `delete` | |
| `hooks` | programmes lancés après une collecte, un export, un push ou un rapport : `list`, `test` | |

## Servir et entretenir

| Commande | Ce qu'elle fait | Options |
|---|---|---|
| `web` | sert l'interface web | `--bind`, `--port`, `--trusted-proxy`, `--hash-password` (affiche l'empreinte d'un mot de passe, pour un compte dont le mot de passe vit dans un fichier) |
| `web passwd` | règle sur place le mot de passe d'un compte web | le compte, s'il y en a plusieurs |
| `oui-update` | rafraîchit la base des constructeurs depuis l'IEEE | `--from-file` (fichiers CSV récupérés avant) |
