"""Strings of the terminal interface and of ``explain``, in English and French."""

from __future__ import annotations

import os

# key -> (English, French)
STRINGS: dict[str, tuple[str, str]] = {
    # application
    "app.subtitle": ("read-only network mapper", "cartographie réseau en lecture seule"),
    "status.never": ("no collect yet", "aucune collecte pour l'instant"),
    "status.last": ("last collect {when} · {status} · {ok}/{total} reachable",
                    "dernière collecte {when} · {status} · {ok}/{total} joignables"),
    "status.running": ("collect running", "collecte en cours"),
    "creds.error": ("Credentials cannot be read: {error}. Browsing works, SNMP actions are "
                    "disabled until it is fixed.",
                    "Identifiants illisibles : {error}. La consultation fonctionne, les actions "
                    "SNMP sont désactivées tant que ce n'est pas corrigé."),
    # tabs
    "tab.devices": ("Devices", "Équipements"),
    "tab.runs": ("Runs", "Collectes"),
    "tab.nodes": ("Nodes", "Nœuds"),
    "tab.links": ("Links", "Liens"),
    "tab.extensions": ("Extensions", "Extensions"),
    "tab.reports": ("Reports", "Rapports"),
    "key.new_report": ("New report", "Nouveau rapport"),
    "key.export_report": ("Export", "Exporter"),
    "key.export": ("Export", "Exporter"),
    "key.reload": ("Reload data", "Recharger les données"),
    "col.source": ("Source", "Source"),
    "col.format": ("Format", "Format"),
    "col.schedule": ("Schedule", "Planification"),
    "col.push": ("Push", "Envoi"),
    "col.title": ("Title", "Titre"),
    "rep.none": ("No report yet. Press n to build one: pick a dataset, tick columns, add "
                 "filters and watch the preview.",
                 "Aucun rapport. Appuyez sur n pour en construire un : choisissez un jeu de "
                 "données, cochez les colonnes, ajoutez des filtres et regardez l'aperçu."),
    "rep.count": ("{count} report(s) — ⏎ open · n new · x export · del delete a report created "
                  "here", "{count} rapport(s) — ⏎ ouvrir · n nouveau · x exporter · suppr "
                  "supprimer un rapport créé ici"),
    "rep.title_new": ("New report", "Nouveau rapport"),
    "rep.title_edit": ("Report {name}", "Rapport {name}"),
    "rep.from_file": ("Defined in {origin}: changes are previewed and exported here but must be "
                      "saved in that file (or saved here under another name).",
                      "Défini dans {origin} : les modifications sont prévisualisées et exportées "
                      "ici mais doivent être enregistrées dans ce fichier (ou ici sous un autre "
                      "nom)."),
    "rep.name": ("Name", "Nom"),
    "rep.report_title": ("Title", "Titre"),
    "rep.source": ("Data", "Données"),
    "rep.sql_source": ("SQL query (read-only)", "Requête SQL (lecture seule)"),
    "rep.unknown": ("unknown", "inconnu"),
    "rep.format": ("Format", "Format"),
    "rep.limit": ("Row limit", "Limite de lignes"),
    "rep.no_limit": ("none", "aucune"),
    "rep.schedule": ("Schedule (cron)", "Planification (cron)"),
    "rep.allow_empty": ("Write when empty", "Écrire si vide"),
    "rep.columns": ("Columns", "Colonnes"),
    "rep.filters": ("Filters (all must match)", "Filtres (tous doivent correspondre)"),
    "rep.add_filter": ("+ Add a filter", "+ Ajouter un filtre"),
    "rep.field": ("field", "champ"),
    "rep.value": ("value (list: a, b)", "valeur (liste : a, b)"),
    "rep.sort": ("Sort", "Tri"),
    "rep.sort_placeholder": ("vendor, -last_seen  (- = descending)",
                             "vendor, -last_seen  (- = décroissant)"),
    "rep.sql": ("SQL query", "Requête SQL"),
    "rep.sql_tables": ("Tables: {tables}. Helpers: iso(time), age_days(time), now().",
                       "Tables : {tables}. Fonctions : iso(temps), age_days(temps), now()."),
    "rep.push": ("Push to", "Envoyer vers"),
    "rep.export": ("Export now", "Exporter maintenant"),
    "rep.preview_invalid": ("Preview paused: fix the definition (see below the form).",
                            "Aperçu en pause : corrigez la définition (voir sous le formulaire)."),
    "rep.preview_count": ("Preview: {shown} of {total} row(s)",
                          "Aperçu : {shown} ligne(s) sur {total}"),
    "rep.preview_limited": ("the file keeps the first {limit}",
                            "le fichier garde les {limit} premières"),
    "rep.name_required": ("Give the report a name (lowercase letters, digits, - and _).",
                          "Donnez un nom au rapport (minuscules, chiffres, - et _)."),
    "rep.file_name": ("{name} is defined in an extension file: choose another name.",
                      "{name} est défini dans un fichier d'extension : choisissez un autre nom."),
    "rep.exists": ("A report named {name} already exists.",
                   "Un rapport nommé {name} existe déjà."),
    "rep.saved": ("{name} saved.", "{name} enregistré."),
    "rep.schedule_hint": ("Its schedule becomes active once the crontab is regenerated "
                          "(snowth_my_net cron print, or restart the container).",
                          "Sa planification devient active quand la crontab est régénérée "
                          "(snowth_my_net cron print, ou redémarrage du conteneur)."),
    "rep.empty": ("{name} has no row: nothing written (tick “Write when empty” to write it "
                  "anyway).", "{name} n'a aucune ligne : rien n'est écrit (cochez « Écrire si "
                  "vide » pour l'écrire quand même)."),
    "rep.written": ("Wrote {path} ({rows} row(s))", "{path} écrit ({rows} ligne(s))"),
    "rep.confirm_push": ("Also push the report to {targets}?",
                         "Envoyer aussi le rapport vers {targets} ?"),
    "rep.file_delete": ("{name} comes from {origin}: edit or delete it in that file.",
                        "{name} vient de {origin} : modifiez-le ou supprimez-le dans ce fichier."),
    "rep.confirm_delete": ("Delete the report {name}? Files already written are kept.",
                           "Supprimer le rapport {name} ? Les fichiers déjà écrits sont gardés."),
    "op.eq": ("equals", "égal à"),
    "op.ne": ("differs from", "différent de"),
    "op.contains": ("contains", "contient"),
    "op.not_contains": ("does not contain", "ne contient pas"),
    "op.startswith": ("starts with", "commence par"),
    "op.endswith": ("ends with", "finit par"),
    "op.regex": ("matches regex", "correspond à la regex"),
    "op.gt": ("greater than", "plus grand que"),
    "op.ge": ("at least", "au moins"),
    "op.lt": ("less than", "plus petit que"),
    "op.le": ("at most", "au plus"),
    "op.empty": ("is empty", "est vide"),
    "op.not_empty": ("is not empty", "n'est pas vide"),
    "op.in": ("is one of", "est parmi"),
    "op.not_in": ("is none of", "n'est aucun de"),
    "op.older_than": ("older than (7d, 12h)", "plus ancien que (7d, 12h)"),
    "op.newer_than": ("newer than (7d, 12h)", "plus récent que (7d, 12h)"),
    "tab.custom": ("Custom", "Personnalisé"),
    "custom.none": ("No custom value for this device. Create a collector from the OID tester "
                    "(“Save as custom OID”) or in extensions/*.yml.",
                    "Aucune valeur personnalisée pour cet équipement. Créez un collecteur depuis "
                    "le testeur d'OID (« Enregistrer comme OID personnalisé ») ou dans "
                    "extensions/*.yml."),
    "col.collector": ("COLLECTOR", "COLLECTEUR"),
    "col.index": ("INDEX", "INDEX"),
    "col.column": ("VALUE NAME", "NOM"),
    "col.value": ("VALUE", "VALEUR"),
    "col.kind": ("KIND", "TYPE"),
    "col.scope": ("APPLIES TO", "S'APPLIQUE À"),
    "col.origin": ("ORIGIN", "ORIGINE"),
    "col.description": ("DESCRIPTION", "DESCRIPTION"),
    "ext.count": ("{count} collector(s) — ⏎ details, del deletes a collector created here",
                  "{count} collecteur(s) — ⏎ détails, suppr supprime un collecteur créé ici"),
    "ext.origin_tui": ("created in the interface", "créé dans l'interface"),
    "ext.all": ("all devices", "tous les équipements"),
    "ext.file_delete": ("{name} comes from {origin}: edit or delete it in that file.",
                        "{name} vient de {origin} : modifiez-le ou supprimez-le dans ce fichier."),
    "ext.confirm_delete": ("Delete the collector {name} and the values it read?",
                           "Supprimer le collecteur {name} et les valeurs lues ?"),
    "ext.deleted": ("{name} deleted", "{name} supprimé"),
    "ext.last_pass": ("last pass {when}: {status}", "dernier passage {when} : {status}"),
    "save.button": ("Save as custom OID", "Enregistrer comme OID personnalisé"),
    "save.title": ("New custom collector", "Nouveau collecteur personnalisé"),
    "save.nothing": ("Run a successful test first (a preset or an OID).",
                     "Lancez d'abord un test réussi (préréglage ou OID)."),
    "save.enterprise": ("The vendor sub-tree preset cannot be saved: test a precise OID.",
                        "Le préréglage « sous-arbre du constructeur » ne peut pas être "
                        "enregistré : testez un OID précis."),
    "save.name": ("Name", "Nom"),
    "save.column": ("Value name", "Nom de la valeur"),
    "save.type": ("Interpret as", "Interpréter comme"),
    "save.scope": ("Read on", "Lire sur"),
    "save.description": ("Description", "Description"),
    "save.scope_device": ("this device only ({address})", "cet équipement seulement ({address})"),
    "save.scope_vendor": ("every {vendor} device", "tous les équipements {vendor}"),
    "save.scope_type": ("every {type}", "tous les équipements de type {type}"),
    "save.scope_all": ("every device", "tous les équipements"),
    "save.what": ("{kind} of {count} value(s): {oids}", "{kind} de {count} valeur(s) : {oids}"),
    "save.exists": ("A collector named {name} already exists.",
                    "Un collecteur nommé {name} existe déjà."),
    "save.done": ("{name} saved; it will be read at the next collect (c to collect now).",
                  "{name} enregistré ; il sera lu à la prochaine collecte (c pour collecter "
                  "maintenant)."),
    "tab.neighbors": ("Neighbors", "Voisins"),
    "col.local_device": ("LOCAL DEVICE", "ÉQUIPEMENT"),
    "col.local_port": ("LOCAL PORT", "PORT LOCAL"),
    "col.remote_device": ("REMOTE DEVICE", "ÉQUIPEMENT DISTANT"),
    "col.remote_port": ("REMOTE PORT", "PORT DISTANT"),
    "col.protocol": ("PROTOCOL", "PROTOCOLE"),
    "col.caps": ("CAPABILITIES", "CAPACITÉS"),
    "col.role": ("PORT ROLE", "RÔLE DU PORT"),
    "links.count": ("{count} link(s); phones and stations are hidden",
                    "{count} lien(s) ; téléphones et postes masqués"),
    "neighbors.none": ("No LLDP/CDP neighbor known for this device.",
                       "Aucun voisin LLDP/CDP connu pour cet équipement."),
    "role.access": ("access", "accès"),
    "role.uplink": ("uplink", "uplink"),
    "remote.polled": ("polled", "interrogé"),
    "remote.not_polled": ("not polled", "non interrogé"),
    "nodes.placeholder": ("Search a MAC, IP, DNS name, switch, port, VLAN, vendor…",
                          "Chercher une MAC, IP, nom DNS, switch, port, VLAN, constructeur…"),
    "nodes.count": ("{shown} of {total} rows — ⏎ explains where a MAC is and why",
                    "{shown} lignes sur {total} — ⏎ explique où est une MAC et pourquoi"),
    "nodes.truncated": ("only the first {limit} rows are shown; refine the search",
                        "seules les {limit} premières lignes sont affichées ; "
                        "affinez la recherche"),
    "col.mac": ("MAC", "MAC"),
    "col.dns": ("DNS NAME", "NOM DNS"),
    "col.switch": ("SWITCH", "SWITCH"),
    "col.port": ("PORT", "PORT"),
    "col.vlan": ("VLAN", "VLAN"),
    "explain.title": ("Why is {mac} here?", "Pourquoi {mac} est-elle ici ?"),
    "tab.identity": ("Identity", "Identité"),
    "tab.settings": ("Settings", "Réglages"),
    "tab.tester": ("OID tester", "Testeur d'OID"),
    "tab.last": ("Last collect", "Dernière collecte"),
    # bindings
    "key.quit": ("Quit", "Quitter"),
    "key.help": ("Help", "Aide"),
    "key.open": ("Open", "Ouvrir"),
    "key.filter": ("Filter", "Filtrer"),
    "key.collect_all": ("Collect all", "Tout collecter"),
    "key.collect_one": ("Collect", "Collecter"),
    "key.add": ("Add", "Ajouter"),
    "key.remove": ("Remove", "Retirer"),
    "key.refresh": ("Refresh", "Rafraîchir"),
    "key.back": ("Back", "Retour"),
    "key.save": ("Save", "Enregistrer"),
    # devices table
    "col.name": ("NAME", "NOM"),
    "col.ip": ("IP", "IP"),
    "col.type": ("TYPE", "TYPE"),
    "col.vendor": ("VENDOR", "CONSTRUCTEUR"),
    "col.model": ("MODEL", "MODÈLE"),
    "col.status": ("STATUS", "ÉTAT"),
    "col.seen": ("LAST SEEN", "VU LE"),
    "filter.placeholder": ("Filter by name, IP, type, vendor, model…",
                           "Filtrer par nom, IP, type, constructeur, modèle…"),
    "devices.empty": ("No device yet. Press [b]a[/b] to add one, or [b]c[/b] to collect the seeds "
                      "of config.yml.",
                      "Aucun équipement. [b]a[/b] pour en ajouter un, ou [b]c[/b] pour collecter "
                      "les points de départ de config.yml."),
    "devices.legend": ("✎ type set by hand · ⚙ type from config.yml · ? no sure evidence",
                       "✎ type réglé à la main · ⚙ type de config.yml · ? pas de preuve sûre"),
    "st.ok": ("ok", "ok"),
    "st.partial": ("partial", "partiel"),
    "st.failed": ("silent", "muet"),
    "st.never": ("not polled yet", "jamais interrogé"),
    # runs
    "col.run": ("RUN", "N°"),
    "col.command": ("COMMAND", "COMMANDE"),
    "col.started": ("STARTED", "DÉBUT"),
    "col.duration": ("DURATION", "DURÉE"),
    "col.result": ("RESULT", "RÉSULTAT"),
    "col.devices": ("DEVICES", "ÉQUIPEMENTS"),
    # identity
    "id.name": ("Name", "Nom"),
    "id.address": ("Address", "Adresse"),
    "id.sysname": ("sysName", "sysName"),
    "id.descr": ("Description", "Description"),
    "id.vendor": ("Vendor", "Constructeur"),
    "id.model": ("Model", "Modèle"),
    "id.serial": ("Serial", "Numéro de série"),
    "id.os": ("Operating system", "Système"),
    "id.mac": ("Base MAC", "MAC de base"),
    "id.location": ("Location", "Emplacement"),
    "id.contact": ("Contact", "Contact"),
    "id.credential": ("SNMP credential", "Identifiant SNMP"),
    "id.driver": ("Vendor driver", "Driver constructeur"),
    "id.type": ("Type", "Type"),
    "id.why": ("Why this type", "Pourquoi ce type"),
    "id.no_type": ("empty — no sure evidence; set it by hand in Settings",
                   "vide — pas de preuve sûre ; réglable à la main dans Réglages"),
    "id.seen": ("Last seen", "Vu pour la dernière fois"),
    "id.never": ("This device never answered.", "Cet équipement n'a jamais répondu."),
    "id.last_error": ("Last error", "Dernière erreur"),
    # settings
    "set.intro": ("The type is only a label: it never prevents a collection. ARP, MAC tables, "
                  "LLDP and CDP are always attempted, unless a function is set to [b]off[/b].",
                  "Le type n'est qu'une étiquette : il n'empêche aucune collecte. ARP, tables "
                  "MAC, LLDP et CDP sont toujours tentés, sauf fonction réglée sur [b]off[/b]."),
    "set.type": ("Type", "Type"),
    "set.name": ("Name in outputs", "Nom dans les sorties"),
    "set.credential": ("SNMP credential", "Identifiant SNMP"),
    "set.disabled": ("Do not poll", "Ne pas interroger"),
    "set.tolerate": ("Failure is not an error", "Panne tolérée"),
    "set.functions": ("Collected functions", "Fonctions collectées"),
    "set.snmp": ("SNMP tuning", "Réglages SNMP"),
    "set.max_repetitions": ("GETBULK size", "Taille GETBULK"),
    "set.pace_ms": ("Pause between requests (ms)", "Pause entre requêtes (ms)"),
    "set.use_bulk": ("Use GETBULK", "Utiliser GETBULK"),
    "set.auto": ("Automatic", "Automatique"),
    "set.auto_detected": ("Automatic — detected: {value}", "Automatique — détecté : {value}"),
    "set.auto_config": ("Default — config.yml: {value}", "Par défaut — config.yml : {value}"),
    "set.cred_order": ("Automatic (configuration order)", "Automatique (ordre de la config)"),
    "set.name_placeholder": ("sysName without domain", "sysName sans domaine"),
    "set.save": ("Save", "Enregistrer"),
    "set.reset": ("Back to automatic", "Revenir à l'automatique"),
    "set.saved": ("Settings saved", "Réglages enregistrés"),
    "set.nothing": ("Nothing changed", "Aucun changement"),
    "set.reset_done": ("Manual settings removed", "Réglages manuels retirés"),
    "src.manual": ("manual", "manuel"),
    "src.config": ("config.yml", "config.yml"),
    "src.default": ("default", "défaut"),
    "mode.auto": ("auto — try, silent if absent", "auto — tenter, silencieux si absent"),
    "mode.force": ("force — absence is an error", "force — absence = erreur"),
    "mode.off": ("off — never query", "off — ne jamais interroger"),
    "feat.entity": ("Chassis (ENTITY-MIB)", "Châssis (ENTITY-MIB)"),
    "feat.interfaces": ("Interfaces", "Interfaces"),
    "feat.ipaddr": ("Device IP addresses", "Adresses IP de l'équipement"),
    "feat.fdb": ("MAC tables (FDB)", "Tables MAC (FDB)"),
    "feat.arp": ("ARP tables", "Tables ARP"),
    "feat.lldp": ("LLDP neighbors", "Voisins LLDP"),
    "feat.cdp": ("CDP neighbors", "Voisins CDP"),
    "confirm.disable": ("Stop polling {name}? It stays in the inventory with its history.",
                        "Ne plus interroger {name} ? Il reste dans l'inventaire avec son "
                        "historique."),
    # tester
    "tester.presets": ("Presets — ★ suggested for the type",
                       "Préréglages — ★ proposés pour le type"),
    "tester.oid_placeholder": ("OID, e.g. 1.3.6.1.2.1.1.5.0", "OID, ex. 1.3.6.1.2.1.1.5.0"),
    "tester.run": ("Test", "Tester"),
    "tester.mode_auto": ("GET, else walk", "GET, sinon walk"),
    "tester.limit": ("rows", "lignes"),
    "tester.connecting": ("Connecting to {target}…", "Connexion à {target}…"),
    "tester.unreachable": ("Unreachable: {error}", "Injoignable : {error}"),
    "tester.running": ("{what}…", "{what}…"),
    "tester.result": ("{title} — {status}, {rows} row(s), {requests} request(s), {ms} ms",
                      "{title} — {status}, {rows} ligne(s), {requests} requête(s), {ms} ms"),
    "tester.truncated": ("stopped at {limit} rows per column",
                         "arrêt à {limit} lignes par colonne"),
    "tester.hint": ("Pick a preset, or type an OID and press Enter. Everything is read-only.",
                    "Choisissez un préréglage, ou tapez un OID puis Entrée. Tout est en lecture "
                    "seule."),
    "tester.bad_oid": ("Not a numeric OID: {text}", "Pas un OID numérique : {text}"),
    "tester.no_creds": ("SNMP actions are disabled: credentials cannot be read.",
                        "Actions SNMP désactivées : identifiants illisibles."),
    # last collect
    "last.function": ("FUNCTION", "FONCTION"),
    "last.status": ("STATUS", "ÉTAT"),
    "last.rows": ("ROWS", "LIGNES"),
    "last.time": ("TIME", "DURÉE"),
    "last.detail": ("DETAIL", "DÉTAIL"),
    "last.none": ("No collect for this device yet.", "Aucune collecte pour cet équipement."),
    "last.when": ("Collect of {when}", "Collecte du {when}"),
    # collect modal
    "collect.title_all": ("Collect — all devices", "Collecte — tous les équipements"),
    "collect.title_one": ("Collect — {target}", "Collecte — {target}"),
    "collect.busy": ("Another run holds the state: {error}",
                     "Une autre exécution tient l'état : {error}"),
    "type.switch": ("switch", "switch"),
    "type.router": ("router", "routeur"),
    "type.firewall": ("firewall", "pare-feu"),
    "type.wireless": ("wireless", "sans-fil"),
    "type.server": ("server", "serveur"),
    "type.printer": ("printer", "imprimante"),
    "type.facility": ("facility (power, cooling)", "infrastructure (énergie, climatisation)"),
    "type.other": ("other", "autre"),
    "collect.done": ("Finished: {status} — {devices} device(s), {reachable} reachable, "
                     "{failing} failing, {duration}s",
                     "Terminé : {status} — {devices} équipement(s), {reachable} joignable(s), "
                     "{failing} en échec, {duration} s"),
    "collect.close": ("Close", "Fermer"),
    "collect.running": ("Collecting… logs below", "Collecte en cours… journal ci-dessous"),
    # add / remove
    "add.title": ("Add a device", "Ajouter un équipement"),
    "add.placeholder": ("IP address, or IP:port", "Adresse IP, ou IP:port"),
    "add.hint": ("It will be polled at the next collect (or press c now).",
                 "Il sera interrogé à la prochaine collecte (ou c tout de suite)."),
    "add.invalid": ("Not a valid address: {error}", "Adresse invalide : {error}"),
    "add.excluded": ("{target} is inside discovery.exclude", "{target} est dans discovery.exclude"),
    "add.done": ("{target} added", "{target} ajouté"),
    "remove.confirm": ("Forget {name}? Its history and manual settings are deleted.",
                       "Oublier {name} ? Son historique et ses réglages manuels sont supprimés."),
    "remove.seed": ("{name} is a seed of config.yml and will come back. Prefer “Do not poll” "
                    "in its settings.",
                    "{name} est un point de départ de config.yml et reviendra. Préférez « Ne pas "
                    "interroger » dans ses réglages."),
    "remove.done": ("{name} forgotten", "{name} oublié"),
    "yes": ("Yes", "Oui"),
    "no": ("Cancel", "Annuler"),
    "ok": ("OK", "OK"),
    # help
    "help.title": ("snowth_my_net — help", "snowth_my_net — aide"),
    "help.body": (
        "[b]Everywhere[/b]\n"
        "  ?  this help        ctrl+p  command palette (themes…)        q  quit\n\n"
        "[b]Devices[/b]\n"
        "  ⏎  open the device    /  filter    r  refresh\n"
        "  c  collect all        a  add       del  remove\n\n"
        "[b]Reports[/b]\n"
        "  ⏎  open the builder    n  new report    x  export    del  delete\n"
        "  In the builder: ctrl+s save · ctrl+e export now · ctrl+r reload data\n\n"
        "[b]Device[/b]\n"
        "  esc  back    c  collect this device    ctrl+s  save settings\n"
        "  Tabs: Identity · Settings · OID tester · Last collect\n\n"
        "[b]Good to know[/b]\n"
        "  • Everything snowth_my_net sends to devices is read-only (GET, GETNEXT, GETBULK).\n"
        "  • The type never blocks a collection: set functions to force/off instead.\n"
        "  • Settings made here win over config.yml and apply at once to the outputs.\n"
        "  • Secrets are never shown.",
        "[b]Partout[/b]\n"
        "  ?  cette aide        ctrl+p  palette de commandes (thèmes…)        q  quitter\n\n"
        "[b]Équipements[/b]\n"
        "  ⏎  ouvrir la fiche    /  filtrer    r  rafraîchir\n"
        "  c  tout collecter     a  ajouter    suppr  retirer\n\n"
        "[b]Rapports[/b]\n"
        "  ⏎  ouvrir le constructeur    n  nouveau rapport    x  exporter    suppr  supprimer\n"
        "  Dans le constructeur : ctrl+s enregistrer · ctrl+e exporter · ctrl+r recharger\n\n"
        "[b]Fiche équipement[/b]\n"
        "  échap  retour    c  collecter cet équipement    ctrl+s  enregistrer les réglages\n"
        "  Onglets : Identité · Réglages · Testeur d'OID · Dernière collecte\n\n"
        "[b]Bon à savoir[/b]\n"
        "  • Tout ce que snowth_my_net envoie aux équipements est en lecture seule (GET, "
        "GETNEXT, GETBULK).\n"
        "  • Le type ne bloque jamais une collecte : réglez les fonctions en force/off.\n"
        "  • Les réglages faits ici priment sur config.yml et s'appliquent aussitôt aux "
        "sorties.\n"
        "  • Les secrets ne sont jamais affichés."),
}


