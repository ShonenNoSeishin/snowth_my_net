# Colonnes

Ce que montre chaque tableau de l'[interface web](web.md), d'où vient chaque valeur, et ce que
signifie une case vide. Les mêmes explications sont dans le panneau **Comment lire ce tableau**
au-dessus de chaque tableau, dans la langue de l'interface ; cette page ajoute les règles qui sont
derrière. Les en-têtes sont écrits ici comme des mots ; l'interface les imprime en capitales. Pour
les colonnes des fichiers exportés, voir les [formats](formats.md).

## Lire un tableau

* **Filtre** : le champ au-dessus du tableau, et la touche `/` pour l'atteindre. Il cherche dans
  toutes les colonnes, y compris celles qui sont masquées : masquer une colonne ne rend donc
  jamais une ligne introuvable.
* **Tri** : cliquez sur un en-tête, cliquez encore pour inverser. Le filtre et le tri se font dans
  le navigateur, sur les lignes déjà envoyées.
* **Colonnes** : la pastille *Colonnes* choisit lesquelles afficher ; tirer le bord droit d'un
  en-tête règle sa largeur ; survoler une valeur qui a dû être coupée en montre l'entier. Le
  navigateur garde ces trois réglages, par page, et rien n'en atteint le serveur.
* **Les heures** sont dans le fuseau de la machine qui sert la page (`TZ`), nommé dans le pied de
  page ; en survoler une montre la valeur UTC stockée. Les fichiers exportés restent en UTC.
* **Taille** : le tableau des nœuds montre au plus `web.node_limit` lignes (2000 par défaut) et le
  dit quand il coupe ; `nodes.csv` les contient toujours toutes.

## Équipements

L'inventaire : une ligne par adresse interrogée, qu'elle ait répondu ou non.

| Colonne | Ce qu'elle contient | D'où ça vient | Vide signifie |
|---|---|---|---|
| Nom | la clé de jointure des tableaux Nœuds et Liens | le nom réglé à la main, sinon le `sysName` coupé au premier point, sinon l'IP ; ` (IP)` est ajouté quand deux équipements ont le même nom | jamais vide |
| IP | l'adresse interrogée | la configuration, ou un voisin qui l'a annoncée | jamais vide |
| Constructeur | qui le fabrique | le numéro d'entreprise IANA du `sysObjectID`, sinon le `sysDescr`, sinon l'adresse MAC | rien ne l'a identifié |
| Modèle | le châssis | ENTITY-MIB, sinon un motif sur le `sysDescr`, sinon un pilote constructeur | rien ne l'a identifié |
| Système | système et version | `sysDescr` ou `sysObjectID` ; un pilote remplit la version quand les MIB standard ne la donnent pas | non reconnu |
| Type | `switch`, `router`, `firewall`, `wireless`, `server`, `printer`, `facility` ou `other` | seulement sur preuve sûre : capacités LLDP, une MIB de fonction (imprimante, onduleur), le catalogue des `sysObjectID`, le système, ou réglé à la main | rien ne l'a prouvé ; le type ne décide jamais de ce qui est collecté |
| MAC | la MAC de base de l'équipement | l'adresse du bridge, sinon le châssis LLDP ; `+n MAC` signifie que n autres adresses sont connues, une par interface | aucune n'a été lue |
| État | le résultat de la dernière collecte de cet équipement | `ok`, `partial` (une table a échoué), `failed`, ou `never` pour une adresse qui n'a jamais répondu | pas encore collecté |
| Vu le | la dernière fois qu'il a répondu | la collecte | il n'a jamais répondu |

* Une adresse qui n'a jamais répondu est aussi une ligne, en rouge, avec la raison à côté de
  l'état : elle est comptée dans « 11/12 joignables » et c'est ici qu'on trouve la douzième.
* Un nœud vu avec une MAC quelconque d'un équipement interrogé n'est pas listé comme nœud : c'est
  l'équipement.

## Nœuds

Une ligne par adresse MAC et par endroit où elle a été vue.

