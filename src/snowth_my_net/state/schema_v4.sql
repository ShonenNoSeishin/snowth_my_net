-- Schema version 4: custom reports created in the terminal interface or imported.

CREATE TABLE reports (
  name        TEXT PRIMARY KEY,
  definition  TEXT NOT NULL,               -- JSON, same shape as the YAML
  created_at  INTEGER NOT NULL,
  updated_at  INTEGER NOT NULL
);