EXPLAIN = {
    # explain <mac|ip>: the same text in the CLI (English) and in the interface (its language)
    "xp.not_found": ("{query}: not seen in any MAC or ARP table within the retention period",
                     "{query} : vue dans aucune table MAC ou ARP pendant la rétention"),
    "xp.title": ("MAC {mac} — {vendor} ({kind})", "MAC {mac} — {vendor} ({kind})"),
    "xp.vendor_unknown": ("unknown vendor", "constructeur inconnu"),
    "xp.random": ("locally administered (random or virtual)",
                  "administrée localement (aléatoire ou virtuelle)"),
    "xp.universal": ("universally administered", "administrée mondialement"),
    "xp.not_node": ("Not a node: {reason}", "Pas un nœud : {reason}"),
    "xp.position": ("Current position", "Position actuelle"),
    "xp.position_value": ("{where}{vlan} — last seen {when}",
                          "{where}{vlan} — vue pour la dernière fois {when}"),
    "xp.position_none": ("none (no access port known)", "aucune (aucun port d'accès connu)"),
    "xp.vlan": (" VLAN {vlan}", " VLAN {vlan}"),
    "xp.rule": ("Rule", "Règle"),
    "xp.rule_access": ("access port ({count} MAC(s) on the port)",
                       "port d'accès ({count} MAC sur le port)"),
    "xp.rule_transit": ("; {count} simultaneous sighting(s) on ports with more MACs treated as "
                        "transit (window {minutes} min)",
                        " ; {count} observation(s) simultanée(s) sur des ports avec plus de MAC "
                        "traitées comme du transit (fenêtre {minutes} min)"),
    "xp.rule_uplinks": ("; {count} uplink sighting(s) discarded",
                        " ; {count} observation(s) sur uplink écartée(s)"),
    "xp.rule_fallback": ("seen only on soft uplinks: placed on the one with the fewest MACs "
                         "(uplink_fallback)",
                         "vue seulement sur des uplinks souples : placée sur celui qui porte le "
                         "moins de MAC (uplink_fallback)"),
    "xp.rule_uplinks_only": ("seen only on uplinks: no position (set nodes.uplink_fallback, or "
                             "declare the port in access_ports)",
                             "vue seulement sur des uplinks : pas de position (activez "
                             "nodes.uplink_fallback, ou déclarez le port dans access_ports)"),
    "xp.rule_arp_only": ("never seen in a MAC table: known from ARP only",
                         "jamais vue dans une table MAC : connue par l'ARP seulement"),
    "xp.fdb_title": ("MAC table sightings (retention {days} d)",
                     "Observations dans les tables MAC (rétention {days} j)"),
    "xp.none": ("  none", "  aucune"),
    "xp.verdict_current": ("current position", "position actuelle"),
    "xp.verdict_previous": ("previous position (roaming)", "position précédente (itinérance)"),
    "xp.verdict_fallback": ("behind soft uplink: {reasons}",
                            "derrière un uplink souple : {reasons}"),
    "xp.verdict_transit": ("transit (same time on {where}, fewer MACs)",
                           "transit (au même moment sur {where}, moins de MAC)"),
    "xp.verdict_uplink": ("uplink: {reasons}", "uplink : {reasons}"),
    "xp.arp_title": ("ARP sightings", "Observations ARP"),
    "xp.current_ip": ("← current IP", "← IP actuelle"),
    "xp.superseded": ("superseded (now {mac})", "remplacée (maintenant {mac})"),
    "xp.dns": ("DNS  {name}", "DNS  {name}"),
    "xp.dns_none": ("(no PTR name cached)", "(aucun nom PTR en cache)"),
    # why a port is an uplink or an access port (codes come from the merge)
    "xp.reason.config": ("declared in uplinks", "déclaré dans uplinks"),
    "xp.reason.config_access": ("declared in access_ports", "déclaré dans access_ports"),
    "xp.reason.lag": ("link aggregation", "agrégation de liens"),
    "xp.reason.mac_count": ("{detail}", "trop de MAC ({detail})"),
    "xp.reason.neighbor_managed": ("neighbor {detail}", "voisin {detail}"),
    "xp.reason.neighbor_infra": ("neighbor {detail}", "voisin {detail}"),
    # why a MAC is not a node
    "xp.excl.multicast": ("multicast or broadcast address", "adresse multicast ou broadcast"),
    "xp.excl.device_mac": ("MAC of a polled device ({detail})",
                           "MAC d'un équipement interrogé ({detail})"),
    "xp.excl.ignored_mac": ("listed in nodes.ignore_macs", "listée dans nodes.ignore_macs"),
    "xp.excl.ignored_prefix": ("matches nodes.ignore_mac_prefixes ({detail})",
                               "correspond à nodes.ignore_mac_prefixes ({detail})"),
}
STRINGS.update(EXPLAIN)


def detect_language(setting: str = "auto") -> str:
    if setting in ("en", "fr"):
        return setting
    for var in ("LC_ALL", "LC_MESSAGES", "LANG"):
        value = os.environ.get(var, "")
        if value:
            return "fr" if value.lower().startswith("fr") else "en"
    return "en"


class Translator:
    def __init__(self, lang: str) -> None:
        self.lang = lang
        self._index = 1 if lang == "fr" else 0

    def __call__(self, key: str, **kwargs: object) -> str:
        text = STRINGS[key][self._index]
        return text.format(**kwargs) if kwargs else text
