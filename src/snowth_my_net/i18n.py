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
    "col.hostname.manual": ("MANUAL HOSTNAME", "NOM D'HÔTE MANUEL"),
    "col.hostname.dns": ("DNS HOSTNAME", "NOM D'HÔTE DNS"),
    "col.hostname.probe": ("NETBIOS HOSTNAME", "NOM D'HÔTE NETBIOS"),
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
    "web.read_only": ("Reads the state; never writes to a device.",
                      "Lit l'état ; n'écrit jamais sur un équipement."),
    "web.times": ("Times in {zone}; hover one for the stored UTC value",
                  "Heures en {zone} ; survolez-en une pour la valeur UTC stockée"),
    "web.not_found": ("Nothing here.", "Rien ici."),
    "web.how": ("How to read this table", "Comment lire ce tableau"),
    "web.columns": ("Columns", "Colonnes"),
    "web.columns.reset": ("Reset the widths", "Réinitialiser les largeurs"),
    "web.disagree": ("{count} row(s): the hostname written by hand and the one DNS gives "
                     "disagree. One of them is wrong, and which one is not for this tool to "
                     "decide.",
                     "{count} ligne(s) : le nom d'hôte écrit à la main et celui que rend le DNS "
                     "diffèrent. L'un des deux est faux, et ce n'est pas à cet outil de dire "
                     "lequel."),
    "web.disagree.show": ("Show only those", "N'afficher que celles-là"),
    "web.disagree.all": ("Show every row", "Afficher toutes les lignes"),
    "web.view.live": ("Seen at the last collect ({count})",
                      "Vues à la dernière collecte ({count})"),
    "web.view.all": ("Everything, history included ({count})",
                     "Tout, historique compris ({count})"),
    "web.view.stale": ("{count} row(s) are memory: last seen before the last collect.",
                       "{count} ligne(s) sont de la mémoire : vues avant la dernière collecte."),
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
        "Result of the last collect of that device: ok, partial (a table failed), failed, or "
        "never for an address that has never answered. The reason is written beside it, and "
        "these rows are coloured: this is where the device missing from '11/12 reachable' is.",
        "Résultat de la dernière collecte de cet équipement : ok, partial (une table a échoué), "
        "failed, ou never pour une adresse qui n'a jamais répondu. La raison est écrite à côté, "
        "et ces lignes sont colorées : c'est là qu'est l'équipement manquant de "
        "« 11/12 joignables »."),
    "hint.devices.seen": ("Last time the device answered. Empty for an address that never did.",
                          "Dernière fois que l'équipement a répondu. Vide pour une adresse qui "
                          "n'a jamais répondu."),
    # nodes
    "hint.nodes.hostname_manual": (
        "Written here by hand and kept with the MAC address: it wins over the other two, and a "
        "collect never changes it. Empty it to forget it.",
        "Écrit ici à la main et conservé avec l'adresse MAC : il l'emporte sur les deux autres, "
        "et une collecte ne le change jamais. Videz-le pour l'oublier."),
    "hint.nodes.hostname_dns": (
        "The reverse lookup (PTR) of the address in the IP column: what the network says about "
        "this host. Empty when no zone holds that address — 'dns check IP' says which.",
        "La résolution inverse (PTR) de l'adresse de la colonne IP : ce que le réseau dit de cet "
        "hôte. Vide quand aucune zone ne contient cette adresse — « dns check IP » dit laquelle."),
    "hint.nodes.hostname_probe": (
        "What the host answered when asked its own name (names.probe). Weaker evidence than "
        "DNS: a host states what it likes, and the answer is dropped when the MAC it states "
        "contradicts this row's.",
        "Ce que l'hôte a répondu quand on lui a demandé son propre nom (names.probe). Preuve "
        "plus faible que le DNS : un hôte annonce ce qu'il veut, et la réponse est écartée si "
        "la MAC qu'il annonce contredit celle de cette ligne."),
    "hint.nodes.description": (
        "Written by hand, like the name, and kept with the MAC address: what it is for, where "
        "it hangs, whom to call.",
        "Écrite à la main, comme le nom, et conservée avec l'adresse MAC : à quoi ça sert, où "
        "c'est accroché, qui appeler."),
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
        "The elected address, then the other addresses known for that MAC behind a '+n'. The "
        "elected one is the most recent seen in an ARP/NDP cache, IPv4 preferred, dropped when "
        "another MAC claimed it later. A link-local address (fe80::) is never elected: nothing "
        "routes to it. Only the elected one is exported in nodes.csv.",
        "L'adresse élue, puis les autres adresses connues pour cette MAC derrière un « +n ». "
        "L'élue est la plus récente vue dans un cache ARP/NDP, IPv4 de préférence, écartée si "
        "une autre MAC l'a revendiquée depuis. Une adresse lien-local (fe80::) n'est jamais "
        "élue : rien ne route vers elle. Seule l'élue est exportée dans nodes.csv."),
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
    "hint.nodes.live": (
        "A MAC table keeps what it learned for nodes.retention_days, so this list is part "
        "inventory and part memory. 'Seen at the last collect' keeps what was still there the "
        "last time every device was polled.",
        "Une table MAC garde ce qu'elle a appris pendant nodes.retention_days, donc cette liste "
        "est en partie un inventaire, en partie une mémoire. « Vues à la dernière collecte » ne "
        "garde que ce qui était encore là au dernier passage sur tous les équipements."),
    "hint.nodes.seen": (
        "Last time that position was observed, in the time zone of the server (the exports stay "
        "in UTC). A MAC may appear on several lines: that is its roaming history, most recent "
        "first.",
        "Dernière observation de cette position, dans le fuseau du serveur (les exports restent "
        "en UTC). Une MAC peut apparaître sur plusieurs lignes : c'est son historique "
        "d'itinérance, la plus récente d'abord."),
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
    "web.snmp.tab": ("SNMP", "SNMP"),
    "web.snmp.title": ("SNMP connections", "Connexions SNMP"),
    "web.snmp.locked": ("Type your password again to open this page.",
                        "Retapez votre mot de passe pour ouvrir cette page."),
    "web.snmp.open": ("Open", "Ouvrir"),
    "web.snmp.intro": ("Which addresses are polled, with which credential, and why one does "
                       "not answer. A community is never shown here: the state only holds the "
                       "name of a credential, and its value stays in its file.",
                       "Quelles adresses sont interrogées, avec quel identifiant, et pourquoi "
                       "l'une ne répond pas. Une communauté n'est jamais affichée ici : l'état "
                       "ne garde que le nom d'un identifiant, sa valeur reste dans son fichier."),
    "web.snmp.add": ("Add an address", "Ajouter une adresse"),
    "web.snmp.forget": ("Forget the MAC and ARP memory",
                        "Oublier la mémoire MAC et ARP"),
    "web.snmp.forget_why": (
        "A MAC table is remembered for weeks: an old mistake, or a device that has moved, stays "
        "visible for as long. This empties that memory — the devices, the links and the names "
        "given by hand stay — and the next collect fills it from what the network says today.",
        "Une table MAC est mémorisée pendant des semaines : une vieille erreur, ou un "
        "équipement qui a déménagé, reste visible aussi longtemps. Ceci vide cette mémoire — "
        "les équipements, les liens et les noms donnés à la main restent — et la prochaine "
        "collecte la remplit avec ce que dit le réseau aujourd'hui."),
    "web.snmp.forget_do": ("Yes, forget them", "Oui, les oublier"),
    "web.snmp.forgotten": ("Forgotten: {fdb} MAC observation(s), {arp} ARP entry(ies). "
                           "Run a collect to fill them again.",
                           "Oubliées : {fdb} observation(s) MAC, {arp} entrée(s) ARP. "
                           "Lancez une collecte pour les reconstituer."),
    "web.snmp.added": ("{address} will be polled from the next collect on.",
                       "{address} sera interrogée dès la prochaine collecte."),
    "web.snmp.removed": ("{address} is no longer polled.",
                         "{address} n'est plus interrogée."),
    "web.snmp.remove": ("Remove", "Retirer"),
    "web.snmp.test": ("Test", "Tester"),
    "web.snmp.testing": ("Testing {address}…", "Test de {address}…"),
    "web.snmp.any": ("whichever answers", "celui qui répond"),
    "web.snmp.save": ("Apply", "Appliquer"),
    "web.snmp.credentials_from": (
        "Credentials come from the configuration file ({count} declared); this page can choose "
        "one for an address, never create one or show its value.",
        "Les identifiants viennent du fichier de configuration ({count} déclarés) ; cette page "
        "peut en choisir un pour une adresse, jamais en créer un ni afficher sa valeur."),
    "col.address": ("ADDRESS", "ADRESSE"),
    "col.origin": ("ORIGIN", "ORIGINE"),
    "col.credential": ("CREDENTIAL", "IDENTIFIANT"),
    "col.failures": ("FAILURES", "ÉCHECS"),
    "web.tab.unreachable": ("Unreachable", "Inaccessibles"),
    "web.no_unreachable": ("Nothing is out of reach: every polled address answers and every "
                           "neighbour is accounted for.",
                           "Rien n'est hors de portée : chaque adresse interrogée répond et "
                           "chaque voisin est expliqué."),
    "web.kind.all": ("Everything ({count})", "Tout ({count})"),
    "web.kind.snmp": ("SNMP ({count})", "SNMP ({count})"),
    "web.kind.neighbor": ("Neighbours ({count})", "Voisins ({count})"),
    "web.kind.names": ("Names ({count})", "Noms ({count})"),
    "kind.snmp": ("SNMP", "SNMP"),
    "kind.neighbor": ("Neighbour", "Voisin"),
    "kind.names": ("Name probe", "Sondage de nom"),
    "col.kind": ("KIND", "NATURE"),
    "col.tried": ("TRIED", "ESSAYÉ"),
    "col.why": ("WHY NOT", "POURQUOI PAS"),
    "col.attempt": ("LAST ATTEMPT", "DERNIÈRE TENTATIVE"),
    "unreach.snmp.never": ("never answered", "n'a jamais répondu"),
    "unreach.snmp.failures": ("{count} attempt(s) failed in a row",
                              "{count} tentative(s) échouée(s) d'affilée"),
    "unreach.snmp.tried": ("SNMP, {credential}", "SNMP, {credential}"),
    "unreach.snmp.every": ("every credential", "chaque identifiant"),
    "unreach.neighbor.tried": ("not attempted", "non tentée"),
    "unreach.neighbor.pending": ("nothing stops it: the next collect will try it",
                                 "rien ne l'en empêche : la prochaine collecte l'essaiera"),
    "unreach.names.outside": ("outside names.networks, so never asked",
                              "hors de names.networks, donc jamais interrogé"),
    "unreach.names.silent": ("no answer", "aucune réponse"),
    "unreach.names.dropped": ("answered, but states the MAC {mac}, which is not this row's: "
                              "the name was dropped",
                              "a répondu, mais annonce la MAC {mac}, qui n'est pas celle de "
                              "cette ligne : le nom a été écarté"),
    "unreach.names.pending": ("not asked yet: run 'names ask'",
                              "pas encore interrogé : lancez « names ask »"),
    "unreach.names.off": ("names.probe is empty: no node is asked its name",
                          "names.probe est vide : aucun nœud n'est interrogé sur son nom"),
    "unreach.count": ("{snmp} address(es) that do not answer SNMP · {neighbor} neighbour(s) "
                      "not polled · {names} node(s) that state no name",
                      "{snmp} adresse(s) qui ne répondent pas en SNMP · {neighbor} voisin(s) "
                      "non interrogé(s) · {names} nœud(s) qui n'annoncent aucun nom"),
    "hint.unreachable.kind": (
        "SNMP: a polled address that does not answer. Neighbour: announced by LLDP or CDP and "
        "not polled. Name probe: a node that stated no name when asked (names.probe).",
        "SNMP : une adresse interrogée qui ne répond pas. Voisin : annoncé par LLDP ou CDP et "
        "non interrogé. Sondage de nom : un nœud qui n'a annoncé aucun nom quand on le lui a "
        "demandé (names.probe)."),
    "hint.unreachable.tried": (
        "What was attempted: SNMP with the credential chosen for it, or every one of them; "
        "nothing for a neighbour that was never tried; the protocols asked for a node.",
        "Ce qui a été tenté : le SNMP avec l'identifiant choisi pour elle, ou avec chacun d'eux ; "
        "rien pour un voisin jamais essayé ; les protocoles demandés pour un nœud."),
    "hint.unreachable.why": (
        "The reason, in the words of the rule that decided it. An address outside "
        "discovery.allowed, a phone, a silent host: each is a different thing to fix, or to "
        "leave as it is.",
        "La raison, avec les mots de la règle qui l'a décidée. Une adresse hors de "
        "discovery.allowed, un téléphone, un hôte muet : chacun est une chose différente à "
        "corriger, ou à laisser telle quelle."),
    "web.do.collect": ("Collect", "Collecter"),
    "web.do.discover": ("Discover", "Découvrir"),
    "web.do.export": ("Export", "Exporter"),
    "web.do.push": ("Push", "Envoyer"),
    "web.do.names": ("Ask names", "Demander les noms"),
    "web.do.scan": ("Port scan", "Scan de ports"),
    "web.scan.title": ("Scan {address}", "Scan de {address}"),
    "web.scan.profile": ("Profile", "Profil"),
    "web.scan.profile.quick": ("Quick: 100 ports, a few seconds",
                               "Rapide : 100 ports, quelques secondes"),
    "web.scan.profile.common": ("Common: 1000 ports and versions, about a minute",
                                "Courant : 1000 ports et versions, environ une minute"),
    "web.scan.profile.all": ("All: 65535 ports and versions, many minutes",
                             "Tous : 65535 ports et versions, de nombreuses minutes"),
    "web.scan.start": ("Scan this address", "Scanner cette adresse"),
    "web.scan.hint": (
        "A TCP scan from this machine, by nmap without privilege: it connects to ports and "
        "changes nothing on the device. An IPS may flag it, so ask first.",
        "Un scan TCP depuis cette machine, par nmap sans privilège : il se connecte à des ports "
        "et ne change rien sur l'équipement. Un IPS peut le signaler, prévenez d'abord."),
    "web.scan.no_nmap": (
        "nmap is not installed in this container: rebuild the image "
        "(docker compose up -d --build).",
        "nmap n'est pas installé dans ce conteneur : reconstruisez l'image "
        "(docker compose up -d --build)."),
    "web.scan.last": ("Last scan: {when}, profile {profile}",
                      "Dernier scan : {when}, profil {profile}"),
    "web.scan.none": ("This address has not been scanned.", "Cette adresse n'a pas été scannée."),
    "web.scan.down": ("The host did not answer.", "L'hôte n'a pas répondu."),
    "web.scan.suspect": (
        "Not trusted: these ports are not shown as the host's own.",
        "Non fiable : ces ports ne sont pas présentés comme ceux de l'hôte."),
    "web.scan.nothing_open": ("Nothing open was found", "Aucun port ouvert n'a été trouvé"),
    "web.scan.bad": ("{text} is not an IP address.", "{text} n'est pas une adresse IP."),
    "web.scan.refused": ("This address is {reason}: it is never scanned.",
                         "Cette adresse est {reason} : elle n'est jamais scannée."),
    "web.snmp.refused": (
        "{address} is {reason}: the interface does not send SNMP there. Add it from a shell "
        "(snowth_my_net device add) if it is meant.",
        "{address} est {reason} : l'interface n'y envoie pas de SNMP. Ajoutez-la depuis un "
        "shell (snowth_my_net device add) si c'est voulu."),
    "web.import.link": ("Import names from a CSV", "Importer des noms depuis un CSV"),
    "web.import.title": ("Import names", "Importer des noms"),
    "web.import.s1": ("Get the list.", "Récupérer la liste."),
    "web.import.template": ("Download the {count} nodes as a CSV",
                            "Télécharger les {count} nœuds en CSV"),
    "web.import.s1.note": (
        "MAC, current name, then the address and the vendor to help you (not read back).",
        "MAC, nom actuel, puis l'adresse et le fabricant pour vous aider (non relus)."),
    "web.import.s2": ("Fill the name column", "Remplir la colonne des noms"),
    "web.import.s2.note": (
        "in your spreadsheet; a line with no name changes nothing. You can also add MACs.",
        "dans votre tableur ; une ligne sans nom ne change rien. Vous pouvez aussi ajouter "
        "des MAC."),
    "web.import.s3": ("Send it back", "Le renvoyer"),
    "web.import.check": ("Check the file", "Vérifier le fichier"),
    "web.import.file": ("Nothing is written yet. At most {size} KiB.",
                        "Rien n'est écrit pour l'instant. {size} Kio au plus."),
    "web.import.hint": (
        "The MAC is in the first column and the name in the second (, or ;). A MAC that "
        "already has a name is updated, any other is added; one the network has not shown yet "
        "is kept and appears once it is seen. An empty name erases nothing.",
        "La MAC est en première colonne et le nom en seconde (, ou ;). Une MAC qui a déjà "
        "un nom est mise à jour, toute autre est ajoutée ; une MAC que le réseau n'a pas encore "
        "montrée est gardée et apparaît dès qu'elle est vue. Un nom vide n'efface rien."),
    "web.import.nofile": ("No file received: choose a CSV file.",
                          "Aucun fichier reçu : choisissez un fichier CSV."),
    "web.import.preview": (
        "Nothing has been written yet. This is what applying the file would do.",
        "Rien n'a encore été écrit. Voici ce que ferait l'application du fichier."),
    "web.import.apply": ("Apply {count} change(s)", "Appliquer {count} changement(s)"),
    "web.import.other": ("Choose another file", "Choisir un autre fichier"),
    "web.import.nothing": ("Nothing to change in this file.",
                           "Rien à changer dans ce fichier."),
    "web.import.errors": (
        "{count} line(s) cannot be used and will be skipped; the others can be applied.",
        "{count} ligne(s) inutilisable(s), sautée(s) ; les autres peuvent être appliquées."),
    "web.import.done": ("Done. The names are written.", "Terminé. Les noms sont écrits."),
    "web.import.log": ("Download the log (CSV)", "Télécharger le log (CSV)"),
    "web.import.back": ("Back to the nodes", "Retour aux nœuds"),
    "web.import.more": ("The first {shown} of {total} lines are shown; the log holds all.",
                        "Les {shown} premières lignes sur {total} sont montrées ; le log les "
                        "contient toutes."),
    "web.import.r.error": ("error", "erreur"),
    "web.import.r.updated": ("updated", "mis à jour"),
    "web.import.r.added": ("added", "ajouté"),
    "web.import.r.skipped": ("skipped", "ignoré"),
    "web.import.r.unchanged": ("unchanged", "inchangé"),
    "web.import.d.mac": ("not a MAC address", "pas une adresse MAC"),
    "web.import.d.column": ("no second column: the name", "pas de seconde colonne : le nom"),
    "web.import.d.empty": ("no name on this line: nothing is changed",
                           "pas de nom sur cette ligne : rien n'est changé"),
    "web.import.d.same": ("already named so", "déjà nommée ainsi"),
    "web.import.d.unseen": ("not seen on the network yet", "pas encore vue sur le réseau"),
    "web.import.d.dup": ("MAC already on line {line}: this line is ignored",
                         "MAC déjà à la ligne {line} : cette ligne est ignorée"),
    "web.import.d.long": ("a name is at most {size} characters",
                          "un nom fait au plus {size} caractères"),
    "web.import.c.line": ("Line", "Ligne"),
    "web.import.c.before": ("Before", "Avant"),
    "web.import.c.name": ("Name", "Nom"),
    "web.import.c.result": ("Result", "Résultat"),
    "web.import.c.detail": ("Detail", "Détail"),
    "web.scan.mass.title": ("Many addresses at once", "Beaucoup d'adresses à la fois"),
    "web.scan.mass.hint": (
        "A network is scanned from a shell, not from this page: the same command and the same "
        "rules (discovery.allowed), and the results appear here afterwards. Replace the network "
        "and the profile (quick, common, all).",
        "Un réseau se scanne depuis un shell, pas depuis cette page : la même commande et les "
        "mêmes règles (discovery.allowed), et les résultats apparaissent ici ensuite. Remplacez "
        "le réseau et le profil (quick, common, all)."),
    "col.proto": ("PROTOCOL", "PROTOCOLE"),
    "col.service": ("SERVICE", "SERVICE"),
    "col.product": ("PRODUCT", "PRODUIT"),
    "col.version": ("VERSION", "VERSION"),
    "web.do.title": ("Run now", "Lancer maintenant"),
    "web.do.running": ("{what} running for {seconds} s…", "{what} en cours depuis {seconds} s…"),
    "web.do.busy": ("Something is already running.", "Quelque chose tourne déjà."),
    "web.do.last": ("Last: {what}, {status}, {seconds} s — {detail}",
                    "Dernier : {what}, {status}, {seconds} s — {detail}"),
    "web.do.ok": ("done", "terminé"),
    "web.do.partial": ("partial", "partiel"),
    "web.do.failed": ("failed", "échec"),
    "web.do.hint": ("The same commands as in a shell, one at a time. The scheduler keeps its "
                    "own pace.",
                    "Les mêmes commandes qu'en ligne de commande, une à la fois. Le "
                    "planificateur garde son propre rythme."),
    "web.name.title": ("Name", "Nom"),
    "web.description.title": ("Description", "Description"),
    "web.name.hint": ("Given by hand, kept with the MAC address: a collect never changes it.",
                      "Donné à la main, conservé avec l'adresse MAC : une collecte ne le "
                      "change jamais."),
    "web.name.save": ("Save", "Enregistrer"),
    "web.name.placeholder": ("printer, desk of…, camera", "imprimante, poste de…, caméra"),
    "web.name.empty_clears": ("Leave empty to forget the name.",
                              "Laissez vide pour oublier le nom."),
    "web.password.title": ("Your password", "Votre mot de passe"),
    "web.password.current": ("Current password", "Mot de passe actuel"),
    "web.password.new": ("New password", "Nouveau mot de passe"),
    "web.password.again": ("New password (again)", "Nouveau mot de passe (à nouveau)"),
    "web.password.save": ("Save", "Enregistrer"),
    "web.password.rule": ("At least {min} characters.", "Au moins {min} caractères."),
    "web.password.mismatch": ("The two passwords differ.",
                              "Les deux mots de passe sont différents."),
    "web.password.wrong": ("The current password is wrong.",
                           "Le mot de passe actuel est incorrect."),
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
    "xp.given_name": ("Named by hand: {name}", "Nommée à la main : {name}"),
    "xp.given_description": ("Description: {text}", "Description : {text}"),
    "xp.probed": ("Name the host states about itself: {name} ({source})",
                  "Nom que l'hôte annonce sur lui-même : {name} ({source})"),
    "xp.hostname": ("Hostname used: {name} ({source})",
                    "Nom d'hôte retenu : {name} ({source})"),
    "xp.hostname_clash": (
        "The hand-written hostname and the DNS one disagree: one of them is wrong",
        "Le nom d'hôte écrit à la main et celui du DNS diffèrent : l'un des deux est faux"),
    "xp.src.manual": ("written by hand", "écrit à la main"),
    "xp.src.dns": ("reverse DNS", "DNS inverse"),
    "xp.src.snmp": ("sysName, reported by the polled device",
                    "sysName, rapporté par l'équipement interrogé"),
    "xp.src.netbios": ("NetBIOS, stated by the host", "NetBIOS, annoncé par l'hôte"),
    "xp.src.llmnr": ("LLMNR, stated by the host", "LLMNR, annoncé par l'hôte"),
    "xp.src.mdns": ("mDNS, stated by the host", "mDNS, annoncé par l'hôte"),
    "xp.is_the_mac": ("(this MAC rewritten: it reaches nothing)",
                      "(cette MAC réécrite : elle ne joint rien)"),
    "xp.link_local": ("(link-local: valid on that segment only)",
                      "(lien-local : valable sur ce segment seulement)"),
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
    "xp.excl.link_local_only": (
        "known by nothing but a link-local address, in a neighbour cache: no port, and nothing "
        "to reach it by (nodes.include_link_local_only to list it anyway)",
        "connue par rien d'autre qu'une adresse lien-local, dans un cache de voisinage : aucun "
        "port, et rien pour la joindre (nodes.include_link_local_only pour la lister quand "
        "même)"),
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
