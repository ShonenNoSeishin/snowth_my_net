-- Schema version 3: custom collectors (extra OIDs) and their values.

CREATE TABLE custom_collectors (           -- collectors created in the TUI / imported
  name        TEXT PRIMARY KEY,
  definition  TEXT NOT NULL,               -- JSON, same shape as the YAML
  created_at  INTEGER NOT NULL,
  updated_at  INTEGER NOT NULL
);

CREATE TABLE custom_runs (                 -- last pass of a collector on a device
  device_id   INTEGER NOT NULL REFERENCES devices(id) ON DELETE CASCADE,
  collector   TEXT NOT NULL,
  run_at      INTEGER NOT NULL,
  status      TEXT NOT NULL,               -- ok | absent | partial | timeout | error | forced_absent
  rows        INTEGER,
  detail      TEXT,
  PRIMARY KEY (device_id, collector)
);

CREATE TABLE custom_values (
  device_id   INTEGER NOT NULL REFERENCES devices(id) ON DELETE CASCADE,
  collector   TEXT NOT NULL,
  idx         TEXT NOT NULL,               -- '' for get:, the table index for walk:
  column      TEXT NOT NULL,
  value       TEXT,
  raw         TEXT,                        -- raw value (hex or number) for reference
  first_seen  INTEGER NOT NULL,
  last_seen   INTEGER NOT NULL,
  PRIMARY KEY (device_id, collector, idx, column)
);