| Colonne | Ce qu'elle contient | D'où ça vient | Vide signifie |
|---|---|---|---|
| Nom d'hôte manuel | un nom que vous avez écrit, qui l'emporte sur les deux autres | vous, dans la case ou avec `node name` ; conservé avec la MAC | rien n'a été écrit |
| Nom d'hôte DNS | la résolution inverse (PTR) de l'adresse de la colonne IP | le DNS, interrogé à l'export et mis en cache | aucune zone ne contient cette adresse : `dns check IP` dit quel résolveur a répondu |
| Nom d'hôte NetBIOS | ce que l'hôte a répondu quand on lui a demandé son propre nom | `names.probe`, désactivé par défaut ; se remplit aussi avec les réponses LLMNR et mDNS | non demandé, l'hôte est muet, ou la MAC qu'il annonce n'est pas celle de la ligne |
| Description | une ligne que vous avez écrite : à quoi ça sert, où c'est accroché, qui appeler | vous, dans la case ou avec `node describe` ; conservée avec la MAC | rien n'a été écrit |
| MAC | l'adresse | la table MAC d'un switch, ou le cache ARP/NDP d'un routeur ou d'un pare-feu | jamais vide |
| Constructeur | qui a fabriqué l'adaptateur | le registre IEEE, d'après la première moitié de la MAC | une adresse aléatoire, comme en utilisent par défaut les téléphones et portables |
| IP | l'adresse élue | les caches ARP/NDP, voir plus bas | aucune adresse utilisable n'a été vue |
| Switch | l'équipement dont la table MAC contient cette adresse sur un port d'accès | les tables MAC | la MAC n'est connue que d'un cache ARP, chaque port qui l'a vue est un uplink, ou le switch qui la porte n'est pas interrogé |
| Port | le port de ce switch | les tables MAC | comme Switch |
| VLAN | le VLAN dans lequel elle a été apprise | la table MAC, sinon le PVID du port | comme Switch |
| Vu le | la dernière observation de cette position | la collecte | jamais vide |

### Les trois noms d'hôte

Un nom peut être écrit à la main, détenu par une zone, ou annoncé par l'hôte lui-même. Ils restent
séparés dans le tableau et ne sont fusionnés que là où il faut une seule valeur, dans l'ordre de
confiance :

1. **Manuel** — quelqu'un l'a écrit, donc il l'emporte.
2. **DNS** — le réseau le dit.
3. **SNMP** — le `sysName` d'un équipement interrogé, quand la ligne est cet équipement : son
   adresse est celle qu'on interroge, et les MAC connues pour lui contiennent celle de la ligne.
   Un équipement qui répond à une requête authentifiée est une meilleure preuve qu'un nom qu'il
   annonce de lui-même.
4. **Ce que l'hôte dit de lui-même** — la preuve la plus faible, et une réponse NetBIOS est
   écartée quand l'adresse d'adaptateur qu'elle annonce n'est pas la MAC de la ligne.

Quand le nom écrit à la main et celui du DNS diffèrent, un bandeau au-dessus du tableau compte les
lignes et propose de n'afficher que celles-là. La casse et le domaine sont ignorés : `poste-julie`
et `poste-julie.example.net` concordent. L'un des deux est faux, et ce n'est pas à l'outil de dire
lequel. `explain <mac>` liste les trois et nomme celui qu'il a retenu, et `snapshot.json`
enregistre sa source.

### La colonne IP

L'adresse élue vient en premier, et les autres adresses connues pour cette MAC sont derrière un
`+n` qui ouvre une liste. L'élection se fait en quatre étapes :

1. les adresses qu'aucune autre MAC n'a revendiquées depuis ;
2. parmi elles, celles vues dans les `nodes.current_ip_window` (24 heures) suivant la plus
   récente ;
3. l'IPv4 d'abord (`nodes.prefer_ipv4`) ;
4. puis la plus récente.

Une adresse lien-local (`fe80::`) n'est jamais élue (`nodes.elect_link_local`) : rien ne route
vers elle, et celle qu'un hôte construit à partir de sa propre MAC ne dit rien que la colonne MAC
ne dise déjà. Une case vide signifie donc qu'aucune adresse utilisable n'a été vue, et elle le dit
honnêtement.

Une adresse est aussi écartée de l'élection quand elle est plus vieille que `nodes.current_ip_max_age` (7 jours) par rapport à la dernière observation du nœud lui-même. Et la case reste vide quand la MAC a plus de `nodes.max_ips_per_mac` adresses (une passerelle qui répond en proxy-ARP, un hyperviseur), ou deux adresses vues au même instant : on ne peut pas distinguer la bonne, et un mauvais nom rattaché à elle serait pire que pas de nom. Les adresses restent dans `snapshot.json`.

### Inventaire ou mémoire

Une table MAC garde ce qu'elle a appris pendant `nodes.retention_days` (30 jours), donc la liste
est en partie un inventaire, en partie une mémoire. Deux pastilles au-dessus du tableau les
distinguent : *Vues à la dernière collecte*, et *Tout, historique compris*, chacune avec son
compte. La référence est la dernière collecte **complète** : tester une seule adresse ne fait
jamais paraître le reste du réseau disparu. Pour vider la mémoire et laisser la prochaine collecte
la remplir à nouveau, `node reset --yes`.

