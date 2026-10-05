# Guide utilisateur

snowth_my_net cartographie un réseau sans le toucher. Il demande à vos switches, routeurs et
pare-feu ce qu'ils savent, en SNMP — quelle adresse MAC est sur quel port, quel voisin se trouve
à l'autre bout d'un câble, quelle IP correspond à quelle MAC — et en fait un inventaire, une carte
et des fichiers qu'un importateur sait lire.

Ce guide est la moitié « usage quotidien » de la documentation : comment le faire tourner,
comment faire prendre en compte un changement, ce que signifie chaque colonne, et que faire quand
quelque chose manque. La [référence de configuration](config.md) et les [formats de
fichiers](formats.md) restent l'endroit où chercher une clé ou une colonne d'un fichier.

## Ce qu'il fait, et ce qu'il ne fait jamais

* **Il n'écrit jamais sur un équipement.** Chaque requête SNMP est une lecture ; il n'y a aucun
  SNMP SET dans le code, et un test le garantit.
* **Il n'affiche jamais un secret.** L'état garde le *nom* d'un identifiant, jamais sa valeur ;
  une communauté ou une clé vit dans un fichier de `secrets/` et nulle part ailleurs.
* **Il ne devine pas.** Une MAC dont le port est douteux n'a pas de position plutôt qu'une
  mauvaise, une adresse qui ne fait que répéter la MAC n'est pas proposée comme adresse, et chaque
  silence peut être expliqué par une commande : voir les [diagnostics](diagnostics.md).
* **Il reste petit.** Un fichier SQLite, quelques CSV, une page web. Rien d'autre n'a besoin de
  tourner.

## Par où commencer

| Je veux | Lire |
|---|---|
| l'installer et obtenir un premier résultat | [Prise en main](getting-started.md) |
| le faire tourner avec Docker et le garder en marche | [Le faire tourner](operations.md) |
| faire prendre en compte un changement de configuration | [Faire prendre en compte un changement](operations.md#faire-prendre-en-compte-un-changement) |
| savoir ce que signifie une colonne de l'interface web | [Colonnes](columns.md) |
| comprendre pourquoi un nœud n'a ni port, ni nom, ni adresse | [Diagnostics](diagnostics.md) |
| alimenter une CMDB ou un importateur | [Exports](exports.md) |
| retrouver une commande | [Commandes](commands.md) |
| retrouver une clé de configuration | [Référence de configuration](config.md) |
| utiliser ou exposer l'interface web | [Interface web](web.md) |
| réparer ce qui ne marche pas | [Dépannage](troubleshooting.md) |

## Une journée avec lui

```bash
docker compose up -d                                # tout démarrer
docker compose exec web snowth_my_net collect       # interroger maintenant, sans attendre dix minutes
docker compose exec web snowth_my_net show devices  # qui a répondu, et qui non
docker compose exec web snowth_my_net export        # écrire les fichiers
```

Le planificateur fait la même chose seul : il collecte toutes les dix minutes et exporte deux fois
par jour (`schedule:` dans la configuration). L'interface web montre ce que la dernière collecte
a trouvé.

## Vocabulaire

| Terme | Sens |
|---|---|
| équipement | un switch, routeur, pare-feu ou point d'accès que snowth_my_net interroge en SNMP |
| nœud | une adresse MAC vue sur le réseau — un PC, un téléphone, une imprimante — et l'endroit où elle a été vue |
| position | le port d'un switch interrogé où un nœud a été appris, quand ce port est un port d'accès |
| uplink | un port qui mène à un autre switch : les MAC derrière lui ne sont pas placées dessus |
| collecte | un passage sur chaque équipement : il lit leurs tables et met à jour l'état |
| état | la base SQLite qui contient ce qui a été collecté (`state.sqlite`) |
| export | les fichiers écrits depuis l'état : CSV, JSON et cartes |
| amorce | une adresse listée dans `discovery.seeds`, là où une collecte commence |
| identifiant | une communauté SNMP ou un utilisateur v3 nommé, dont la valeur est un fichier de `secrets/` |
