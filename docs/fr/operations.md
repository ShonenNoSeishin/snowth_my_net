# Le faire tourner

Comment la pile Docker est organisée, quelles commandes taper chaque jour, comment faire prendre
en compte un changement, comment mettre à jour et comment sauvegarder. L'installation elle-même
est dans la [prise en main](getting-started.md), le réseau et le durcissement dans le
[déploiement](deployment.md).

## Qui est où

```text
snowth_my_net/
├── .env                    ports, utilisateur, fuseau, noms TLS   à vous, ignoré par git
├── compose.yml             la pile — jamais modifié, donc git pull ne rentre jamais en conflit
├── compose.override.yml    tout le reste à changer                à vous, ignoré par git
├── config/
│   ├── snowth_my_net.yml   votre configuration                    à vous, ignoré par git
│   └── extensions/         collecteurs et rapports personnalisés  à vous, ignoré par git
├── secrets/                un fichier par secret, chmod 600       à vous, ignoré par git
├── data/                   l'état, voir plus bas                  ignoré par git
└── output/                 les fichiers exportés                  ignoré par git
```

| Fichier de `data/` | Ce qu'il contient | S'il est supprimé |
|---|---|---|
| `state.sqlite` | l'inventaire — équipements, observations MAC et ARP, liens, collectes — **et ce que vous y réglez à la main** : réglages par équipement (`device set`), collecteurs et rapports construits dans l'interface en terminal | la prochaine collecte reconstruit l'inventaire, pas les réglages faits à la main |
| `node_names.json` | les noms et descriptions donnés aux adresses MAC | les noms sont perdus |
| `web_accounts.json` | les empreintes des mots de passe des comptes web | les mots de passe sont perdus ; de nouveaux mots de passe de première connexion sont inventés et écrits dans le journal |
| `oui.tsv.gz` | la base des constructeurs récupérée par `oui-update` | la copie intégrée à l'outil est de nouveau utilisée |
| `state.lock` | le verrou qui ne laisse entrer qu'un seul écrivain à la fois | rien |

## Les services

| Service | Ce qu'il fait | Accessible par |
|---|---|---|
| `snowth` | le planificateur : collecte toutes les dix minutes, exporte deux fois par jour | rien n'est publié |
| `web` | l'interface web | uniquement à travers `nginx` |
| `nginx` | termine le TLS devant l'interface | `https://<host>:8443`, et `http://<host>:8080` qui y redirige |

`sim-access`, `sim-cisco`, `fakepush` et `tests` appartiennent au profil de test et ne démarrent
jamais seuls.

## Commandes de tous les jours

```bash
docker compose ps                                  # ce qui tourne, et s'il est en bonne santé
docker compose logs -f snowth                      # suivre le planificateur
docker compose logs --tail=50 web                  # l'interface ; un mot de passe de première connexion est ici
docker compose exec web snowth_my_net <commande>   # n'importe quelle commande, voir commands.md
docker compose exec -it web snowth_my_net tui      # l'interface en terminal demande -it
docker compose restart web                         # après un changement de configuration
docker compose up -d --build                       # après un git pull
docker compose down                                # supprimer les conteneurs ; data/ reste
```

`snowth` et `web` font tourner la même image sur la même configuration, le même état et la même
sortie : tapez les commandes dans l'un ou l'autre. Une commande qui écrit prend le verrou de
l'état, donc un `collect` manuel attend jusqu'à une minute si une collecte planifiée tourne
(`general.lock_wait`), et les autres commandes jusqu'à un quart d'heure.

## Faire prendre en compte un changement

Une tâche planifiée est un nouveau processus à chaque fois, donc elle relit la configuration. Le
serveur web la lit une seule fois, à son démarrage, et le planificateur construit sa crontab une
seule fois, au démarrage de son conteneur. C'est toute la règle ; la voici selon ce que vous avez
changé.

| Ce que vous avez changé | Quoi faire | Pourquoi |
|---|---|---|
| une clé de `config/snowth_my_net.yml` | rien pour le planificateur, `docker compose restart web` pour l'interface | chaque tâche relit le fichier ; le serveur web le lit au démarrage |
| `schedule:` | `docker compose restart snowth` | la crontab est générée au démarrage du conteneur |
| un fichier de `secrets/` | rien pour le planificateur ; redémarrer `web` si c'est un fichier de mot de passe web | les tâches lisent les secrets quand elles tournent |
| un fichier de `config/extensions/` | rien pour le planificateur, `docker compose restart web` | comme la configuration |
| un nom ou une description, depuis le tableau ou `node name` | rien | relu à chaque requête |
| un mot de passe web, depuis la page ou `web passwd` | rien | relu à chaque connexion |
| `.env` | `docker compose up -d` | Compose recrée les services dont les réglages ont changé |
| `SNOWTH_TLS_HOSTS`, après le premier démarrage | `docker compose down`, `docker volume rm snowth_my_net_certs_web`, `docker compose up -d` | le certificat est fait une fois et conservé |
| `compose.override.yml` | `docker compose up -d` | comme `.env` |
| l'outil lui-même, après un `git pull` | `docker compose up -d --build` | l'image est reconstruite |

