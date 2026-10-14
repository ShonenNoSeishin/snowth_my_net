# Diagnostics

Un inventaire qui ne doit contenir aucun faux positif doit préférer le silence à la supposition.
Un nœud sans port, une colonne vide, un équipement absent : chacun est l'outil qui refuse
d'affirmer ce qu'il n'a pas pu prouver. Le but de cette page est que **chaque silence ait une
explication, et une commande qui la donne**. Trouvez le symptôme, lancez la commande, lisez ce
qu'elle dit.

## Ce qui explique quoi

| Ce qui est expliqué | Où |
|---|---|
| ce qui n'a pas pu être interrogé ou joint, et pourquoi | l'onglet *Inaccessibles* de l'interface web |
| ce que chaque table SNMP a rendu sur chaque équipement | `show tables` |
| quels ports sont tenus pour des uplinks, par preuve ou par supposition, et ce que chacun coûte | `show uplinks` |
| quelles MAC la liste écarte, et pourquoi | `show excluded` |
| tout sur une MAC : ses observations, les ports écartés, ses adresses, ses trois noms d'hôte | `explain` |
| quel résolveur répond, et si une zone contient une adresse | `dns check` |
| si un hôte annonce son propre nom | `dns probe` |

## Par où regarder d'abord

| Symptôme | Première étape | Ce que ça vous apprend |
|---|---|---|
| un équipement manque dans l'inventaire | l'onglet *Inaccessibles*, nature *SNMP* | l'erreur de la dernière tentative ; puis `check` avec son adresse |
| « 11/12 joignables » et vous voulez la douzième | l'onglet Équipements, lignes en rouge | quelle adresse, et la raison à côté |
| un nœud n'a pas de port | `explain <mac>` | chaque observation, et la raison pour laquelle chaque port a été écarté |
| un nœud apparaît deux fois, sur un port et sur un trunk | `explain <mac>` puis `show uplinks` | un trunk pris pour un port d'accès, ou un déménagement |
| une MAC n'est pas du tout dans la liste | `show excluded` | la règle qui l'a écartée |
| un nœud n'a pas d'IP | `explain <mac>` | ses observations ARP ; une adresse lien-local n'est jamais élue |
| un nœud n'a pas de nom d'hôte | `dns check <ip>` | le résolveur qui a répondu, et `nxdomain` quand aucune zone ne contient l'adresse |
| les nœuds d'un VLAN manquent | les lignes `note:` d'un `collect`, puis `show tables` | un VLAN dont la table MAC n'a pas été lue |
| une table MAC est revenue vide ou courte | `show tables` | son état, ses lignes et sa durée |
| trop de lignes, des anciennes parmi elles | la pastille *Vues à la dernière collecte* | ce qui est mémoire et ce qui est inventaire |
| l'interface répond 503 | `collect` | l'état est plus ancien que l'outil et a besoin de sa première écriture |

## Un nœud n'a pas de port, ou le mauvais

```bash
docker compose exec web snowth_my_net explain 80:5e:c0:3b:1f:4f
docker compose exec web snowth_my_net show uplinks
```

`explain` liste chaque endroit où la MAC a été vue dans une table MAC, marque d'une coche celui
qu'il a retenu, et donne la raison pour chaque port qu'il a mis de côté. Les raisons, telles
qu'elles s'impriment :

| Raison | Ce que ça veut dire | Quoi faire |
|---|---|---|
| `neighbor …` avec un switch interrogé | LLDP ou CDP montre un switch interrogé sur ce port : une preuve | rien : la MAC est derrière lui, et son vrai port est sur ce switch |
| `neighbor … local port guessed from its number` | le voisin est un switch interrogé, mais LLDP n'a donné le port local que comme un numéro égal par hasard à un ifIndex ou à un port bridge : une supposition | rien à faire ; un équipement qui nomme ses ports locaux (ou LLDP-V2) en fait une preuve |
| `neighbor …` avec un bridge ou un routeur | un voisin LLDP ou CDP qui n'est pas interrogé est sur ce port : une supposition | interroger cet équipement, ou accepter `nodes.uplink_fallback` |
| `61 MACs > 50` | le port porte plus que `nodes.uplink_mac_threshold` : une supposition | le relever pour cet équipement, ou lister le port dans `devices[].access_ports` |
| `declared in uplinks` | vous l'avez dit | `devices[].uplinks` |
| `declared in access_ports` | vous avez dit le contraire | `devices[].access_ports` |
| `link aggregation` | `nodes.lag_is_uplink` est activé | |

Un trunk hérite des voisins de ses ports membres, donc un trunk entre switches est reconnu même
quand il porte peu de MAC ; la raison se lit alors *a member of this trunk*.

`show uplinks` se termine par un compte : combien de MAC obtiendraient une position avec
`nodes.uplink_fallback`, qui leur donne le port qui les a apprises, marqué `behind_uplink`. Un
appareil derrière un switch qui **est** interrogé n'en reçoit jamais ainsi, parce que son vrai
port vient de ce switch.

## Un équipement ne répond pas

L'onglet *Inaccessibles* dit ce qui a été essayé et ce qui est revenu. Ensuite :

```bash
docker compose exec web snowth_my_net check 192.0.2.12
docker compose exec web snowth_my_net probe 192.0.2.12 system
```

