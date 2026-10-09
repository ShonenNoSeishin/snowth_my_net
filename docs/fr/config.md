# Référence de configuration

Un seul fichier YAML (`snowth_my_net init` écrit un exemple commenté). Une clé inconnue est une
erreur, avec une suggestion quand elle ressemble à une faute de frappe ; `snowth_my_net check`
valide le fichier et teste chaque équipement. Toutes les valeurs par défaut sont génériques :
rien n'est réglé pour un réseau particulier.

**Où le fichier est cherché :** `--config` > `$SNOWTH_CONFIG` > `./snowth_my_net.yml` >
`/etc/snowth_my_net/config.yml`.

**Les durées** s'écrivent en secondes ou `30s`, `10m`, `24h`, `7d`. **Les adresses** acceptent
une IP ou un CIDR.

**Les secrets ne vont jamais dans ce fichier.** Communautés, clés SNMPv3, jetons et mots de passe
sont lus dans un fichier (`*_file` ; un chemin relatif l'est par rapport à `general.secrets_dir`)
ou dans une variable d'environnement (`*_env`). Écrire `community:`, `auth_key:`, `token:`… est
refusé (code de sortie 2). Un fichier de secret lisible par le groupe ou par les autres déclenche
un avertissement ; le BOM et les CR/LF finaux sont retirés.

**Priorité des chemins** (`state_dir`, `output_dir`, `secrets_dir`, `extensions_dir`) : option de
ligne de commande > variable d'environnement (`SNOWTH_STATE_DIR`, `SNOWTH_OUTPUT_DIR`,
`SNOWTH_SECRETS_DIR`, `SNOWTH_EXTENSIONS_DIR`) > ce fichier > valeur par défaut. Les chemins
relatifs écrits dans le fichier sont relatifs à son répertoire. Un même fichier sert ainsi une
installation sur l'hôte et le conteneur.

**Les réglages manuels** faits dans l'interface en terminal ou avec `snowth_my_net device set`
priment sur les entrées `devices:`, clé par clé (voir `devices`).

## `version`

| Clé | Défaut | Description |
|---|---|---|
| `version` | `1` | Version du format de ce fichier. |

## `general`

