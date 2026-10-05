# Exports

Les fichiers sont ce que lisent les autres outils : un importateur, un script, une personne avec
une carte. Cette page dit à quoi sert chaque fichier, quand il est écrit, quels réglages le
façonnent, et comment alimenter un importateur sans lui importer le passé. La référence colonne
par colonne est dans les [formats](formats.md), chaque clé dans la [référence de
configuration](config.md).

## Les fichiers

| Fichier | Ce qu'il contient | Qui le lit |
|---|---|---|
| `devices.csv` | une ligne par équipement interrogé | un importateur, comme actifs |
| `nodes.csv` | une ligne par adresse MAC et par position | un importateur, comme hôtes et leur emplacement |
| `links.csv` | une ligne par lien physique | un outil de cartographie |
| `snapshot.json` | tout, avec un schéma versionné et les raisons derrière chaque valeur | des scripts |
| `map.html`, `map.dot`, `map.mmd` | une page interactive qui marche hors ligne, Graphviz, Mermaid | des personnes |

Les en-têtes par défaut de `devices.csv` et `nodes.csv` sont ceux que lit le profil `netdisco`
d'Inventory Manager, et ils ne changent pas quand vous mettez à jour. Toutes les heures d'un
fichier sont en UTC.

## Quand ils sont écrits

* **Selon la planification** : `schedule.export_push` (11 h et 18 h par défaut) lance
  `run --no-collect`, et pousse aussi quand des cibles de push sont configurées.
* **À la main** : `export`, ou `export --only devices,nodes` pour un sous-ensemble ; le bouton
  *Exporter* de la page Collectes ; ou `run`, qui collecte, exporte et pousse d'un seul geste.
* **Quels fichiers** : `export.files`, tous par défaut.
* **Jamais un demi-fichier** : un fichier est écrit à côté de sa destination puis renommé à sa
  place, donc un lecteur n'en voit jamais un partiel.
* **Jamais un fichier vide par accident** : un CSV sans ligne de données n'est ni écrit par-dessus
  le précédent ni poussé, sauf s'il est listé dans `export.allow_empty`.
* **Le DNS est interrogé maintenant** : les noms sont résolus à l'export et mis en cache, dans la
  limite de `dns.budget` et `names.budget`. Le premier export après avoir activé l'un des deux
  peut laisser des adresses au suivant.
* **Interroger les hôtes peut être séparé** : `names ask`, planifié avec `schedule.names` ou lancé
  depuis le bouton *Demander les noms*, demande son nom à chaque nœud à part. Avec
  `names.at_export: false`, un export ne fait plus que lire ce qui a déjà été répondu, et reste
  rapide.

## Ce qui façonne nodes.csv

| Clé | Effet | Défaut |
|---|---|---|
| `nodes.positions` | `current` écrit une ligne par MAC avec sa dernière position ; `all` écrit une ligne par position, l'historique d'itinérance | `all` |
| `nodes.retention_days` | les observations plus anciennes sont oubliées | `30` |
| `nodes.uplink_fallback` | une MAC vue seulement derrière des uplinks faibles reçoit le port qui l'a apprise, marquée `behind_uplink` | `false` |
| `nodes.include_unlocated` | garder les lignes qui n'ont ni switch ni port | `true` |
| `nodes.include_link_local_only` | garder les MAC connues seulement par une adresse lien-local | `false` |
| `nodes.elect_link_local` | autoriser une adresse lien-local comme IP d'une ligne | `false` |
| `nodes.current_ip_window` | l'écart maximal à la plus récente pour qu'une autre adresse puisse encore être élue | `86400` |
| `export.nodes.merge_hostnames` | `DNS Name` porte le meilleur des trois noms d'hôte | `true` |
| `export.nodes.include_name`, `export.nodes.include_description` | ajouter une première colonne avec le nom, la description | `false` |
| `dns.strip_domain` | ne garder que la partie hôte d'un nom DNS | `false` |
| `export.csv.line_terminator` | `crlf` (RFC 4180) ou `lf` | `crlf` |

Les deux clés `include_` ajoutent des colonnes *devant* les autres. Un importateur qui lit les
colonnes par leur en-tête n'est pas affecté ; celui qui les lit par position l'est, et c'est
pourquoi elles sont désactivées.

## Les noms d'hôte dans l'export

`DNS Name` porte une seule valeur, choisie dans l'ordre de confiance : le nom écrit à la main,
sinon la résolution inverse, sinon ce que l'hôte a annoncé sur lui-même (`names.probe`). Le CSV
n'a pas la place de dire lequel des trois sans casser l'en-tête qu'attend un importateur, donc
`snapshot.json` l'enregistre pour chaque nœud :

```json
"hostname": { "name": "poste-de-frank", "source": "manual" }
```

Avec `export.nodes.merge_hostnames: false`, `DNS Name` est la résolution inverse seule.

## Alimenter un importateur

Un importateur déduplique ce qu'il reçoit. S'il reçoit trente jours de positions pour une MAC, il
peut en garder n'importe laquelle, y compris un port vieux de trois semaines. Ces réglages
envoient le présent et ne perdent rien de ce qu'un switch non managé cache :

```yaml
nodes:
  positions: current          # une ligne par MAC : sa dernière position, pas son historique
  uplink_fallback: true       # les appareils derrière un switch non managé gardent le port qui les a appris
export:
  nodes:
    merge_hostnames: true     # le meilleur nom d'hôte connu va dans DNS Name
```

Avant d'activer `uplink_fallback`, demandez ce que cela changerait :

```bash
docker compose exec web snowth_my_net show uplinks
```

La dernière ligne compte les MAC qui obtiendraient une position. Une MAC derrière un switch qui
*est* interrogé n'en reçoit jamais ainsi : son vrai port vient de ce switch.

## Pousser

Envoyer les fichiers à un point d'accès HTTP, avec son authentification et son suivi de tâches,
est décrit dans [Push HTTP](formats.md#push-http). En ligne de commande :

```bash
docker compose exec web snowth_my_net push --dry-run              # ce qui serait envoyé, rien n'est envoyé
docker compose exec web snowth_my_net push --target my-cmdb       # une cible
docker compose exec web snowth_my_net run --wait                  # collecter, exporter, pousser, attendre les tâches
```

## Vérifier un export

```bash
ls -l output/                                                         # ce qui a été écrit, et quand
tail -n +2 output/nodes.csv | cut -d, -f1 | tr -d '"' | sort -u | wc -l   # MAC distinctes
docker compose exec web snowth_my_net show nodes --filter 192.0.2       # la même chose, depuis l'état
```

Le nombre de MAC distinctes doit être proche de ce qu'affiche la pastille *Vues à la dernière
collecte*. S'il est très au-dessus, le fichier contient encore de la mémoire : `nodes.positions:
current` ne raccourcit pas cette mémoire, `node reset --yes` suivi d'une collecte si. Voir les
[diagnostics](diagnostics.md) quand un nœud manque dans le fichier.
