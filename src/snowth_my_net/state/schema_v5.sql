-- Names a host states about itself (NetBIOS, LLMNR, mDNS), cached like the PTR answers.
-- One row per (address, source): the three can disagree, and which one answered is the point.
-- `mac` is what the host said about its own adapter: when it contradicts the node's MAC, the
-- answer came from something else and the name is not that node's.
CREATE TABLE name_probe (
  address      TEXT NOT NULL,
  source       TEXT NOT NULL,          -- netbios | llmnr | mdns
  name         TEXT,
  mac          TEXT,
  status       TEXT NOT NULL,          -- ok | none | error
  resolved_at  INTEGER NOT NULL,
  expires_at   INTEGER NOT NULL,
  PRIMARY KEY (address, source)
);
CREATE INDEX name_probe_expiry ON name_probe(expires_at);
