# Formats de sortie

Tous les fichiers sont écrits de façon atomique dans `general.output_dir` (fichier temporaire,
`fsync`, renommage) : un lecteur voit l'ancien fichier ou le nouveau, jamais une moitié. Les
fichiers CSV sont en UTF-8 sans BOM, RFC 4180 (CRLF par défaut, guillemets seulement quand c'est
nécessaire). Leurs **en-têtes sont fixés à l'octet près** (vérifiés par des fichiers de
référence). Toutes les heures sont en UTC, `YYYY-MM-DDTHH:MM:SSZ`, à la seconde, pour que les
chaînes se comparent correctement.

**Garde-fou contre les fichiers vides :** un CSV sans aucune ligne de données n'écrase pas le
fichier précédent, n'est pas poussé, et la commande sort avec le code 1 (sauf s'il figure dans
`export.allow_empty`).

## `devices.csv`

```
"Device Name","Device Details","IP Address",Location,Model,Serial,Vendor,"Operating System","OS Version","MAC Address","Device Type"
```

Un équipement par ligne, trié par nom.

| Colonne | Contenu |
|---|---|
| Device Name | `devices[].name` ou le nom réglé à la main, sinon le sysName sans son domaine (`general.device_name`), sinon l'IP. Les doublons reçoivent ` (IP)`. **La clé de jointure** de `nodes.csv` et `links.csv`. |
| Device Details | sysDescr sur une seule ligne. |
| IP Address | Adresse de gestion interrogée (sans port). |
| Location | sysLocation. |
| Model | Modèle ENTITY-MIB du châssis principal (ou le motif sysDescr propre au constructeur). |
| Serial | Numéro de série ENTITY-MIB du châssis principal (les valeurs bouche-trou comme `0` ou `N/A` sont écartées). Tous les membres d'une pile sont dans `snapshot.json`. |
| Vendor | D'après le numéro d'entreprise IANA du sysObjectID (OUI de la MAC de base pour les piles SNMP génériques). |
| Operating System | Par exemple `IOS-XE`, `AOS-CX`, `Junos`, `SFOS`, `FortiOS`. |
| OS Version | D'après le sysDescr, la révision logicielle ENTITY-MIB, ou le remplissage d'un collecteur personnalisé. |
| MAC Address | `dot1dBaseBridgeAddress`, sinon la MAC de châssis LLDP, sinon vide. |
| Device Type | `switch`, `router`, `firewall`, `wireless`, `server`, `printer`, `facility`, `other` — **ou vide faute de preuve sûre**. Réglé à la main, par la configuration, ou détecté (capacités LLDP propres, Printer-MIB/UPS-MIB, identifiants produit du constructeur, système ou constructeur à usage unique). `snapshot.json` donne la règle et la raison. Désactivable (`export.devices.include_type`). |

## `nodes.csv`

```
"MAC Address",Vendor,"IP Address","DNS Name",Switch,Port,VLAN,"Last Seen"
```

Une ligne par (MAC, position), triée par `Last Seen` décroissant. Un consommateur qui regroupe par
MAC prend la ligne la plus récente comme position courante ; les autres lignes forment son
historique d'itinérance.

| Colonne | Contenu |
|---|---|
| Name | Seulement avec `export.nodes.include_name: true` : le nom donné à la main à cette MAC (`node name`), vide sinon. La colonne est absente par défaut, pour ne pas changer les colonnes que lit un importateur. |
| Description | Seulement avec `export.nodes.include_description: true` : la description donnée à la main (`node describe`). |
| MAC Address | En minuscules avec deux-points. Les MAC de broadcast, multicast, nulles, virtuelles VRRP/HSRP, celles des équipements interrogés, et celles connues par rien d'autre que la forme `fe80::` d'elles-mêmes (`nodes.include_link_local_only`) sont exclues. |
| Vendor | Registre IEEE (MA-L/MA-M/MA-S), nettoyé ; vide pour les MAC administrées localement (aléatoires). |
| IP Address | IP courante de la MAC : parmi les adresses qu'aucune autre MAC n'a revendiquées depuis, celles vues dans les `nodes.current_ip_window` (24 h) suivant la plus récente, l'IPv4 d'abord. Une IPv6 seule signifie qu'aucune IPv4 récente n'est connue : augmentez `current_ip_window` (par exemple `30d`) pour qu'une IPv4 gagne dès qu'il en existe une dans la rétention. Toutes les adresses d'une MAC restent dans `snapshot.json` et dans l'interface web. |
| DNS Name | Nom PTR de cette IP (mis en cache). |
| Switch | Exactement un `Device Name` de `devices.csv` ; vide quand aucun port d'accès n'est connu. |
| Port | Nom court de l'interface (`Gi1/0/5`, `1/1/12`, `ge-0/0/3`). |
| VLAN | D'après la table MAC (FDB Q-BRIDGE ou instance Cisco par VLAN), sinon le VLAN du port (PVID). |
| Last Seen | Dernière observation de cette position (pas l'heure de l'export). Pour une ligne sans position : dernière observation de la MAC. |

