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
    "col.os": ("OS", "SYSTÈME"),
    "col.file": ("FILE", "FICHIER"),
    "col.size": ("BYTES", "OCTETS"),
    "col.written": ("WRITTEN", "ÉCRIT LE"),
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


WEB = {
    # web interface: read-only, it shows the same views as the exports
    "web.title": ("snowth_my_net", "snowth_my_net"),
    "web.search": ("Filter… (/)", "Filtrer… (/)"),
    "web.shown": ("{shown} of {total}", "{shown} sur {total}"),
    "web.count": ("{total} row(s)", "{total} ligne(s)"),
    "web.truncated": ("first {limit} shown; use the exported file for the rest",
                      "les {limit} premières ; le fichier exporté contient le reste"),
    "web.tab.files": ("Files", "Fichiers"),
    "web.no_devices": ("No device yet. Run a collect, then reload this page.",
                       "Aucun équipement. Lancez une collecte, puis rechargez cette page."),
    "web.no_nodes": ("No node yet: the MAC and ARP tables are read during a collect.",
                     "Aucun nœud : les tables MAC et ARP sont lues pendant une collecte."),
    "web.no_links": ("No link found: LLDP or CDP must be enabled on the devices.",
                     "Aucun lien : LLDP ou CDP doit être actif sur les équipements."),
    "web.no_runs": ("No run yet.", "Aucune collecte pour l'instant."),
    "web.no_files": ("No exported file yet. Run an export.",
                     "Aucun fichier exporté. Lancez un export."),
    "web.node_title": ("Node {mac}", "Nœud {mac}"),
    "web.back": ("Back", "Retour"),
    "web.read_only": ("Read-only view. Collect and export from the command line or the terminal "
                      "interface.",
                      "Vue en lecture seule. Collecte et export depuis la ligne de commande ou "
                      "l'interface en terminal."),
    "web.not_found": ("Nothing here.", "Rien ici."),
    "web.how": ("How to read this table", "Comment lire ce tableau"),
    "web.theme": ("Light or dark", "Clair ou sombre"),
    "web.positions": ("{count} positions", "{count} positions"),
    "web.more_ips": (" +{count} more", " +{count} autres"),
    "web.more_macs": ("+{count} MAC", "+{count} MAC"),
    # devices
    "hint.devices.name": (
        "sysName, cut at the first dot; ' (IP)' is added when two devices share a name. It is "
        "the join key used by the Nodes and Links tables.",
        "Le sysName, coupé au premier point ; « (IP) » est ajouté quand deux équipements portent "
        "le même nom. C'est la clé de jointure des tableaux Nœuds et Liens."),
    "hint.devices.ip": (
        "The address actually polled, the one written in the configuration or found through a "
        "neighbour.",
        "L'adresse réellement interrogée, celle de la configuration ou trouvée par un voisin."),
    "hint.devices.vendor": (
        "From the private enterprise number of sysObjectID, else from sysDescr, else from the "
        "MAC address.",
        "D'après le numéro de constructeur du sysObjectID, sinon le sysDescr, sinon l'adresse "
        "MAC."),
    "hint.devices.model": (
        "ENTITY-MIB chassis, else a pattern on sysDescr, else a vendor driver.",
        "Le châssis d'ENTITY-MIB, sinon un motif sur le sysDescr, sinon un driver constructeur."),
    "hint.devices.os": (
        "Recognised from sysDescr or sysObjectID; a driver fills the version when the standard "
        "MIBs do not give it.",
        "Reconnu d'après le sysDescr ou le sysObjectID ; un driver complète la version quand les "
        "MIB standard ne la donnent pas."),
    "hint.devices.type": (
        "Only on sure evidence: LLDP capabilities, a function MIB (printer, UPS), the "
        "sysObjectID catalogue, the OS, or set by hand. Empty means nothing proved it.",
        "Seulement sur preuve sûre : capacités LLDP, MIB de fonction (imprimante, onduleur), "
        "catalogue de sysObjectID, système, ou réglage manuel. Vide = rien ne le prouvait."),
    "hint.devices.mac": (
        "Base MAC of the device (bridge or LLDP chassis). '+n MAC' means n more addresses are "
        "known for it, one per interface: a node seen with any of them is not listed as a node.",
        "MAC de base de l'équipement (bridge ou châssis LLDP). « +n MAC » signifie que n autres "
        "adresses lui sont connues, une par interface : un nœud vu avec l'une d'elles n'est pas "
        "listé comme nœud."),
    "hint.devices.status": (
        "Result of the last collect of that device: ok, partial (a table failed) or failed.",
        "Résultat de la dernière collecte de cet équipement : ok, partial (une table a échoué) "
        "ou failed."),
    "hint.devices.seen": ("Last time the device answered.",
                          "Dernière fois que l'équipement a répondu."),
    # nodes
    "hint.nodes.mac": (
        "Learnt in the MAC table of a switch (BRIDGE/Q-BRIDGE) or in the ARP/NDP cache of a "
        "router or firewall. '2 positions' means the same MAC is on several lines: its roaming "
        "history, most recent first.",
        "Apprise dans la table MAC d'un commutateur (BRIDGE/Q-BRIDGE) ou dans le cache ARP/NDP "
        "d'un routeur ou d'un pare-feu. « 2 positions » signale une MAC présente sur plusieurs "
        "lignes : son historique d'itinérance, la plus récente d'abord."),
    "hint.nodes.vendor": (
        "IEEE registry, from the first half of the MAC. Empty for a randomised (locally "
        "administered) address, which phones and laptops now use by default.",
        "Registre IEEE, d'après la première moitié de la MAC. Vide pour une adresse aléatoire "
        "(administrée localement), ce que font aujourd'hui téléphones et portables par défaut."),
    "hint.nodes.ip": (
        "The elected address, in bold, then the other addresses known for that MAC in grey. The "
        "elected one is the most recent seen in an ARP/NDP cache, IPv4 preferred, dropped when "
        "another MAC claimed it later; only it is exported to devices.csv consumers.",
        "L'adresse élue, puis en gris les autres adresses connues pour cette MAC. L'élue est la "
        "plus récente vue dans un cache ARP/NDP, IPv4 de préférence, écartée si une autre MAC "
        "l'a revendiquée depuis ; c'est la seule exportée vers les consommateurs de nodes.csv."),
    "hint.nodes.dns": (
        "Reverse lookup (PTR) of that address, from the cache; empty when DNS is disabled or the "
        "name does not exist.",
        "Résolution inverse (PTR) de cette adresse, depuis le cache ; vide quand le DNS est "
        "désactivé ou que le nom n'existe pas."),
    "hint.nodes.switch": (
        "The device whose MAC table holds that address, on an access port. Empty when the MAC is "
        "only known from an ARP cache, when every port that saw it is an uplink, or when the "
        "switch holding it is not polled.",
        "L'équipement dont la table MAC contient cette adresse, sur un port d'accès. Vide quand "
        "la MAC n'est connue que par un cache ARP, quand tous les ports qui l'ont vue sont des "
        "uplinks, ou quand le commutateur qui la porte n'est pas interrogé."),
    "hint.nodes.port": (
        "The port of that device. A port carrying many MAC addresses, or facing a neighbour "
        "switch, is treated as an uplink and never as a position.",
        "Le port de cet équipement. Un port qui porte beaucoup d'adresses MAC, ou qui fait face "
        "à un commutateur voisin, est traité comme un uplink et jamais comme une position."),
    "hint.nodes.vlan": ("From the MAC table, else the VLAN of the port (PVID).",
                        "D'après la table MAC, sinon le VLAN du port (PVID)."),
    "hint.nodes.seen": (
        "Last time that position was observed. A MAC may appear on several lines: that is its "
        "roaming history, most recent first.",
        "Dernière observation de cette position. Une MAC peut apparaître sur plusieurs lignes : "
        "c'est son historique d'itinérance, la plus récente d'abord."),
    "hint.nodes.click": (
        "Click a MAC to see why it sits there: every sighting, the ports discarded as uplinks or "
        "transit, and all its addresses.",
        "Cliquez une MAC pour savoir pourquoi elle est là : toutes les observations, les ports "
        "écartés comme uplinks ou transit, et toutes ses adresses."),
    # links
    "hint.links.devices": (
        "Both ends as announced by LLDP or CDP; a name that is not in Devices is a neighbour "
        "that is not polled (a phone, a router outside the allowed range).",
        "Les deux extrémités telles qu'annoncées par LLDP ou CDP ; un nom absent des Équipements "
        "est un voisin non interrogé (un téléphone, un routeur hors de la plage autorisée)."),
    "hint.links.protocol": (
        "LLDP, CDP, or both when the two protocols agree on the same link.",
        "LLDP, CDP, ou les deux quand les deux protocoles décrivent le même lien."),
    "hint.links.seen": ("Last collect where both ends still announced each other.",
                        "Dernière collecte où les deux extrémités s'annonçaient encore."),
    # runs and files
    "hint.runs.result": (
        "ok, partial (a device or a table failed) or failed. A tolerated device never turns a "
        "run partial.",
        "ok, partial (un équipement ou une table a échoué) ou failed. Un équipement toléré ne "
        "rend jamais une exécution partielle."),
    "hint.runs.devices": ("Devices that answered, out of those polled.",
                          "Équipements qui ont répondu, sur ceux interrogés."),
    "hint.files.file": (
        "Written by the last export, in the output directory. Click to download.",
        "Écrit par le dernier export, dans le répertoire de sortie. Cliquez pour télécharger."),
    "web.user": ("User", "Utilisateur"),
    "web.password": ("Password", "Mot de passe"),
    "web.sign_in": ("Sign in", "Se connecter"),
    "web.sign_out": ("Sign out", "Se déconnecter"),
    "web.bad_login": ("Wrong user or password.", "Utilisateur ou mot de passe incorrect."),
    "web.too_many": ("Too many attempts. Try again in {seconds} s.",
                     "Trop de tentatives. Réessayez dans {seconds} s."),
    "web.password.title": ("Your password", "Votre mot de passe"),
    "web.password.new": ("New password", "Nouveau mot de passe"),
    "web.password.again": ("New password (again)", "Nouveau mot de passe (à nouveau)"),
    "web.password.save": ("Save", "Enregistrer"),
    "web.password.rule": ("At least {min} characters.", "Au moins {min} caractères."),
    "web.password.mismatch": ("The two passwords differ.",
                              "Les deux mots de passe sont différents."),
    "web.password.forced": ("Choose your own password to go on: this one was invented by the "
                            "interface and printed in the log.",
                            "Choisissez votre propre mot de passe pour continuer : celui-ci a "
                            "été inventé par l'interface et écrit dans le journal."),
    "web.password.from_file": ("The password of this account comes from a file set in the "
                               "configuration (password_file): change it there.",
                               "Le mot de passe de ce compte vient d'un fichier indiqué dans la "
                               "configuration (password_file) : changez-le là."),
}
STRINGS.update(WEB)

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
    "xp.last": ("last", "vue"),
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
