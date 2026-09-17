-- snowth_my_net state, schema version 1.
-- All times are INTEGER seconds since the epoch (UTC), taken from the collector's clock.

CREATE TABLE meta (
  key    TEXT PRIMARY KEY,
  value  TEXT
);

CREATE TABLE runs (
  id           INTEGER PRIMARY KEY,
  command      TEXT NOT NULL,              -- collect|discover|export|push|run
  started_at   INTEGER NOT NULL,
  finished_at  INTEGER,
  status       TEXT,                       -- ok|partial|failed|aborted
  stats        TEXT                        -- JSON
);

CREATE TABLE devices (
  id                  INTEGER PRIMARY KEY,
  mgmt_address        TEXT NOT NULL,       -- ip or [ip]:port actually polled
  serial              TEXT,
  base_mac            TEXT,
  sys_name            TEXT,
  sys_descr           TEXT,
  sys_object_id       TEXT,
  sys_location        TEXT,
  sys_contact         TEXT,
  sys_uptime          INTEGER,
  sys_services        INTEGER,
  lldp_caps           INTEGER,             -- own lldpLocSysCapEnabled bitmask (bit 0 = other)
  vendor              TEXT,
  pen                 INTEGER,
  model               TEXT,
  os_name             TEXT,
  os_version          TEXT,
  device_type         TEXT NOT NULL DEFAULT '',   -- '' = no sure evidence
  type_rule           TEXT,
  type_reason         TEXT,
  driver              TEXT,
  credential          TEXT,                -- NAME of the working credential, never the secret
  first_seen          INTEGER NOT NULL,
  last_seen           INTEGER NOT NULL,    -- last successful system GET
  last_collect_at     INTEGER,
  last_collect_status TEXT
);
CREATE INDEX devices_serial   ON devices(serial);
CREATE INDEX devices_base_mac ON devices(base_mac);
CREATE INDEX devices_mgmt     ON devices(mgmt_address);

CREATE TABLE targets (
  address              TEXT PRIMARY KEY,
  origin               TEXT NOT NULL,      -- seed|neighbor|sweep|state
  depth                INTEGER NOT NULL DEFAULT 0,
  device_id            INTEGER REFERENCES devices(id) ON DELETE SET NULL,
  is_alias             INTEGER NOT NULL DEFAULT 0,
  credential           TEXT,
  first_seen           INTEGER,
  last_attempt_at      INTEGER,
  last_ok_at           INTEGER,
  consecutive_failures INTEGER NOT NULL DEFAULT 0,
  last_error           TEXT
);

CREATE TABLE device_chassis (
  device_id  INTEGER NOT NULL REFERENCES devices(id) ON DELETE CASCADE,
  ent_index  INTEGER NOT NULL,
  model      TEXT,
  serial     TEXT,
  sw_rev     TEXT,
  descr      TEXT,
  PRIMARY KEY (device_id, ent_index)
);

CREATE TABLE device_addresses (
  device_id   INTEGER NOT NULL REFERENCES devices(id) ON DELETE CASCADE,
  address     TEXT NOT NULL,
  ifindex     INTEGER,
  prefix_len  INTEGER,
  last_seen   INTEGER,
  PRIMARY KEY (device_id, address)
);
CREATE INDEX device_addresses_addr ON device_addresses(address);

CREATE TABLE device_macs (
  device_id  INTEGER NOT NULL REFERENCES devices(id) ON DELETE CASCADE,
  mac        TEXT NOT NULL,
  source     TEXT,                         -- bridge|ifphys|lldp_chassis
  last_seen  INTEGER,
  PRIMARY KEY (device_id, mac)
);
CREATE INDEX device_macs_mac ON device_macs(mac);

CREATE TABLE interfaces (
  device_id     INTEGER NOT NULL REFERENCES devices(id) ON DELETE CASCADE,
  ifindex       INTEGER NOT NULL,
  name          TEXT,
  descr         TEXT,
  alias         TEXT,
  if_type       INTEGER,
  admin_status  INTEGER,
  oper_status   INTEGER,
  speed_mbps    INTEGER,
  phys_mac      TEXT,
  bridge_port   INTEGER,
  pvid          INTEGER,
  lag_ifindex   INTEGER,
  role          TEXT,                      -- access|uplink
  role_reasons  TEXT,                      -- JSON list
  mac_count     INTEGER,
  role_at       INTEGER,
  last_seen     INTEGER,
  PRIMARY KEY (device_id, ifindex)
);

CREATE TABLE vlans (
  device_id  INTEGER NOT NULL REFERENCES devices(id) ON DELETE CASCADE,
  vlan_id    INTEGER NOT NULL,
  name       TEXT,
  last_seen  INTEGER,
  PRIMARY KEY (device_id, vlan_id)
);

CREATE TABLE fdb_obs (
  mac          TEXT NOT NULL,
  device_id    INTEGER NOT NULL REFERENCES devices(id) ON DELETE CASCADE,
  ifindex      INTEGER NOT NULL,
  vlan         INTEGER NOT NULL DEFAULT 0,
  vlan_source  TEXT,
  method       TEXT,
  first_seen   INTEGER NOT NULL,
  last_seen    INTEGER NOT NULL,
  last_run_id  INTEGER,
  PRIMARY KEY (mac, device_id, ifindex, vlan)
);
CREATE INDEX fdb_obs_port ON fdb_obs(device_id, ifindex, last_run_id);

CREATE TABLE arp_obs (
  mac           TEXT NOT NULL,
  address       TEXT NOT NULL,
  family        INTEGER NOT NULL,
  device_id     INTEGER NOT NULL REFERENCES devices(id) ON DELETE CASCADE,
  ifindex       INTEGER,
  source_table  TEXT,
  first_seen    INTEGER NOT NULL,
  last_seen     INTEGER NOT NULL,
  last_run_id   INTEGER,
  PRIMARY KEY (mac, address, device_id)
);
CREATE INDEX arp_obs_addr ON arp_obs(address, last_seen);

CREATE TABLE neighbors (
  device_id            INTEGER NOT NULL REFERENCES devices(id) ON DELETE CASCADE,
  ifindex              INTEGER,
  protocol             TEXT NOT NULL,
  remote_key           TEXT NOT NULL,
  remote_chassis_id    TEXT,
  remote_sys_name      TEXT,
  remote_port_id       TEXT NOT NULL DEFAULT '',
  remote_port_desc     TEXT,
  remote_mgmt_address  TEXT,
  remote_caps          TEXT,
  remote_platform      TEXT,
  remote_device_id     INTEGER,
  remote_ifindex       INTEGER,
  local_port_method    TEXT,
  first_seen           INTEGER,
  last_seen            INTEGER,
  last_run_id          INTEGER,
  PRIMARY KEY (device_id, protocol, remote_key, remote_port_id)
);

CREATE TABLE collect_status (
  run_id       INTEGER NOT NULL,
  device_id    INTEGER NOT NULL,
  function     TEXT NOT NULL,
  status       TEXT NOT NULL,              -- ok|empty|absent|timeout|error|skipped|partial
  rows         INTEGER,
  duration_ms  INTEGER,
  detail       TEXT,
  PRIMARY KEY (run_id, device_id, function)
);

CREATE TABLE dns_cache (
  address      TEXT PRIMARY KEY,
  name         TEXT,
  status       TEXT,
  resolved_at  INTEGER,
  expires_at   INTEGER
);