Pourquoi une MAC est (ou n'est pas) sur un port : `snowth_my_net explain <mac|ip>`.

## `links.csv`

```
Local Device,Local Port,Remote Device,Remote Port,Protocol,Last Seen
```

Un lien physique par ligne, même vu des deux côtés et par les deux protocoles. Quand les deux
extrémités sont des équipements interrogés, `Local Device` est celui dont le nom vient en premier
dans l'ordre de tri. `Protocol` vaut `LLDP`, `CDP` ou `LLDP+CDP`. Téléphones et stations sont
exclus, sauf avec `export.links.include_endpoints`.

## `snapshot.json`

Tout ce qui est connu, pour les scripts. `schema` est versionné (`snowth_my_net/snapshot/1`) ; au
sein d'une version, des champs peuvent seulement être ajoutés.

```json
{
  "schema": "snowth_my_net/snapshot/1",
  "generated_at": "2026-09-17T11:00:04Z",
  "tool_version": "…",
  "last_collect": {"run_id": 812, "finished_at": "…", "status": "partial", "stats": {}},
  "devices": [{
    "name": "…", "ip": "…", "address": "…", "sys_name": "…", "description": "…",
    "location": "…", "contact": "…", "object_id": "…", "vendor": "…", "model": "…",
    "serial": "…", "os": "…", "os_version": "…", "base_mac": "…",
    "device_type": "…", "type_rule": "…", "type_reason": "…", "detected_type": "…",
    "credential": "v3-main", "driver": "sophos", "first_seen": "…", "last_seen": "…", "last_collect_status": "ok",
    "chassis": [], "addresses": [], "vlans": [],
    "interfaces": [{"ifindex": 8, "name": "Gi1/0/1", "role": "access", "role_reasons": [],
                    "mac_count": 1, "…": "…"}],
    "neighbors": [{"protocol": "lldp", "local_port": "…", "remote_device": "…",
                   "remote_port": "…", "remote_polled": true, "capabilities": ["bridge"]}],
    "custom": {"collector": {"status": "ok", "values": {}, "table": []}},
    "collection": {"fdb": {"status": "ok", "rows": 1834, "duration_ms": 900, "detail": ""}}
  }],
  "nodes": [{"mac": "…", "vendor": "…", "random_mac": false, "position_kind": "access",
             "current_ip": "…", "dns_name": "…", "first_seen": "…", "last_seen": "…",
             "positions": [], "sightings": [], "ips": []}],
  "links": [{"a": {"device": "…", "port": "…"}, "b": {"device": "…", "port": "…"},
             "protocols": ["LLDP", "CDP"], "endpoint": false, "last_seen": "…"}],
  "errors": [{"device": "…", "function": "arp", "status": "timeout", "detail": "…"}]
}
```

## Cartes

* `map.dot` — Graphviz (`dot -Tsvg map.dot > map.svg`) ; formes et couleurs selon le type,
  voisins non interrogés en pointillés.
* `map.mmd` — Mermaid (`graph LR`), affiché par GitLab, GitHub, Obsidian…
* `map.html` — une page autonome (aucune ressource externe, fonctionne hors ligne) : zoom,
  déplacement, glisser, recherche, détails au clic, thèmes clair et sombre.

Les hôtes finaux s'ajoutent avec `export.map.endpoints: grouped` (une bulle par port) ou `all`.

## Push HTTP

Pour chaque cible, chaque fichier de `files` est envoyé **séparément, dans l'ordre** :

```
POST <url>
Authorization: Bearer <token>            (or Basic, or custom headers)
Content-Type: multipart/form-data; boundary=…

--boundary
Content-Disposition: form-data; name="<extra field>"      (optional extra_fields)

value
--boundary
Content-Disposition: form-data; name="file"; filename="devices.csv"
Content-Type: text/csv            (application/json : snapshot, rapports JSON ; text/markdown, text/html : rapports)

<file content>
--boundary--
```

* Un 2xx est un succès ; le corps de la réponse est journalisé (tronqué à 4 Ko).
* 202 avec `--wait` (ou `wait: true`) : l'identifiant du job est lu à `poll.id_field` dans le
  corps JSON, puis `GET poll.url` est appelé toutes les `poll.interval` jusqu'à ce que
  `poll.status_field` soit dans `success` (OK), ne soit plus dans `pending` (FAILED), ou que
  `poll.timeout` expire (FAILED).
* Un fichier en échec n'empêche jamais le suivant. Le résumé indique `OK`/`FAILED` par fichier ;
  le code de sortie vaut 1 si quelque chose a échoué.
* Les redirections ne sont pas suivies ; TLS est vérifié sauf avec `tls_verify: false` ; nouvelles
  tentatives uniquement sur erreur réseau, 429 (en respectant `Retry-After`), 502, 503, 504.
* Dans `run`, un fichier dont l'export a échoué est signalé `FAILED`, et l'ancien fichier présent
  sur le disque n'est pas envoyé à sa place.

## Codes de sortie

| Code | Signification |
|---|---|
| 0 | OK |
| 1 | Échec partiel : un équipement ou une fonction forcée a échoué, un export était vide, un push a échoué, `health` constate une collecte trop ancienne |
| 2 | Erreur de configuration ou d'utilisation (YAML invalide, clé inconnue, secret illisible, extension ou planification invalide) |
| 3 | L'état est verrouillé par une autre exécution au-delà de `general.lock_wait` |
| 130 | Interrompu ; les résultats déjà enregistrés sont gardés |