### Une MAC sur plusieurs lignes

Une ligne dit `N positions` quand la même MAC a été vue à plusieurs endroits : son historique
d'itinérance, la plus récente d'abord. `nodes.positions: current` ne garde que la dernière. Une
MAC vue sur deux ports d'accès dans les `nodes.transit_window` (30 minutes) reste sur le port qui
porte le moins de MAC ; l'autre était du transit.

### Ce que la liste écarte

`show excluded` dit quelles MAC sont écartées, et pourquoi :

| Raison | Ce que c'est |
|---|---|
| `multicast` | une adresse multicast ou broadcast |
| `device_mac` | l'adresse d'un équipement interrogé |
| `ignored_mac`, `ignored_prefix` | listée dans `nodes.ignore_macs` ou `nodes.ignore_mac_prefixes` (les MAC virtuelles VRRP et HSRP par défaut) |
| `link_local_only` | connue seulement par une adresse lien-local dans un cache de voisinage : aucun port, rien pour la joindre (`nodes.include_link_local_only`) |

Une MAC vue seulement derrière des uplinks est gardée avec un Switch et un Port vides
(`nodes.include_unlocated`), ou placée sur le port qui l'a apprise avec `nodes.uplink_fallback`,
marquée `behind_uplink`.

### Les noms écrits dans le tableau

Les cases *Nom d'hôte manuel* et *Description* sont des champs : tapez, puis quittez la case ou
appuyez sur `Enter` pour enregistrer, `Escape` pour remettre ce qui y était. La page ne se
recharge pas et garde votre filtre et votre place. Avec des comptes configurés, il faut être
connecté. Un nom fait au plus 60 caractères, une description 200.

## Liens

Une ligne par lien physique annoncé en LLDP ou en CDP.

| Colonne | Ce qu'elle contient | D'où ça vient | Vide signifie |
|---|---|---|---|
| Équipement | l'équipement interrogé qui a entendu le voisin | la collecte | jamais vide |
| Port local | son port | la collecte | jamais vide |
| Équipement distant | le voisin tel qu'il s'est annoncé | LLDP ou CDP ; un nom absent des Équipements est un voisin qui n'est pas interrogé | jamais vide |
| Port distant | le port à l'autre bout | LLDP ou CDP | le voisin n'en a annoncé aucun |
| Protocole | `LLDP`, `CDP`, ou `LLDP+CDP` quand les deux s'accordent sur le même lien | la collecte | jamais vide |
| Vu le | la dernière collecte où les deux bouts s'annonçaient encore | la collecte | jamais vide |

* Un port qui entend plusieurs voisins mène à quelque chose de non managé : un switch ou un hub qui
  ne parle aucun des deux protocoles.
* Un port distant comme `BRIDGE-VOIP/VOIP-280-VLAN` est une interface logique du voisin (un
  bridge, un VLAN) : un seul câble peut être annoncé sous plusieurs noms.
* Les téléphones et les stations sont écartés sauf si `export.links.include_endpoints` est activé.
* Un identifiant fait d'octets bruts est montré en hexadécimal, et reconnu comme une MAC quand
  c'en est une.

## Inaccessibles

Ce qui ne peut pas être interrogé et ce qui ne peut pas être joint, dans un seul tableau à trois
sortes de lignes. Certaines sont à corriger, d'autres sont voulues : la page ne prétend pas
savoir lesquelles, elle rend chacune visible, avec la règle qui l'a décidée. Un équipement
interrogé n'y figure jamais.

| Colonne | Ce qu'elle contient | D'où ça vient | Vide signifie |
|---|---|---|---|
| Nature | *SNMP*, *Voisin* ou *Sondage de nom* | la page | jamais vide |
| Adresse | l'adresse concernée | l'adresse interrogée ; la première adresse de gestion annoncée par un voisin ; l'IP d'un nœud | un voisin qui n'en annonce aucune |
| Nom | l'équipement, le voisin tel qu'il s'est annoncé, ou le meilleur nom d'hôte connu d'un nœud | la dernière collecte | rien n'est connu |
| MAC | l'adresse de châssis d'un voisin, la MAC d'un nœud | LLDP, CDP, les tables MAC | non annoncée |
| Essayé | ce qui a été tenté | le SNMP avec l'identifiant choisi, ou avec chacun ; les protocoles demandés à un nœud | un voisin jamais tenté, un nœud jamais interrogé |
| Pourquoi pas | la raison, avec les mots de la règle | la collecte, la configuration | jamais vide |
| Dernière tentative | quand cela a été tenté pour la dernière fois | la collecte, la dernière question | jamais tenté |

