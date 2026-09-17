# Drivers constructeur

Les MIB standard (IF-MIB, BRIDGE/Q-BRIDGE, IP-MIB, LLDP, ENTITY-MIB) sont toujours collectées sur
chaque équipement, quoi qu'il annonce. Un driver ne fait qu'**ajouter** ce que ces MIB ne savent
pas dire pour une famille de produits :

* **l'identité**, lue dans des objets privés : modèle, numéro de série, nom et version du
  système, appliqués aux champs que la collecte standard a laissés vides ;
* **des observations**, après la collecte standard : stations Wi-Fi, entrées ARP, et points
  d'accès décrits par un contrôleur.

Un driver ne désactive jamais une fonction standard. Son travail est enregistré comme n'importe
quelle fonction (`driver` et `driver:<name>` dans `snapshot.json` → `collection`, dans l'onglet
*Dernière collecte* du TUI et dans `check`), et une erreur du driver ne fait échouer que cette
fonction.

## Sélection

Un driver est choisi d'après le sysObjectID de l'équipement. `devices[].driver` modifie ce
choix :

```yaml
devices:
  - address: 192.0.2.10
    driver: cisco-wlc      # l'utiliser même si le contrôleur annonce un identifiant produit Cisco
  - address: 192.0.2.11
    driver: none           # collecte standard uniquement
```

`check` affiche le driver et ce qu'il a complété, par exemple
`driver:fortinet ok(serial, os_version)`. Chaque objet lu par un driver a un préréglage dans le
testeur d'OID (`probe ADDR <preset>` ou le TUI) : on peut donc le vérifier à la main sur ses
équipements avant de s'y fier.

## Drivers intégrés

| Driver | Choisi pour (sysObjectID) | Ajoute | Préréglage(s) |
|---|---|---|---|
| `fortinet` | `1.3.6.1.4.1.12356.101.1.*`, `…12356.15.*` (FortiGate, FortiWiFi) | numéro de série (`fnSysSerial`), version et build de FortiOS (`fgSysVersion`) | `fortinet` |
| `sophos` | `1.3.6.1.4.1.2604.5` (Sophos Firewall / XGS, SFOS) | modèle (`sfosDeviceType`), version SFOS (`sfosDeviceFWVersion`), numéro de série = clé d'appliance (`sfosDeviceAppKey`) | `sophos-sfos` |
| `mikrotik` | `1.3.6.1.4.1.14988.1` (RouterOS) | nom de la carte, numéro de série, version de RouterOS ; stations Wi-Fi enregistrées sur les interfaces sans fil du routeur lui-même (`mtxrWlRtabTable`), comme positions sur ces interfaces | `mikrotik`, `mikrotik-wifi` |
| `cisco-wlc` | `1.3.6.1.4.1.14179.1.1.4.3` (AireOS ; les autres avec `driver: cisco-wlc`) | un **équipement synthétique** par point d'accès associé (nom, IP, modèle, numéro de série, logiciel, emplacement) et chaque client comme position sur la radio de son AP, avec l'IP apprise par le contrôleur | `cisco-wlc-aps`, `cisco-wlc-clients` |

Les valeurs ne sont acceptées que si elles ont la forme attendue (une version ressemble à une
version, un modèle à un modèle) : un agent qui sert autre chose sous les mêmes OID ne change donc
rien.

Les drivers ont été construits d'après les définitions des MIB des constructeurs et testés sur des
agents synthétiques ; si l'un de vos équipements n'est pas d'accord, `probe` montre ce qu'il sert
réellement, `driver: none` désactive le driver pour lui, et un collecteur personnalisé ou un
driver Python peut faire mieux.

### Contrôleurs sans fil et points d'accès synthétiques

Avec des AP légers, le trafic des clients passe en tunnel jusqu'au contrôleur : les switches ne
voient les clients que derrière le port du contrôleur, qui devient un uplink, si bien que les
clients n'auraient pas de position. Le driver `cisco-wlc` publie chaque AP dans `devices.csv`
(Device Type `wireless`, Device Details `<model> (reported by <controller>)`) et chaque client
dans `nodes.csv` avec `Switch` = le nom de l'AP et `Port` = `radio0`, `radio1`… La jointure
`Switch` ⊂ `Device Name` est respectée.

* Un AP est identifié par sa MAC de base. Si l'AP est aussi interrogé directement (ou découvert
  par LLDP/CDP), il s'agit du même équipement : l'identité interrogée est gardée et les stations
  sont ajoutées.
* Un AP sans IP de gestion n'est pas publié (toutes les sorties ont besoin d'une adresse).
* Les radios (ifType `ieee80211`) ne deviennent jamais des uplinks à cause du seuil de MAC :
  beaucoup de stations sur une radio, c'est normal. Cela vaut aussi pour les interfaces sans fil
  des routeurs et pour toute radio signalée par un agent standard.
* Les équipements synthétiques sont rafraîchis à chaque collecte du contrôleur et oubliés après
  `general.retention_days`, comme tout équipement.
* Pas encore couverts : contrôleurs Catalyst 9800 (MIB CISCO-LWAPP), contrôleurs Aruba et
  Fortinet, UniFi (les clients ne sont que dans l'API du contrôleur). Un driver Python peut les
  ajouter.

## Comportements standard qui semblaient propres à un constructeur

Certains manques se sont révélés génériques et sont traités pour tous les équipements, sans
driver :

* **Unités logiques** (`ge-0/0/5.0` sur Juniper, `Gi0/1.10`, `eth0.100`) : les MAC apprises sur
  une unité logique sont attribuées à son port physique quand `ifStackTable` empile l'unité sur
  exactement une interface **et** que l'unité s'appelle `<port>.<number>`. Le rôle du port (voisin
  LLDP, listes d'uplinks, nombre de MAC) est alors évalué là où il doit l'être. Les tunnels, les
  interfaces IRB/VLAN et les agrégats ne sont jamais repliés.
* **Identifiants CDP NX-OS** `hostname(SERIAL)` : ils sont nettoyés.
* **Tables MAC Cisco par VLAN** : lues selon ce que l'équipement répond, voir
  [dépannage](troubleshooting.md).

## Écrire un driver

Une extension Python peut déclarer un driver avec les mêmes possibilités que les drivers intégrés
(il est essayé avant eux, et peut donc en remplacer un) :

```python
from snowth_my_net.api import AccessPoint, Extension, Observations, Station, text

extension = Extension("acme")
acme = extension.driver("acme-os", object_ids=["1.3.6.1.4.1.99999.1"])

@acme.identity
async def identity(device, snmp):
    values = await snmp.get("1.3.6.1.4.1.99999.1.1.0")
    return {"os_version": text(values["1.3.6.1.4.1.99999.1.1.0"])}

@acme.observations
async def observations(device, snmp):
    return Observations(
        stations=[Station(mac=text(v), port=7) for _i, v in await snmp.walk("1.3.6.1.4.1.99999.2")],
        arp=[("00:00:5e:00:53:01", "192.0.2.50")],
        access_points=[AccessPoint(mac="00:00:5e:00:53:70", name="ap-1", address="192.0.2.70",
                                   stations=[Station("00:00:5e:00:53:02", port=1)])])
```

Voir [extensions](extensions.md#extensions-python) pour le chargement, et
`snowth_my_net.testing.run_driver` pour des tests sans équipement.
