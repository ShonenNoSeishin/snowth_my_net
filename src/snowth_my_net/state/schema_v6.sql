-- What a port scan found on one address: the last scan only, since a scan describes "now".
-- `ports` is a JSON list of {port, proto, state, service, product, version}; a scan that found
-- nothing open is a scan that ran, and says so (status ok, no ports), unlike one that failed.
CREATE TABLE host_scan (
  address     TEXT PRIMARY KEY,
  profile     TEXT NOT NULL,           -- quick | common | all
  status      TEXT NOT NULL,           -- ok | down | error
  detail      TEXT,                    -- the reason when it is not ok
  ports       TEXT NOT NULL,
  scanned_at  INTEGER NOT NULL,
  seconds     REAL NOT NULL
);