| À vérifier | Pourquoi |
|---|---|
| la communauté, ou l'utilisateur v3 et ses clés | une mauvaise ressemble exactement à un délai dépassé |
| l'ACL SNMP de l'équipement | elle doit autoriser l'adresse de l'**hôte** : un conteneur sort par elle |
| le port, `general.snmp.port` | ou `address:port` dans la configuration |
| la version de l'identifiant | une communauté v2c face à un agent v3 seul, c'est du silence |
| `general.snmp.timeout` et `retries` | un agent lent peut être entendu trop tard |

Une adresse qui répond pour certaines tables et pas pour d'autres est `partial` dans l'onglet
Équipements, et `show tables` dit quelle table a échoué et comment.

## Un nœud n'a pas de nom d'hôte

```bash
docker compose exec web snowth_my_net dns check 192.0.2.121
```

| Réponse | Ce que ça veut dire |
|---|---|
| `ok` | un nom a été trouvé, et `ANSWERED BY` dit par quel résolveur |
| `nxdomain` | le résolveur a répondu « ce nom n'existe pas » : pas de zone inverse pour ce sous-réseau, ou rien n'a enregistré de PTR pour cette adresse |
| `timeout` | aucun résolveur n'a répondu : le port 53 est fermé, en UDP ou en TCP, depuis l'adresse de l'hôte, ou plus lent que `dns.timeout` |
| `error` | le résolveur a refusé : vérifiez qu'il sert ce client |

Un nom trouvé est gardé `dns.cache_ttl`, un « pas de nom » `dns.negative_ttl`. Après avoir
corrigé un résolveur, `dns flush --misses-only` oublie les refus pour que la correction se voie à
l'export suivant.

Quand aucune zone ne contiendra jamais l'adresse, on peut demander son nom à l'hôte lui-même :

```bash
docker compose exec web snowth_my_net dns probe 192.0.2.120
```

Elle essaie NetBIOS, LLMNR et mDNS, comme le font `nbtstat -A` et un scanner. Activez-la pour de
bon avec `names.probe`, et voyez les lignes *Sondage de nom* de l'onglet *Inaccessibles* pour les
hôtes qui restent muets. Un nom qu'un hôte annonce sur lui-même est une preuve plus faible qu'un
nom détenu par une zone, ce qui explique qu'il vienne en dernier quand les trois sont fusionnés.

## Lire les notes d'une collecte

Une collecte écrit une ligne `note:` pour chaque décision qu'elle a prise et que vous pourriez
vouloir connaître :

| Note | Ce que ça veut dire |
|---|---|
| `neighbor X (a.b.c.d): skipped (capabilities station,telephone)` | un téléphone ou une station n'est jamais interrogé, par construction |
| `neighbor X (a.b.c.d): skipped (outside discovery.allowed)` | l'adresse n'est dans aucune plage autorisée : ajoutez-la, ou écrivez `all` |
| `neighbor X (a.b.c.d): skipped (max_depth 3)` | le voisin est plus loin que `discovery.max_depth` sauts |
| `neighbor X (a.b.c.d): skipped (disabled)` | `devices[].disabled` le dit |
| `a.b.c.d: VLAN 81, 90: ports live there but the MAC table returned nothing for them` | l'instance de bridge de ces VLAN n'a pas été lue : `devices[].vlan_indexing: cisco` les lit chacune |

Rien n'est déduit de la note sur les VLAN : aucune position n'est inventée. Elle nomme le trou et
le réglage qui le comble.

## Quand les chiffres diffèrent d'un autre outil

Deux outils comptent rarement la même chose. Un outil qui ne lit que les tables MAC compte ce
qu'un switch a appris ; celui-ci compte aussi ce qu'un cache ARP connaît, et écarte ce qu'il ne
sait pas placer. Comparez la même chose :

```bash
tail -n +2 output/nodes.csv | cut -d, -f1 | tr -d '"' | sort -u > /tmp/snowth.macs
# les MAC actives de l'autre outil, une par ligne, en minuscules avec deux-points, dans /tmp/other.macs
comm -23 /tmp/other.macs /tmp/snowth.macs      # vues par l'autre outil seulement
comm -13 /tmp/other.macs /tmp/snowth.macs      # vues ici seulement
```

Lancez `explain` sur quelques MAC de la première liste : chacune a une raison. Les habituelles
sont une MAC retenue derrière un uplink, un VLAN dont la table n'a pas été lue, un port que
l'autre outil rapporte d'après une vieille lecture, et une MAC que l'autre outil donne pour active
parce que sa dernière lecture n'est pas récente. Comparez avec le compte *Vues à la dernière
collecte*, pas avec le total.

## L'interface web

| Symptôme | Cause | Quoi faire |
|---|---|---|
| un 503 juste après une mise à jour | l'état est plus ancien que l'outil | lancez `collect` ; la première écriture le met à niveau |
| le navigateur avertit pour le certificat | il est auto-signé | acceptez-le une fois, ou remplacez-le, voir l'[interface web](web.md) |
| une connexion est refusée | le journal dit `no such account` ou `wrong password` | `web passwd` le réinitialise, sans redémarrage |
| l'onglet *SNMP* manque | il demande un compte, et `web.actions` activé | déclarez un compte sous `web.auth.users` |
| un bouton échoue | la ligne sous les boutons dit comment la commande s'est terminée, avec son dernier message | tapez la même commande dans un terminal pour tout voir |