Des pastilles au-dessus du tableau isolent chaque nature et la comptent. Les raisons, et ce que
chacune vous demande :

| Nature | Raison | Ce qu'elle vous demande |
|---|---|---|
| SNMP | l'erreur de la dernière tentative, comme `no answer (v3: timeout)`, ou `n'a jamais répondu` | la communauté, l'ACL de l'équipement (l'adresse de l'hôte, puisqu'un conteneur est en NAT), l'adresse elle-même ; `check` la teste |
| Voisin | `discovery.follow_neighbors is off` | rien, sauf si vous voulez explorer les voisins |
| Voisin | `it announces no management address` | rien : il n'y a rien à interroger, comme pour la plupart des téléphones |
| Voisin | `capabilities …: a phone, a station or an endpoint is never polled` | rien : voulu, voir `discovery.follow_capabilities` |
| Voisin | `outside discovery.allowed` ou `excluded` | ajouter son réseau à `discovery.allowed` (ou `all`), ou le laisser dehors exprès |
| Voisin | `disabled by the configuration` | `devices[].disabled` le dit |
| Voisin | `nothing stops it: the next collect will try it` | attendre la prochaine collecte |
| Sondage de nom | `outside names.networks, so never asked` | élargir `names.networks` là où le pare-feu laisse passer UDP/137 |
| Sondage de nom | `no answer` | l'hôte ne parle aucun des protocoles demandés, ou un pare-feu jette la question |
| Sondage de nom | `answered, but states the MAC …` | rien : un autre appareil a répondu pour cette adresse, et son nom a été écarté |
| Sondage de nom | `not asked yet: run 'names ask'` | `names ask`, ou le bouton *Demander les noms* |

Les lignes de sondage de nom n'existent que si `names.probe` liste un protocole, et seulement
pour les nœuds vus à la dernière collecte.

## Collectes

Les 50 dernières collectes.

| Colonne | Ce qu'elle contient | D'où ça vient | Vide signifie |
|---|---|---|---|
| N° | le numéro de la collecte | l'état | jamais vide |
| Commande | `collect`, `discover`, `run`… | l'état | jamais vide |
| Début | quand elle a commencé | l'état | jamais vide |
| Durée | combien de temps elle a pris | l'état | des points de suspension tant qu'elle tourne |
| Résultat | `ok`, `partial` (un équipement ou une table a échoué) ou `failed` | la collecte | il affiche `running` jusqu'à la fin |
| Équipements | les équipements qui ont répondu sur ceux interrogés | la collecte | des tirets : cette collecte n'a pas interrogé d'équipements |

Un équipement marqué `devices[].tolerate_failure` ne rend jamais une collecte `partial`. Les
boutons au-dessus du tableau lancent `collect`, `discover`, `export`, avec des cibles de push
`push`, et avec `names.probe` *Demander les noms* (`names ask`, sans tenir compte du cache) : un
à la fois, comme les mêmes commandes qu'un terminal lancerait.

## Fichiers

| Colonne | Ce qu'elle contient | D'où ça vient | Vide signifie |
|---|---|---|---|
| Fichier | un fichier exporté | le répertoire de sortie | jamais vide |
| Octets | la taille du fichier | le fichier | jamais vide |
| Écrit le | quand le dernier export l'a écrit | le fichier | jamais vide |

Cliquez sur un nom pour le télécharger. Seuls les noms d'export connus sont servis ; aucun chemin
venant d'une requête n'atteint le système de fichiers.

## SNMP

Cet onglet n'existe que si un compte est configuré, et il redemande ce mot de passe avant de
s'ouvrir. Une communauté n'est jamais affichée : l'état garde le nom d'un identifiant, jamais sa
valeur.

| Colonne | Ce qu'elle contient | D'où ça vient | Vide signifie |
|---|---|---|---|
| Adresse | une adresse interrogée | l'état | jamais vide |
| Nom | l'équipement trouvé là | la dernière collecte | elle n'a jamais répondu |
| Origine | comment elle est devenue interrogée : `seed`, `manual`, `neighbor`, `sweep` ou `state` | l'état | jamais vide |
| Identifiant | l'identifiant choisi pour elle | un réglage fait à la main | aucun choisi : celui qui répond est utilisé |
| État | le résultat de la dernière tentative, et la raison en cas d'échec | la dernière collecte | jamais essayée |
| Échecs | les tentatives échouées d'affilée | l'état | zéro |

Depuis cet onglet, on peut ajouter une adresse, en retirer une, choisir un identifiant par son
nom, tester une adresse (une collecte pour cette seule adresse), et oublier la mémoire MAC et ARP.
On ne peut pas y créer un identifiant.
