-- Schema version 2: per-device settings made by hand (TUI or `device set`).
-- They take precedence over config.yml `devices:` entries, field by field.

CREATE TABLE manual_settings (
  address     TEXT NOT NULL,             -- IP address (no port), like devices[].address
  key         TEXT NOT NULL,             -- e.g. type, features.arp, snmp.pace_ms
  value       TEXT NOT NULL,             -- JSON
  updated_at  INTEGER NOT NULL,
  PRIMARY KEY (address, key)
);