Vérifiez une configuration avant de redémarrer quoi que ce soit. `cron print` charge tout le
fichier et refuse une faute de frappe en proposant la bonne clé ; `check` va plus loin et
interroge chaque équipement :

```bash
docker compose exec snowth snowth_my_net cron print
docker compose exec snowth snowth_my_net check
```

## Mettre à jour

```bash
cd ~/snowth_my_net
git pull
docker compose up -d --build
docker compose exec web snowth_my_net collect      # la première écriture met l'état à niveau si besoin
```

* Rien de ce qui est à vous n'est écrasé : `.env`, `config/`, `secrets/`, `data/`, `output/` et
  `compose.override.yml` ne sont pas suivis par git.
* Une nouvelle version peut mettre à niveau le schéma de l'état la première fois que quelque
  chose y écrit. D'ici là, l'interface web répond *503* : elle refuse de lire un état plus ancien
  qu'elle. La prochaine collecte planifiée le fait, ou lancez `collect` vous-même.
* **La mise à niveau ne va que dans un sens.** Une version plus ancienne refuse un état plus
  récent. Pour revenir en arrière, restaurez une sauvegarde de `data/` faite avant la mise à jour.
* Si `git pull` se plaint de modifications locales de `compose.yml`, ce fichier a été modifié
  alors qu'il ne doit pas l'être : déplacez le changement dans `compose.override.yml` et lancez
  `git checkout -- compose.yml`.

## Sauvegarder et restaurer

| À garder | Pourquoi |
|---|---|
| `config/` et `secrets/` | votre configuration et les valeurs vers lesquelles elle pointe : la seule partie qui ne se reconstruit pas |
| `data/node_names.json` | les noms et descriptions écrits à la main |
| `data/web_accounts.json` | les mots de passe web |
| `data/state.sqlite` | l'inventaire et ses 30 jours d'historique, plus les réglages faits à la main |
| `.env`, `compose.override.yml` | vos réglages Compose |

L'état fonctionne en mode WAL : un fichier copié pendant qu'une collecte écrit peut être
incohérent. L'appel `backup()` de SQLite prend un instantané cohérent pendant que tout continue
de tourner :

```bash
docker compose exec -T snowth python -c "import sqlite3; s = sqlite3.connect('/var/lib/snowth_my_net/state.sqlite'); d = sqlite3.connect('/var/lib/snowth_my_net/state.backup.sqlite'); s.backup(d)"
tar czf snowth-backup-$(date +%F).tgz config secrets .env data/node_names.json data/web_accounts.json data/state.backup.sqlite
```

Pour restaurer, arrêtez tout, remettez les fichiers, et supprimez les fichiers d'écriture
anticipée de l'état que vous remplacez — ils appartiennent à l'ancienne base et corrompraient la
base restaurée :

```bash
docker compose down
tar xzf snowth-backup-2026-10-05.tgz
mv data/state.backup.sqlite data/state.sqlite
rm -f data/state.sqlite-wal data/state.sqlite-shm
docker compose up -d
```

## Repartir de zéro

| Je veux | Commande | Ce que ça perd |
|---|---|---|
| oublier toutes les observations MAC et ARP et garder le reste | `node reset --yes` | les 30 jours de mémoire ; équipements, liens, noms et réglages restent |
| redemander le DNS | `dns flush` | les noms en cache ; `--misses-only` garde ceux déjà trouvés |
| repartir d'un inventaire vide | arrêter, supprimer `data/state.sqlite*`, démarrer | équipements, observations, collectes **et les réglages faits à la main** — exportez-les d'abord avec `device export-settings`, `custom export` et `report export` |
| oublier tous les mots de passe web | supprimer `data/web_accounts.json`, `docker compose restart web` | les mots de passe ; de nouveaux sont inventés et journalisés |

## Sans Docker

Avec pipx et cron ou systemd, chaque commande d'ici est la même sans le `docker compose exec web`
devant, et les fichiers sont là où `general.state_dir`, `general.output_dir` et
`general.secrets_dir` le disent. Voir le [déploiement](deployment.md).