| Clé | Défaut | Description |
|---|---|---|
| `general.state_dir` | `/var/lib/snowth_my_net` | État : `state.sqlite`, `state.lock`, base des constructeurs mise à jour. Doit être sur un disque local (le verrou utilise `flock`). |
| `general.output_dir` | `<state_dir>/output` | Sorties CSV, JSON et cartes. |
| `general.secrets_dir` | `/etc/snowth_my_net/secrets` | Base des chemins relatifs des secrets `*_file`. |
| `general.extensions_dir` | `<config dir>/extensions` | Collecteurs et rapports personnalisés (`*.yml`), extensions Python (`*.py`), voir [extensions](extensions.md). |
| `general.python_extensions` | `[]` | Extensions Python à charger, par nom : `<extensions_dir>/<name>.py` ou un point d'entrée installé. Rien n'est importé sans être listé. |
| `general.log_file` | aucun | Journalise aussi dans ce fichier (rotation 10 Mo × 5). Les journaux vont toujours sur stderr. |
| `general.log_level` | `info` | `debug`, `info`, `warning`, `error`. |
| `general.language` | `auto` | Langue de l'interface en terminal, et de l'explication qu'elle affiche pour un nœud : `auto` (d'après `LANG`), `fr`, `en`. La CLI (`explain`, journaux, `--json`) reste en anglais. |
| `general.device_name.strip_domain` | `first_dot` | Noms des équipements : `first_dot` garde ce qui précède le premier point (sauf si le sysName est une IP), `suffixes` retire les `domain_suffixes`, `none` garde le sysName. |
| `general.device_name.domain_suffixes` | `[]` | Suffixes retirés avec `strip_domain: suffixes`. |
| `general.device_name.duplicate_names` | `suffix_ip` | Deux équipements de même nom reçoivent le suffixe ` (IP)` (`keep` le désactive). Le nom est la clé de jointure de `nodes.csv` et `links.csv`. |
| `general.lock_wait.collect` | `60` | Temps pendant lequel un `collect` attend une autre exécution avant de sortir avec le code 3. |
| `general.lock_wait.default` | `900` | Idem pour `export`, `push`, `run`, `discover` (ils démarrent souvent à la même minute qu'une collecte). |
| `general.run_timeout` | `3000` | Budget d'une collecte complète. |
| `general.retention_days` | `90` | Équipements, voisins, valeurs personnalisées et exécutions non vus depuis cette durée sont oubliés. |
| `general.snmp.port` | `161` | Port UDP des points de départ sans port, des voisins explorés et des balayages. |
| `general.snmp.timeout` | `3` | Par requête, en secondes. |
| `general.snmp.retries` | `1` | Nouvelles tentatives par requête. |
| `general.snmp.probe_timeout` | `2` | Délai lors de l'essai des identifiants (sans nouvelle tentative). Une mauvaise communauté v2c ne répond rien : gardez-le court et utilisez `credentials[].scope`. |
| `general.snmp.max_repetitions` | `25` | Taille des GETBULK. À baisser pour les agents fragiles. |
| `general.snmp.use_bulk` | `true` | `false` : GETNEXT uniquement (agents au GETBULK défaillant). |
| `general.snmp.concurrency` | `16` | Équipements interrogés en parallèle. |
| `general.snmp.per_device_concurrency` | `1` | Requêtes simultanées vers un même équipement (1 = jamais de rafale). |
| `general.snmp.pace_ms` | `0` | Pause minimale entre deux requêtes vers le même équipement. |
| `general.snmp.table_timeout` | `180` | Budget par table ; les lignes reçues avant le délai sont gardées (statut `partial`). |
| `general.snmp.device_timeout` | `600` | Budget par équipement. |
| `general.snmp.max_rows_per_table` | `500000` | Arrêt de sécurité contre les agents qui bouclent sans fin. |

## `credentials`

Une liste ordonnée. Pour chaque adresse, l'identifiant qui a fonctionné la dernière fois est
essayé en premier, puis chaque identifiant dont le `scope` contient l'adresse, dans l'ordre.
SNMPv3 authPriv est recommandé : v2c envoie sa communauté en clair (`check` le signale).

| Clé | Défaut | Description |
|---|---|---|
| `credentials[].name` | obligatoire | Nom affiché dans les journaux et les sorties (jamais le secret). |
| `credentials[].version` | obligatoire | `2c` ou `3`. |
| `credentials[].scope` | `[]` (tout) | Adresses/CIDR où cet identifiant est essayé. |
| `credentials[].community_file` | | Communauté v2c, depuis un fichier. |
| `credentials[].community_env` | | Communauté v2c, depuis une variable d'environnement. |
| `credentials[].username` | | Utilisateur SNMPv3. |
| `credentials[].auth_protocol` | | `md5`, `sha`, `sha224`, `sha256`, `sha384`, `sha512`. |
| `credentials[].auth_key_file` | | Clé d'authentification SNMPv3 (au moins 8 caractères). |
| `credentials[].auth_key_env` | | Idem, depuis l'environnement. |
| `credentials[].priv_protocol` | | `des`, `3des`, `aes128`, `aes192`, `aes256` (Blumenthal), `aes192c`, `aes256c` (extension de clé Cisco). Nécessite `auth_protocol`. |
| `credentials[].priv_key_file` | | Clé de chiffrement SNMPv3. |
| `credentials[].priv_key_env` | | Idem, depuis l'environnement. |

## `discovery`

| Clé | Défaut | Description |
|---|---|---|
| `discovery.seeds` | `[]` | Points de départ : IP, noms d'hôte (résolus à chaque exécution), `host:port`. Un point de départ peut être hors `allowed`, jamais dans `exclude`. |
| `discovery.allowed` | `[]` | Plages où les équipements peuvent être interrogés (voisins, balayages, équipements connus) : une liste de réseaux, ou le mot `all` pour toute adresse IPv4 et IPv6. Vide : seulement les amorces. Avec `all`, une adresse qu'un voisin annonce est interrogée où qu'elle pointe et reçoit les identifiants essayés contre elle — gardez `discovery.exclude` pour ce qui ne doit jamais être atteint. |
| `discovery.exclude` | `[]` | Adresses/plages jamais interrogées. |
| `discovery.follow_neighbors` | `true` | Explore les voisins LLDP/CDP (en largeur) pendant `collect` et `discover`. |
| `discovery.max_depth` | `3` | Nombre de sauts depuis un point de départ. |
| `discovery.follow_capabilities` | `[bridge, router, wlan_ap]` | Seuls les voisins annonçant l'une de ces capacités sont sondés ; téléphones et stations ne le sont jamais. |
| `discovery.sweep` | `[]` | Plages sondées activement (dans `allowed`, 65536 adresses au plus). |
| `discovery.sweep_rate` | `50` | Sondes par seconde pendant un balayage. |
| `discovery.sweep_interval` | `86400` | Temps minimal entre deux balayages (un `collect` ne balaie que quand c'est dû ; `discover` toujours). |
| `discovery.forget_after_days` | `90` | Les adresses découvertes qui ne répondent plus jamais sont oubliées (les points de départ et les adresses ajoutées à la main sont gardés). |

## `devices`

Réglages par équipement, par IP ou CIDR. Toutes les entrées qui contiennent l'adresse
s'appliquent ; la plus précise l'emporte clé par clé (un /32 bat un /24). Les réglages manuels
(TUI, `device set`) priment sur cette section. **Le type n'empêche jamais une collecte** : les MIB
standard sont toujours tentées, sauf si une fonction est `off`.

| Clé | Défaut | Description |
|---|---|---|
| `devices[].address` | obligatoire | IP ou CIDR. |
| `devices[].name` | sysName | Nom dans toutes les sorties. |
| `devices[].type` | détecté | `switch`, `router`, `firewall`, `wireless`, `server`, `printer`, `facility`, `other`. Une simple étiquette. |
| `devices[].credential` | automatique | N'utiliser que cet identifiant. |
| `devices[].features.entity` | `auto` | ENTITY-MIB (modèle, numéro de série). `auto` : tenter, silencieux si absente ; `force` : l'absence est une erreur (code 1) ; `off` : ne jamais interroger. |
| `devices[].features.interfaces` | `auto` | IF-MIB. |
| `devices[].features.ipaddr` | `auto` | Adresses de l'équipement (IP-MIB). |
| `devices[].features.fdb` | `auto` | Tables MAC (Q-BRIDGE, BRIDGE, Cisco par VLAN). |
| `devices[].features.arp` | `auto` | Tables ARP/NDP (les deux tables IP-MIB, toujours). |
| `devices[].features.lldp` | `auto` | Voisins LLDP : LLDP-MIB, ou LLDP-V2-MIB (802.1AB-2009) quand l'agent sert celle-ci à la place. |
| `devices[].features.cdp` | `auto` | Voisins CDP. |
| `devices[].vlan_indexing` | `auto` | Instances de bridge Cisco par VLAN (`community@vlan`, contexte SNMPv3 `vlan-N`) : `auto` les utilise quand CISCO-VTP-MIB répond et que Q-BRIDGE est vide ; `cisco` toujours ; `off` jamais. Une collecte avertit quand un VLAN qui porte des ports n'a rendu aucune MAC — la signature d'une instance non lue — et `cisco` est ce qui la lit. |
| `devices[].vrfs` | `auto` | Caches ARP des VRF non globales, lus dans leur propre contexte SNMP : `auto` lit les VRF que l'équipement déclare (CISCO-VRF-MIB, puis MPLS-L3VPN-STD-MIB), `off` ne lit que la table globale, ou donnez les noms de contextes à lire (`[blue, dmz]`). Le nom de contexte doit correspondre au nom de la VRF ; en SNMPv2c, la communauté `community@vrf` est utilisée. |
| `devices[].uplinks` | `[]` | Ports (par nom) toujours traités comme uplinks. |
| `devices[].access_ports` | `[]` | Ports toujours traités comme ports d'accès (par exemple un bond LACP de serveur). |
| `devices[].uplink_mac_threshold` | `nodes.uplink_mac_threshold` | Seuil propre à l'équipement. |
| `devices[].snmp.timeout` | global | Surcharge de `general.snmp.timeout` pour l'équipement. |
| `devices[].snmp.retries` | global | Surcharge. |
| `devices[].snmp.max_repetitions` | global | Surcharge (à baisser pour les pare-feu). |
| `devices[].snmp.use_bulk` | global | Surcharge. |
| `devices[].snmp.per_device_concurrency` | global | Surcharge. |
| `devices[].snmp.pace_ms` | global | Surcharge (pour ménager le CPU d'un pare-feu). |
| `devices[].snmp.table_timeout` | global | Surcharge. |
| `devices[].snmp.device_timeout` | global | Surcharge. |
| `devices[].snmp.max_rows_per_table` | global | Surcharge. |
| `devices[].driver` | `auto` | Driver constructeur : `auto` (choisi d'après le sysObjectID), `none`, ou le nom d'un driver (`fortinet`, `sophos`, `mikrotik`, `cisco-wlc`, ou celui d'une extension Python) pour l'utiliser quoi qu'annonce l'équipement. Voir [drivers](drivers.md). |
| `devices[].tolerate_failure` | `false` | L'équipement reste dans les sorties ; son échec ne donne pas le code de sortie 1. |
| `devices[].ha_mode` | members | Sur l'IP virtuelle d'un cluster : `members` interroge les adresses des membres (la VIP devient un alias), `vip` interroge la VIP. |
| `devices[].disabled` | `false` | Ne jamais interroger cette adresse. |

## `nodes`

Comment les observations MAC et ARP deviennent des positions de nœuds (voir `explain`).

| Clé | Défaut | Description |
|---|---|---|
| `nodes.uplink_mac_threshold` | `50` | Un port qui porte davantage de MAC apprises au dernier parcours est un uplink (faible) : un filet de sécurité pour les uplinks sans LLDP. Élevé exprès : un AP, un hyperviseur ou un petit switch de bureau porte légitimement beaucoup de MAC. Rien n'est supprimé quand il s'applique — l'observation reste, `explain` la montre avec sa raison — mais une MAC vue seulement là n'a pas de position. `show uplinks` liste ce qu'il décide et ce que chaque décision coûte. |
| `nodes.lag_is_uplink` | `false` | Traiter tout agrégat de liens comme un uplink. Rarement nécessaire : un trunk hérite des voisins LLDP/CDP de ses ports membres, donc un trunk entre switches est reconnu même s'il porte peu de MAC. À activer si vos trunks ne portent aucun LLDP. |
| `nodes.ap_ports_are_access` | `true` | Un port qui mène à un point d'accès non interrogé est un port d'accès (les clients Wi-Fi y sont positionnés). |
| `nodes.uplink_fallback` | `false` | Une MAC vue uniquement derrière des uplinks faibles (seuil, bridge non interrogé) est placée sur celui qui porte le moins de MAC (`position_kind: behind_uplink`). Par défaut : pas de position. **À activer pour égaler un outil qui rapporte le port d'apprentissage** : un switch non manageable suffisamment peuplé pour dépasser le seuil laisse sinon tout ce qui est derrière lui sans port. `show uplinks` compte ce que ça récupérerait. Un appareil derrière un switch qui *est* interrogé n'est jamais placé ainsi — son vrai port vient de ce switch. |
| `nodes.include_unlocated` | `true` | Lignes sans switch ni port dans `nodes.csv` (ARP seul, ou seulement derrière des uplinks). |
| `nodes.include_device_macs` | `false` | Garder comme nœuds les MAC des équipements interrogés. |
| `nodes.positions` | `all` | `all` : une ligne par position connue (historique d'itinérance, la plus récente d'abord) ; `current` : seulement la dernière. |
| `nodes.retention_days` | `30` | Les observations MAC/ARP plus anciennes sont purgées. |
| `nodes.prefer_ipv4` | `true` | L'IP courante est une IPv4 quand une IPv4 a été vue récemment. |
| `nodes.include_link_local_only` | `false` | Lister une MAC connue par rien d'autre qu'une adresse lien-local, dans un cache de voisinage : aucun port, et rien pour la joindre. Désactivé, car tout hôte IPv6 laisse une telle entrée, donc un routeur qui tient un cache de voisinage produit des centaines de ces lignes, chacune une MAC et six colonnes vides. `explain` répond toujours pour elles, et la moindre autre information fait revenir la ligne. |
| `nodes.elect_link_local` | `false` | Une adresse lien-local (`fe80::`) peut-elle être l'IP courante ? Désactivé : elle reste dans la liste des adresses, dans `explain` et dans `snapshot.json`, mais n'est jamais élue — rien ne route vers elle, aucun nom ne la résout, aucun importateur ne peut s'en servir. Qu'elle reprenne la MAC (`fe80::1e0b:8bff:fec0:eb62` pour `1c:0b:8b:c0:eb:62`) ou qu'elle porte un identifiant aléatoire, comme Windows les fabrique, une IP vide signifie alors honnêtement qu'aucune adresse utilisable n'a été vue. |
| `nodes.current_ip_window` | `86400` | Candidates à l'IP courante : vues dans cette fenêtre par rapport à la plus récente. |
| `nodes.current_ip_max_age` | `604800` | Une adresse vue plus longtemps avant la dernière observation du nœud lui-même n'est pas élue (un cache ARP qui en a gardé une des semaines). |
| `nodes.max_ips_per_mac` | `3` | Une MAC qui a plus d'adresses distinctes que cela (proxy-ARP, passerelle, hyperviseur), ou deux adresses vues au même instant, n'en reçoit aucune : la case reste vide plutôt que de nommer la mauvaise. |
| `nodes.transit_window` | `1800` | Une MAC vue sur deux ports d'accès dans cette fenêtre reste sur le port qui porte le moins de MAC ; l'autre est du transit. |
| `nodes.ignore_macs` | `[]` | MAC jamais rapportées. |
| `nodes.ignore_mac_prefixes` | VRRP, HSRP | Préfixes jamais rapportés (précision au quartet) : `00:00:5e:00:01`, `00:00:5e:00:02`, `00:00:0c:07:ac`, `00:00:0c:9f:f`. |

## `dns`

| Clé | Défaut | Description |
|---|---|---|
| `dns.enabled` | `true` | Résolutions inverses (PTR) des IP des nœuds au moment de l'export. |
| `dns.resolvers` | système | IP des résolveurs (un conteneur peut interroger directement le DNS interne). `dns check IP` dit lesquels sont utilisés et ce qu'ils répondent. |
| `dns.timeout` | `2` | Par résolution. |
| `dns.concurrency` | `20` | Résolutions en parallèle. |
| `dns.cache_ttl` | `86400` | Durée de vie d'un nom trouvé. |
| `dns.negative_ttl` | `3600` | Durée de vie d'un « pas de nom » ou d'un délai dépassé. |
| `dns.budget` | `120` | Temps total des résolutions par export ; le reste attend l'export suivant. |
| `dns.strip_domain` | `false` | Ne garder que la partie hôte dans `DNS Name`. |

## `names`

Demander son nom à un hôte, quand aucune zone DNS ne le contient — ce que font `nbtstat -A` et
un scanner. Désactivé par défaut : cela envoie un paquet à chaque nœud plutôt qu'aux
équipements interrogés, un balayage NetBIOS ressemble à de la reconnaissance pour un IPS, et un
nom qu'un hôte annonce sur lui-même est une preuve plus faible qu'un nom détenu par une zone.
`dns probe IP` dit quel protocole répond sur un réseau avant d'activer quoi que ce soit.

| Clé | Défaut | Description |
|---|---|---|
| `names.probe` | `[]` | Protocoles à interroger : `netbios` (UDP/137), `llmnr` (UDP/5355), `mdns` (UDP/5353). Vide : rien n'est demandé. |
| `names.networks` | `[]` | N'interroger que dans ces réseaux : une liste, ou le mot `all` pour toute adresse. Vide revient à `all`, mais `check` demande d'écrire le choix — une question envoyée là où un pare-feu la jette coûte le délai complet. |
| `names.at_export` | `true` | Interroger aussi pendant l'export. `false` laisse ce travail à `names ask` — planifié avec `schedule.names`, ou depuis le bouton *Demander les noms* — pour qu'un export reste rapide. |
| `names.timeout` | `1` | Par question. |
| `names.budget` | `60` | Temps total par export et par protocole ; le reste attend l'export suivant. |
| `names.cache_ttl` | `86400` | Durée de vie d'un nom trouvé. |
| `names.negative_ttl` | `3600` | Durée de vie d'un silence. |

Une réponse NetBIOS annonce aussi l'adresse de l'adaptateur : quand elle contredit la MAC de la
ligne à nommer, la réponse vient d'autre chose et le nom est écarté.

## `oui`

| Clé | Défaut | Description |
|---|---|---|
| `oui.file` | embarquée | Base des constructeurs explicite (TSV.gz produit par `oui-update`). |
| `oui.clean_names` | `true` | `Cisco Systems, Inc` → `Cisco Systems`. |
| `oui.urls` | IEEE MA-L, MA-M, MA-S | Sources de `oui-update` (HTTPS uniquement). |

## `export`

| Clé | Défaut | Description |
|---|---|---|
| `export.files` | tous | `devices`, `nodes`, `links`, `snapshot`, `map`. |
| `export.allow_empty` | `[]` | Fichiers CSV autorisés à n'avoir aucune ligne de données. Sinon un CSV vide n'écrase pas le précédent, n'est pas poussé, et la commande sort avec le code 1. |
| `export.csv.line_terminator` | `crlf` | `crlf` (RFC 4180) ou `lf`. |
| `export.csv.formula_safe` | `true` | Une cellule de texte qui commence par `=`, `+`, `-` ou `@` (un nom annoncé par un hôte) reçoit une apostrophe devant, pour qu'un tableur ne l'exécute jamais. `false` pour un importeur qui ne la supporte pas. |
| `export.nodes.live_only` | `true` | `nodes.csv` et la carte portent les nœuds vus à la dernière collecte complète, pas la mémoire gardée `nodes.retention_days`. `false` ramène la mémoire. |
| `export.devices.include_type` | `true` | Colonne finale `"Device Type"`. |
| `export.nodes.include_name` | `false` | Ajouter une première colonne `Name` à `nodes.csv` avec les noms donnés à la main (`node name`). Désactivé par défaut pour qu'un importateur continue de lire les mêmes colonnes. |
| `export.nodes.include_description` | `false` | Idem, pour les descriptions (`node describe`). |
| `export.nodes.merge_hostnames` | `true` | `DNS Name` porte le meilleur des trois : écrit à la main, sinon la résolution inverse, sinon le `sysName` d'un équipement interrogé, sinon ce que l'hôte annonce sur lui-même. `false` ne garde que la résolution inverse. `snapshot.json` enregistre toujours la source retenue. |
| `export.links.include_endpoints` | `false` | Inclure téléphones et stations dans `links.csv` et sur la carte. |
| `export.map.formats` | `[dot, mmd, html]` | Fichiers de carte. |
| `export.map.endpoints` | `none` | Hôtes finaux sur la carte : `none`, `grouped` (une bulle par port), `all` (groupés au-delà de 2000 hôtes). |

## `push`

Voir [formats](formats.md#push-http) pour le protocole.

| Clé | Défaut | Description |
|---|---|---|
| `push.targets[].name` | obligatoire | Nom de la cible (`push --target`). |
| `push.targets[].url` | obligatoire | `https://…` (ou `http://`, avec avertissement). |
| `push.targets[].files` | `[devices, nodes]` | Fichiers envoyés un par un, dans cet ordre. |
| `push.targets[].auth.bearer_token_file` | | `Authorization: Bearer …`, jeton lu dans un fichier. |
| `push.targets[].auth.bearer_token_env` | | Idem, depuis l'environnement. |
| `push.targets[].auth.basic.username` | | Utilisateur de l'authentification Basic. |
| `push.targets[].auth.basic.password_file` | | Mot de passe Basic lu dans un fichier. |
| `push.targets[].auth.basic.password_env` | | Idem, depuis l'environnement. |
| `push.targets[].headers.<name>.file` | | En-tête supplémentaire dont la valeur vient d'un fichier (par exemple une clé d'API). |
| `push.targets[].headers.<name>.env` | | Idem, depuis l'environnement. |
| `push.targets[].multipart_field` | `file` | Champ de formulaire du fichier. |
| `push.targets[].extra_fields` | `{}` | Champs de formulaire supplémentaires (non secrets). |
| `push.targets[].tls_verify` | `true` | `false` accepte n'importe quel certificat (avertissement à chaque push). Préférez `ca_bundle`. |
| `push.targets[].ca_bundle` | système | Fichier d'AC pour un certificat interne ou autosigné. |
| `push.targets[].timeout` | `120` | Par requête. |
| `push.targets[].retries` | `0` | Nouvelles tentatives sur erreur réseau, 429 (`Retry-After`), 502, 503, 504 uniquement. Jamais sur 413 ni sur un autre 4xx. |
| `push.targets[].wait` | `false` | Attendre la fin des jobs 202 (comme `--wait`), pour les exécutions planifiées. |
| `push.targets[].poll.url` | obligatoire | URL du job avec `{id}`. |
| `push.targets[].poll.id_field` | `id` | Chemin pointé de l'identifiant du job dans le corps JSON de la réponse 202. |
| `push.targets[].poll.status_field` | `status` | Chemin pointé du statut dans le JSON du job. |
| `push.targets[].poll.pending` | `[queued, running]` | Continuer à interroger. |
| `push.targets[].poll.success` | `[done]` | Succès ; tout autre statut est un échec. |
| `push.targets[].poll.interval` | `5` | Entre deux interrogations. |
| `push.targets[].poll.timeout` | `1800` | Abandon après ce délai. |

## `schedule`

Déclarée une fois, utilisée par les deux déploiements : `snowth_my_net cron print` pour le cron de
l'hôte, le planificateur du conteneur au démarrage.

| Clé | Défaut | Description |
|---|---|---|
| `schedule.collect` | `*/10 * * * *` | Fréquent : les pare-feu font expirer les entrées ARP en quelques minutes, et l'état accumule les observations entre deux exports. `null` le désactive. |
| `schedule.export_push` | `0 11,18 * * *` | `run --no-collect` (export, puis push s'il existe des cibles). |
| `schedule.names` | aucune | `names ask` : demander son nom à chaque nœud, réponses mises en cache. Demande `names.probe` ; sans lui rien n'est planifié et `check` le dit. |
| `schedule.timezone` | fuseau du processus | Sert uniquement à interpréter la planification (`CRON_TZ`) ; toutes les sorties sont en UTC. |
| `schedule.health_max_age` | `auto` | Âge admis de la dernière collecte réussie pour `health` ; `auto` = deux fois le plus long intervalle de `schedule.collect`. |

## `web`

Interface web en lecture seule (`snowth_my_net web`, ou le service `web` de Compose), voir
[interface web](web.md).

| Clé | Défaut | Description |
|---|---|---|
| `web.bind` | `127.0.0.1` | Adresse d'écoute. `0.0.0.0` seulement avec des comptes, derrière un proxy inverse TLS. |
| `web.port` | `8080` | Port d'écoute. Avec Docker, le conteneur écoute toujours sur 8080 et `SNOWTH_WEB_PORT` choisit le port de l'hôte. |
| `web.node_limit` | `2000` | Lignes envoyées au navigateur sur la page Nœuds ; la page le signale quand elle tronque. |
| `web.auth.users` | `[]` | Comptes de l'interface. Vide : aucune authentification, ce qui n'est sûr que sur la boucle locale. |
| `web.auth.users[].name` | obligatoire | Nom d'utilisateur saisi dans le formulaire. Un nom seul suffit : le premier mot de passe est inventé et journalisé, puis `web passwd` le change. |
| `web.auth.users[].password_file` | | Facultatif : un fichier contenant l'empreinte affichée par `snowth_my_net web --hash-password` (relatif à `general.secrets_dir`), pour un mot de passe géré hors de l'outil. |
| `web.auth.users[].password_env` | | La même empreinte, depuis une variable d'environnement. Jamais les deux formes à la fois. |
| `web.actions` | `true` | Les boutons de la page Collectes qui lancent une collecte, une découverte, un export ou un envoi. `false` les retire et refuse les requêtes. Sans compte, quiconque atteint la page peut appuyer dessus. |
| `web.nmap` | `false` | Un scan de ports d'une adresse depuis l'interface : l'IP d'un équipement ouvre sa page de scan, avec un profil à choisir et le résultat conservé. Demande un compte et `web.actions`. Seul ce que `discovery.allowed` permet et que `discovery.exclude` épargne est scanné. |
| `web.trusted_proxies` | `[]` | Réseaux des proxys inverses autorisés à annoncer l'adresse du lecteur dans `X-Forwarded-For` (et `X-Forwarded-Proto`). Tout autre est ignoré. `--trusted-proxy CIDR` prime pour une exécution. |
| `web.auth.session_hours` | `12` | Durée d'une session ; les sessions vivent dans le processus et sont perdues au redémarrage. |

## `hooks`

Programmes externes lancés après une commande, pour tout ce que snowth_my_net ne fait pas
lui-même (notifier, copier des fichiers, alimenter un autre outil). Voir
[extensions](extensions.md#hooks).

```yaml
hooks:
  after_export:
    - name: copy-to-share
      command: [/usr/local/bin/publish-inventory, "{devices}", "{nodes}"]
      timeout: 120
```

| Clé | Défaut | Description |
|---|---|---|
| `hooks.after_collect` | `[]` | Après `collect` et l'étape de collecte de `run`. |
| `hooks.after_export` | `[]` | Après `export` et l'étape d'export de `run`. |
| `hooks.after_push` | `[]` | Après `push` et l'étape de push de `run` (pas après `--dry-run`). |
| `hooks.after_report` | `[]` | Après chaque rapport écrit par `report run` (et après chaque rapport en échec). |
| `hooks.after_collect[].name` | obligatoire | Unique pour l'événement ; affiché dans les journaux et dans `--json`. |
| `hooks.after_collect[].command` | obligatoire | Programme et arguments sous forme de **liste** ; jamais exécuté par un shell. Champs `{event}`, `{status}`, `{run_id}`, `{output_dir}`, `{state_dir}`, `{summary}` ; `{devices}`, `{nodes}`, `{links}`, `{snapshot}` après un export et un push ; `{report}`, `{report_file}` après un rapport. `{{` et `}}` sont des accolades littérales. |
| `hooks.after_collect[].timeout` | `60` | Ensuite le groupe de processus est terminé, puis tué 5 s plus tard. |
| `hooks.after_collect[].when` | `always` | `ok` : seulement quand l'étape a réussi ; `failed` : seulement quand elle n'a pas réussi (`partial` ou `failed`). |
| `hooks.after_collect[].env` | `{}` | Variables littérales pour le programme (jamais de secrets). |
| `hooks.after_collect[].pass_env` | `[]` | Variables copiées depuis l'environnement de snowth_my_net (par exemple `HTTPS_PROXY`). `check` avertit quand l'une d'elles est un secret utilisé par la configuration. |

Les autres événements prennent les mêmes clés : `hooks.after_export[].name`, `hooks.after_export[].command`, `hooks.after_export[].timeout`, `hooks.after_export[].when`, `hooks.after_export[].env`, `hooks.after_export[].pass_env`, `hooks.after_push[].name`, `hooks.after_push[].command`, `hooks.after_push[].timeout`, `hooks.after_push[].when`, `hooks.after_push[].env`, `hooks.after_push[].pass_env`, `hooks.after_report[].name`, `hooks.after_report[].command`, `hooks.after_report[].timeout`, `hooks.after_report[].when`, `hooks.after_report[].env`, `hooks.after_report[].pass_env`.
