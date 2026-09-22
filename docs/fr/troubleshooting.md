# Dépannage

Commencez toujours par `snowth_my_net check` (par équipement : identifiant utilisé, temps
aller-retour, MIB qui répondent et nombre de lignes), puis `snowth_my_net probe <address>` pour
tester des OID à la main, et `snowth_my_net explain <mac|ip>` pour les positions.

## Rien ne répond

* `no answer (v3-main: timeout; …)` : ACL SNMP sur l'équipement (avec Docker, autorisez l'adresse
  de **l'hôte**), mauvais port, ou mauvaise communauté v2c — les échecs v2c sont silencieux et
  ressemblent donc à des délais dépassés. Restreignez `credentials[].scope`.
* `unknown user` / `wrong digest` : utilisateur ou clé SNMPv3 incorrects (signalé immédiatement).
* AES-192/256 sur Cisco : utilisez `aes192c` / `aes256c` (extension de clé Cisco).
* `no credential in scope for this address` : aucun `scope` d'identifiant ne contient l'adresse.

## Le type est vide

C'est voulu : un type n'est posé que sur une preuve sûre. Réglez-le à la main (interface en
terminal, onglet Réglages, ou `snowth_my_net device set 192.0.2.1 type=firewall`). **Le type
n'empêche jamais une collecte** : ARP, tables MAC, LLDP et CDP sont toujours tentés.

## La table ARP d'un pare-feu manque

Rien ne dépend de ce qu'annonce l'équipement (sysServices, type). Regardez `check` :
`ipNetToMedia` et `ipNetToPhysical`. S'ils répondent `absent`, la vue SNMP du pare-feu exclut
peut-être IP-MIB. Réglez `features.arp: force` sur cet équipement pour qu'une absence future soit
signalée comme une erreur (code 1).

## Pas de table MAC sur un switch Cisco

Cisco IOS sert les tables de bridge par VLAN. snowth_my_net utilise les instances par VLAN quand
CISCO-VTP-MIB répond (`vlan_indexing: auto`) ; forcez-les avec `vlan_indexing: cisco`. En SNMPv3,
le groupe doit avoir accès aux contextes de VLAN :

```
snmp-server group SNOWTH v3 priv context vlan- match prefix
```

En v2c, `community@vlan` doit être autorisé par la vue ou l'ACL de la communauté.

## Toutes les MAC d'un étage sont sur le trunk

Les positions ne sont gardées que sur les ports d'accès. Un port est un uplink quand un voisin
LLDP/CDP est un switch interrogé (ou un bridge/routeur non interrogé), quand il est déclaré
(`uplinks`), quand il porte plus de `uplink_mac_threshold` MAC, ou (en option) quand c'est un LAG.
Quand LLDP est désactivé entre deux switches, déclarez le port dans `uplinks`, baissez le
`uplink_mac_threshold` de l'équipement, ou comptez sur la détection du transit (la même MAC sur un
port qui porte moins de MAC l'emporte). `explain` montre les raisons.

## Un serveur ou un hyperviseur a perdu ses positions

Beaucoup de MAC sur un port en font un uplink faible au-delà du seuil (50). Déclarez le port dans
`access_ports`, ou relevez `uplink_mac_threshold` pour cet équipement.

## Téléphones IP

Les téléphones annoncent `bridge` + `telephone` : cela ne fait jamais d'un port un uplink, et le
PC derrière le téléphone garde sa position. Les téléphones ne sont jamais sondés pendant
l'exploration et ne sont pas dans `links.csv` (sauf avec `include_endpoints`).

## Clients Wi-Fi

* Pont local : les clients sont dans la table MAC du switch, sur le port de l'AP
  (`ap_ports_are_access`).
* Tunnel vers un contrôleur : les clients apparaissent sur le port du contrôleur, qui devient un
  uplink. Pour Cisco AireOS, le driver `cisco-wlc` publie les AP et positionne les clients sur
  leurs radios ; les autres contrôleurs demandent un driver Python. Voir [drivers](drivers.md).

## Notes par constructeur

| Constructeur | Note |
|---|---|
| Cisco IOS/IOS-XE | Instances de bridge par VLAN (ci-dessus) ; `lldpLocPortNum` n'est pas l'ifIndex (correspondance par nom) ; MAC virtuelles HSRP ignorées. |
| Cisco NX-OS | Les identifiants CDP `hostname(SERIAL)` sont nettoyés. |
| Cisco, VRF | Le contexte par défaut ne montre que la table de routage globale. Les VRF déclarées par l'équipement sont lues dans leur propre contexte SNMP (`devices[].vrfs`) ; le nom du contexte doit correspondre au nom de la VRF sur l'équipement. |
| Juniper EX/QFX | Les identifiants de FDB ne sont pas des numéros de VLAN : `dot1qVlanFdbId` est utilisé. Les MAC apprises sur des unités logiques (`ge-0/0/5.0`) sont attribuées au port physique. |
| HPE Aruba AOS-CX, ProVision | MIB standard ; sur ProVision, les ports de bridge sont égaux aux ifIndex. |
| Fortinet, Sophos | ARP via IP-MIB ; ENTITY-MIB souvent absente : les drivers `fortinet` et `sophos` lisent le numéro de série, la version (et le modèle pour Sophos) dans les MIB privées. |
| Palo Alto | ARP via IP-MIB ; ENTITY-MIB généralement présente. Pas de driver. |
| MikroTik RouterOS | BRIDGE-MIB partielle selon la version ; le driver `mikrotik` ajoute l'identité et les stations de ses interfaces sans fil. |
| Contrôleurs Cisco AireOS | Driver `cisco-wlc` : AP synthétiques et positions des clients. |
| Ubiquiti UniFi/EdgeSwitch | Identifiants de pile SNMP générique : constructeur d'après l'OUI de la MAC. |
| Agents qui servent LLDP-V2-MIB | Lue en repli quand LLDP-MIB ne répond rien ; son index nomme l'ifIndex local, donc aucun rapprochement de port n'est nécessaire. |
