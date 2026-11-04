"""The Documentation tab: what a reader needs to trust the tables, short and in both languages.

The full manuals live in ``docs/`` (not shipped in the image); this is the essential part, kept
here so that it travels with the program and cannot disagree with the version that runs it.
Each block is ``(kind, english, french)`` with kind ``p`` (paragraph) or ``li`` (list item);
a `backticked` span is code.
"""

from __future__ import annotations

import re
from html import escape as esc

SECTIONS = (
    ("purpose", ("What this tool is", "À quoi sert cet outil"), (
        ("p", "snowth_my_net reads your network over SNMP and never writes to a device. It builds "
              "an inventory and exports it as CSV files shaped like netdisco's, so that "
              "inventory_manager can read them in place of netdisco.",
              "snowth_my_net lit votre réseau en SNMP et n'écrit jamais sur un équipement. Il "
              "construit un inventaire et l'exporte en fichiers CSV de la forme de ceux de "
              "netdisco, pour qu'inventory_manager les lise à la place de netdisco."),
        ("li", "Devices: what answered SNMP, with its model, system and last collect.",
               "Équipements : ce qui a répondu en SNMP, avec son modèle, son système et sa "
               "dernière collecte."),
        ("li", "Nodes: every MAC address seen, with the port it was heard on and its address.",
               "Nœuds : chaque adresse MAC vue, avec le port où elle a été entendue et son "
               "adresse."),
        ("li", "Links: the neighbours devices announce to each other (LLDP, CDP).",
               "Liens : les voisins que les équipements s'annoncent entre eux (LLDP, CDP)."),
        ("li", "Ports: for one device, each port with its state, the MACs heard on it and the "
               "neighbour it announced there. Topology: the same links, drawn.",
               "Ports : pour un équipement, chaque port avec son état, les MAC entendues dessus "
               "et le voisin qu'il y a annoncé. Topologie : les mêmes liens, dessinés."),
        ("p", "The rule behind every table: when the evidence is missing, the cell stays empty. "
              "Nothing is guessed to fill a gap.",
              "La règle derrière chaque tableau : quand la preuve manque, la cellule reste vide. "
              "Rien n'est deviné pour combler un trou."),
    )),
    ("nodes", ("Reading the Nodes table", "Lire le tableau Nœuds"), (
        ("li", "Switch and port: where a switch's MAC table learned the MAC. A port that leads to "
               "another switch (a neighbour, a link aggregation, or many MACs on it) is an "
               "uplink: the MAC is behind it and no position is stated for it. "
               "`nodes.uplink_fallback` can give such MACs the port that learned them, marked "
               "as behind an uplink.",
               "Switch et port : là où la table MAC d'un switch a appris la MAC. Un port qui "
               "mène à un autre switch (un voisin, une agrégation, ou beaucoup de MAC dessus) "
               "est un uplink : la MAC est derrière lui et aucune position n'est affirmée. "
               "`nodes.uplink_fallback` peut leur donner le port qui les a apprises, marqué "
               "comme derrière un uplink."),
        ("li", "VLAN: shown only when the MAC table or a VLAN context stated it, never deduced.",
               "VLAN : affiché seulement quand la table MAC ou un contexte VLAN l'a énoncé, "
               "jamais déduit."),
        ("li", "IP address: from the ARP and NDP tables of routers and firewalls. The shown "
               "address is the most recent one that no other MAC took later, IPv4 first. An "
               "empty cell means no usable address was seen, not an error.",
               "Adresse IP : tirée des tables ARP et NDP des routeurs et pare-feux. L'adresse "
               "affichée est la plus récente qu'aucune autre MAC n'a prise ensuite, l'IPv4 "
               "d'abord. Une cellule vide veut dire qu'aucune adresse utilisable n'a été vue, "
               "pas une erreur."),
        ("li", "Names, in order of trust: written by hand, then DNS, then the name an SNMP "
               "device reports, then what a host says about itself (NetBIOS, mDNS, LLMNR). A "
               "banner counts the rows where they disagree; the tool does not decide which is "
               "right.",
               "Noms, par ordre de confiance : écrit à la main, puis DNS, puis le nom rapporté "
               "par un équipement SNMP, puis ce qu'un hôte dit de lui-même (NetBIOS, mDNS, "
               "LLMNR). Un bandeau compte les lignes où ils diffèrent ; l'outil ne tranche pas."),
        ("li", "Seen at the last collect, or everything: a MAC table keeps what it learned for "
               "`nodes.retention_days`, so the full list is part inventory, part memory.",
               "Vues à la dernière collecte, ou tout : une table MAC garde ce qu'elle a appris "
               "pendant `nodes.retention_days`, la liste complète est donc moitié inventaire, "
               "moitié mémoire."),
    )),
    ("local", ("Local MACs", "MAC locaux"), (
        ("p", "A MAC whose first byte has its second bit set is locally administered. Phones and "
              "laptops use one to hide their real MAC and change it, so one device can appear "
              "as several nodes. Containers, virtual machines and software interfaces use "
              "them too, and the tool cannot tell which is which.",
              "Une MAC dont le premier octet a son deuxième bit à 1 est administrée localement. "
              "Les téléphones et portables en utilisent une pour masquer leur vraie MAC et la "
              "changent : un même appareil peut apparaître en plusieurs nœuds. Les conteneurs, "
              "machines virtuelles et interfaces logicielles en utilisent aussi, et l'outil ne "
              "sait pas lequel est lequel."),
        ("p", "They carry a \"local MAC\" badge and can be filtered. Nothing is ever merged: two "
              "local MACs on one port are a coincidence of place, not one device. "
              "`export.nodes.local_macs: skip` leaves them out of the export.",
              "Elles portent une pastille « MAC local » et se filtrent. Rien n'est jamais "
              "fusionné : deux MAC locaux sur un même port sont une coïncidence de lieu, pas "
              "un seul appareil. `export.nodes.local_macs: skip` les retire de l'export."),
    )),
    ("churn", ("An address that changes often", "Une adresse qui change souvent"), (
        ("p", "\"Address changes often\" lists the MACs seen with `nodes.ip_churn_min` (3) or "
              "more IPv4 addresses within `nodes.ip_churn_days` (7 days).",
              "« Change souvent d'adresse » liste les MAC vues avec `nodes.ip_churn_min` (3) "
              "adresses IPv4 ou plus dans `nodes.ip_churn_days` (7 jours)."),
        ("p", "It counts and says the address moves. It does not say why: DHCP, several "
              "interfaces and proxy-ARP look the same in an ARP table.",
              "Il compte et dit que l'adresse bouge. Il ne dit pas pourquoi : DHCP, plusieurs "
              "interfaces et proxy-ARP se ressemblent dans une table ARP."),
    )),
    ("export", ("What the export carries", "Ce que l'export contient"), (
        ("li", "`nodes.csv` columns: MAC Address, Vendor, IP Address, DNS Name, Switch, Port, "
               "VLAN, Last Seen. Name and description columns are off by default so that the "
               "shape does not move.",
               "Colonnes de `nodes.csv` : MAC Address, Vendor, IP Address, DNS Name, Switch, "
               "Port, VLAN, Last Seen. Les colonnes nom et description sont désactivées par "
               "défaut pour que la forme ne bouge pas."),
        ("li", "Only nodes seen at the last full collect are exported "
               "(`export.nodes.live_only`): a host gone for three weeks is memory, not "
               "inventory.",
               "Seuls les nœuds vus à la dernière collecte complète sont exportés "
               "(`export.nodes.live_only`) : un hôte parti depuis trois semaines est de la "
               "mémoire, pas de l'inventaire."),
        ("li", "A cell a spreadsheet would run as a formula (`=`, `+`, `-`, `@`) gets a leading "
               "apostrophe (`export.csv.formula_safe`).",
               "Une cellule qu'un tableur exécuterait comme formule (`=`, `+`, `-`, `@`) reçoit "
               "une apostrophe en tête (`export.csv.formula_safe`)."),
        ("li", "The files are in the Files tab, written whole or not at all.",
               "Les fichiers sont dans l'onglet Fichiers, écrits en entier ou pas du tout."),
    )),
    ("limits", ("Limits worth knowing", "Limites à connaître"), (
        ("li", "A MAC table says where a MAC was heard, not that the host is there now.",
               "Une table MAC dit où une MAC a été entendue, pas que l'hôte y est maintenant."),
        ("li", "A MAC seen with more than `nodes.max_ips_per_mac` (3) addresses within a day, or "
               "two addresses at the same instant, is given no IP in the export: an empty "
               "cell rather than the wrong address.",
               "Une MAC vue avec plus de `nodes.max_ips_per_mac` (3) adresses en un jour, ou "
               "deux adresses au même instant, n'a pas d'IP dans l'export : une cellule vide "
               "plutôt que la mauvaise adresse."),
        ("li", "The VRF of an ARP entry is not collected: an address is said to have changed "
               "hands only when one device listed both MACs for it.",
               "Le VRF d'une entrée ARP n'est pas collecté : une adresse n'est dite reprise que "
               "si un même équipement a listé les deux MAC."),
        ("li", "The tool reads; it never changes a device, a name in DNS or a switch port.",
               "L'outil lit ; il ne modifie jamais un équipement, un nom DNS ou un port."),
    )),
)

_CODE = re.compile(r"`([^`]+)`")


def inline(text: str) -> str:
    """Escape first, then turn `spans` into code: the text itself can never add markup."""
    return _CODE.sub(lambda m: f"<code>{m.group(1)}</code>", esc(text))


def render(lang: str) -> str:
    index = 2 if lang == "fr" else 1
    toc = "".join(f'<a href="#{key}">{esc(title[index - 1])}</a>' for key, title, _b in SECTIONS)
    parts = [f'<nav class="doctoc">{toc}</nav>']
    for key, title, blocks in SECTIONS:
        parts.append(f'<section class="doc" id="{key}"><h2>{esc(title[index - 1])}</h2>')
        items: list[str] = []
        for block in blocks:
            if block[0] == "li":
                items.append(f"<li>{inline(block[index])}</li>")
                continue
            if items:
                parts.append(f"<ul>{''.join(items)}</ul>")
                items = []
            parts.append(f"<p>{inline(block[index])}</p>")
        if items:
            parts.append(f"<ul>{''.join(items)}</ul>")
        parts.append("</section>")
    return "".join(parts)
