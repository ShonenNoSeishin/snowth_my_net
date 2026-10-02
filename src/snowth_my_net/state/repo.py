"""Data access for the SQLite state. Short synchronous calls, one transaction per device."""

from __future__ import annotations

import json
import sqlite3
from typing import Any

from snowth_my_net.collect.model import ABSENT, OK, PARTIAL, DeviceResult, Outcome
from snowth_my_net.snmp.target import split_host_port

DAY = 86400
KEEP_STATUS_RUNS = 50
KEEP_RUNS_DAYS = 90


class Repo:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    # ------------------------------------------------------------------ meta

    def get_meta(self, key: str) -> str | None:
        row = self.conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
        return row[0] if row else None

    def set_meta(self, key: str, value: str) -> None:
        with self.conn:
            self.conn.execute(
                "INSERT INTO meta(key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value", (key, value))

    # ------------------------------------------------------------------ runs

    def start_run(self, command: str, now: int) -> int:
        with self.conn:
            cur = self.conn.execute(
                "INSERT INTO runs(command, started_at) VALUES (?, ?)", (command, now))
        return int(cur.lastrowid)

    def finish_run(self, run_id: int, status: str, now: int, stats: dict) -> None:
        with self.conn:
            self.conn.execute(
                "UPDATE runs SET finished_at = ?, status = ?, stats = ? WHERE id = ?",
                (now, status, json.dumps(stats, sort_keys=True), run_id))

    def last_successful_collect(self) -> sqlite3.Row | None:
        return self.conn.execute(
            "SELECT * FROM runs WHERE command IN ('collect', 'run') "
            "AND status IN ('ok', 'partial') AND finished_at IS NOT NULL "
            "AND json_extract(COALESCE(stats, '{}'), '$.only') IS NULL "
            "ORDER BY finished_at DESC LIMIT 1").fetchone()

    def recent_runs(self, limit: int = 20) -> list[sqlite3.Row]:
        return self.conn.execute(
            "SELECT * FROM runs ORDER BY id DESC LIMIT ?", (limit,)).fetchall()

    # ------------------------------------------------------------------ targets

    def targets(self) -> list[sqlite3.Row]:
        return self.conn.execute(
            "SELECT t.*, d.last_collect_status AS device_status, d.mgmt_address AS device_mgmt "
            "FROM targets t LEFT JOIN devices d ON d.id = t.device_id "
            "ORDER BY t.address").fetchall()

    def ensure_target(self, address: str, origin: str, depth: int, now: int) -> None:
        with self.conn:
            self.conn.execute(
                "INSERT INTO targets(address, origin, depth, first_seen) VALUES (?, ?, ?, ?) "
                "ON CONFLICT(address) DO UPDATE SET "
                "  origin = CASE WHEN excluded.origin = 'seed' THEN 'seed'"
                "    WHEN excluded.origin = 'manual' AND targets.origin != 'seed' THEN 'manual'"
                "    ELSE targets.origin END,"
                "  depth = MIN(targets.depth, excluded.depth)",
                (address, origin, depth, now))

    def demote_seeds(self, current_seeds: set[str]) -> None:
        """Targets that are no longer seeds keep being polled, as ordinary known targets."""
        rows = self.conn.execute("SELECT address FROM targets WHERE origin = 'seed'").fetchall()
        stale = [r[0] for r in rows if r[0] not in current_seeds]
        if stale:
            with self.conn:
                self.conn.executemany(
                    "UPDATE targets SET origin = 'state' WHERE address = ?", [(a,) for a in stale])

    def remove_target(self, address: str) -> None:
        """Forget an address, the device polled through it, and its manual settings."""
        host = split_host_port(address)[0]
        with self.conn:
            row = self.conn.execute("SELECT device_id FROM targets WHERE address = ?",
                                    (address,)).fetchone()
            if row and row[0] is not None:
                self.conn.execute("DELETE FROM targets WHERE device_id = ?", (row[0],))
                self.conn.execute("DELETE FROM devices WHERE id = ?", (row[0],))
            self.conn.execute("DELETE FROM targets WHERE address = ?", (address,))
            self.conn.execute("DELETE FROM manual_settings WHERE address = ?", (host,))

    # ------------------------------------------------------------------ manual settings

    def manual_settings(self) -> dict[str, dict[str, Any]]:
        result: dict[str, dict[str, Any]] = {}
        for row in self.conn.execute("SELECT address, key, value FROM manual_settings"):
            result.setdefault(row[0], {})[row[1]] = json.loads(row[2])
        return result

    def set_manual(self, address: str, values: dict[str, Any], now: int) -> None:
        with self.conn:
            self.conn.executemany(
                "INSERT INTO manual_settings(address, key, value, updated_at) VALUES (?, ?, ?, ?)"
                " ON CONFLICT(address, key) DO UPDATE SET value = excluded.value,"
                " updated_at = excluded.updated_at",
                [(address, k, json.dumps(v), now) for k, v in values.items()])

    def unset_manual(self, address: str, keys: list[str] | None = None) -> int:
        with self.conn:
            if keys is None:
                cur = self.conn.execute("DELETE FROM manual_settings WHERE address = ?",
                                        (address,))
            else:
                cur = self.conn.executemany(
                    "DELETE FROM manual_settings WHERE address = ? AND key = ?",
                    [(address, k) for k in keys])
        return cur.rowcount

    def dns_names(self, now: int) -> dict[str, str]:
        """Cached PTR names that are still valid."""
        return {r[0]: r[1] for r in self.conn.execute(
            "SELECT address, name FROM dns_cache WHERE status = 'ok' AND expires_at >= ?",
            (now,))}

    def dns_fresh(self, now: int) -> set[str]:
        return {r[0] for r in self.conn.execute(
            "SELECT address FROM dns_cache WHERE expires_at >= ?", (now,))}

    def save_dns(self, results: dict, now: int, positive_ttl: int, negative_ttl: int) -> None:
        with self.conn:
            self.conn.executemany(
                "INSERT INTO dns_cache(address, name, status, resolved_at, expires_at) "
                "VALUES (?, ?, ?, ?, ?) ON CONFLICT(address) DO UPDATE SET name = excluded.name, "
                "status = excluded.status, resolved_at = excluded.resolved_at, "
                "expires_at = excluded.expires_at",
                [(ip, name, status, now,
                  now + (positive_ttl if status == "ok" else negative_ttl))
                 for ip, (name, status) in results.items()])

    def last_outcomes(self, device_id: int) -> list[sqlite3.Row]:
        return self.conn.execute(
            "SELECT s.*, r.started_at FROM collect_status s JOIN runs r ON r.id = s.run_id "
            "WHERE s.device_id = ? AND s.run_id = (SELECT MAX(run_id) FROM collect_status "
            "WHERE device_id = ?) ORDER BY s.function", (device_id, device_id)).fetchall()

    def find_device(self, address: str) -> sqlite3.Row | None:
        """Device polled through ``address`` (with or without port), or owning that IP."""
        host = split_host_port(address)[0]
        return self.conn.execute(
            "SELECT * FROM devices WHERE mgmt_address = ? OR mgmt_address = ? "
            "OR mgmt_address LIKE ? OR id IN (SELECT device_id FROM targets WHERE address = ?) "
            "OR id IN (SELECT device_id FROM device_addresses WHERE address = ?) "
            "ORDER BY last_seen DESC LIMIT 1",
            (address, host, f"{host}:%", address, host)).fetchone()

    def device(self, device_id: int) -> sqlite3.Row | None:
        return self.conn.execute("SELECT * FROM devices WHERE id = ?", (device_id,)).fetchone()

    def remember_credential(self, address: str, credential: str | None, now: int) -> None:
        self.ensure_target(address, "state", 0, now)
        with self.conn:
            self.conn.execute("UPDATE targets SET credential = ? WHERE address = ?",
                              (credential, address))

    def target_failed(self, address: str, now: int, error: str) -> None:
        with self.conn:
            self.conn.execute(
                "UPDATE targets SET last_attempt_at = ?, last_error = ?, "
                "consecutive_failures = consecutive_failures + 1 WHERE address = ?",
                (now, error, address))

    def _target_ok(self, address: str, now: int, device_id: int, credential: str | None,
                   is_alias: bool) -> None:
        self.conn.execute(
            "UPDATE targets SET last_attempt_at = ?, last_ok_at = ?, device_id = ?, "
            "credential = ?, is_alias = ?, consecutive_failures = 0, last_error = NULL "
            "WHERE address = ?",
            (now, now, device_id, credential, int(is_alias), address))

    # ------------------------------------------------------------------ identity

    def match_device(self, *, serial: str, pen: int | None, base_mac: str | None,
                     sys_name: str, address: str) -> tuple[int | None, list[str]]:
        """Existing device for these identity keys: serial, then base MAC, then address+name."""
        warnings: list[str] = []
        by_serial = by_mac = None
        if serial:
            row = self.conn.execute(
                "SELECT id FROM devices WHERE serial = ? AND (pen IS ? OR pen IS NULL OR ? IS NULL)"
                " ORDER BY last_seen DESC LIMIT 1", (serial, pen, pen)).fetchone()
            by_serial = row[0] if row else None
        if base_mac:
            row = self.conn.execute(
                "SELECT id FROM devices WHERE base_mac = ? ORDER BY last_seen DESC LIMIT 1",
                (base_mac,)).fetchone()
            by_mac = row[0] if row else None
        if by_serial is not None:
            if by_mac is not None and by_mac != by_serial:
                warnings.append(f"base MAC {base_mac} is already known on another device "
                                f"(#{by_mac}); matched by serial number {serial} instead")
            return by_serial, warnings
        if by_mac is not None:
            return by_mac, warnings
        row = self.conn.execute(
            "SELECT d.id, d.serial FROM devices d LEFT JOIN targets t ON t.device_id = d.id "
            "WHERE (d.mgmt_address = ? OR t.address = ?) AND d.sys_name = ? "
            "ORDER BY d.last_seen DESC LIMIT 1", (address, address, sys_name)).fetchone()
        if row:
            if serial and row["serial"] and row["serial"] != serial:
                warnings.append(
                    f"serial number changed from {row['serial']} to {serial} at the same address "
                    "and sysName (HA failover or hardware replacement?)")
            return row["id"], warnings
        return None, warnings

    # ------------------------------------------------------------------ devices

    def save_device(self, r: DeviceResult, now: int, run_id: int) -> int:
        """Persist a reachable device (one transaction). Returns the device id."""
        assert r.system is not None and r.ident is not None
        s, ident = r.system, r.ident
        entity_known = r.outcome_status("entity") in (OK, ABSENT)
        keep = None  # "not observed this run": keep the stored value
        fields = {
            "mgmt_address": str(r.target),
            "serial": (ident.serial or None) if entity_known else keep,
            "base_mac": s.base_mac,
            "sys_name": s.name, "sys_descr": s.descr, "sys_object_id": s.object_id,
            "sys_location": s.location, "sys_contact": s.contact, "sys_uptime": s.uptime,
            "sys_services": s.services, "lldp_caps": s.lldp_caps,
            "vendor": ident.vendor, "pen": ident.pen,
            "model": ident.model if entity_known else keep,
            "os_name": ident.os_name,
            "os_version": ident.os_version if entity_known or ident.os_version else keep,
            "device_type": ident.device_type if entity_known else keep,
            "type_rule": ident.type_rule if entity_known else keep,
            "type_reason": ident.type_reason if entity_known else keep,
            "credential": r.credential,
            "driver": r.driver or None,
            "last_seen": now, "last_collect_at": now, "last_collect_status": r.status,
        }
        with self.conn:
            if r.device_id is None:
                cols = [k for k, v in fields.items() if v is not None] + ["first_seen"]
                values = [fields[k] for k in cols[:-1]] + [now]
                cur = self.conn.execute(
                    f"INSERT INTO devices({', '.join(cols)}) "  # noqa: S608 - fixed column names
                    f"VALUES ({', '.join('?' * len(cols))})", values)
                device_id = int(cur.lastrowid)
            else:
                device_id = r.device_id
                assignments = ", ".join(f"{k} = COALESCE(?, {k})" for k in fields)
                self.conn.execute(
                    f"UPDATE devices SET {assignments} WHERE id = ?",  # noqa: S608
                    [*fields.values(), device_id])
            self._save_details(device_id, r, now)
            self._save_observations(device_id, r, now, run_id)
            self._save_custom(device_id, r, now)
            self._save_synthetic(device_id, r, now, run_id)
            self._save_outcomes(run_id, device_id, r.outcomes.values())
            self._target_ok(str(r.target), now, device_id, r.credential, is_alias=False)
        return device_id

    def _save_details(self, device_id: int, r: DeviceResult, now: int) -> None:
        c = self.conn
        if r.outcome_status("entity") in (OK, ABSENT):
            c.execute("DELETE FROM device_chassis WHERE device_id = ?", (device_id,))
            c.executemany(
                "INSERT INTO device_chassis(device_id, ent_index, model, serial, sw_rev, descr) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                [(device_id, ch.index, ch.model, ch.serial, ch.sw_rev, ch.descr)
                 for ch in r.chassis])
        addresses = [(a.address, a.ifindex, a.prefix_len) for a in r.addresses]
        addresses.append((r.target.host, None, None))
        if r.outcome_status("ipaddr") == OK:
            c.execute("DELETE FROM device_addresses WHERE device_id = ?", (device_id,))
        c.executemany(
            "INSERT INTO device_addresses(device_id, address, ifindex, prefix_len, last_seen) "
            "VALUES (?, ?, ?, ?, ?) ON CONFLICT(device_id, address) DO UPDATE SET "
            "ifindex = COALESCE(excluded.ifindex, ifindex), "
            "prefix_len = COALESCE(excluded.prefix_len, prefix_len), "
            "last_seen = excluded.last_seen",
            [(device_id, a, i, p, now) for a, i, p in addresses])
        macs = []
        if r.system and r.system.bridge_mac:
            macs.append((r.system.bridge_mac, "bridge"))
        if r.system and r.system.chassis_mac:
            macs.append((r.system.chassis_mac, "lldp_chassis"))
        macs += [(i.phys_mac, "ifphys") for i in r.interfaces.values() if i.phys_mac]
        c.executemany(
            "INSERT INTO device_macs(device_id, mac, source, last_seen) VALUES (?, ?, ?, ?) "
            "ON CONFLICT(device_id, mac) DO UPDATE SET last_seen = excluded.last_seen",
            [(device_id, m, src, now) for m, src in macs])
        if r.outcome_status("interfaces") in (OK, PARTIAL):
            c.executemany(
                "INSERT INTO interfaces(device_id, ifindex, name, descr, alias, if_type, "
                "admin_status, oper_status, speed_mbps, phys_mac, lag_ifindex, last_seen) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(device_id, ifindex) DO UPDATE SET name = excluded.name, "
                "descr = excluded.descr, alias = excluded.alias, if_type = excluded.if_type, "
                "admin_status = excluded.admin_status, oper_status = excluded.oper_status, "
                "speed_mbps = excluded.speed_mbps, phys_mac = excluded.phys_mac, "
                "lag_ifindex = excluded.lag_ifindex, last_seen = excluded.last_seen",
                [(device_id, i.ifindex, i.name, i.descr, i.alias, i.if_type, i.admin_status,
                  i.oper_status, i.speed_mbps, i.phys_mac, i.lag_ifindex, now)
                 for i in r.interfaces.values()])

    def _save_synthetic(self, parent_id: int, r: DeviceResult, now: int, run_id: int) -> None:
        """Devices described by a driver (e.g. access points of a wireless controller).

        A synthetic device is matched by its base MAC. When that device is also polled
        directly, its polled identity is kept and only the stations are added.
        """
        if not r.synthetic or r.outcome_status(f"driver:{r.driver}") not in (OK, PARTIAL):
            return
        c = self.conn
        parent = r.system.name if r.system else f"#{parent_id}"
        vendor = r.ident.vendor if r.ident else ""
        for syn in r.synthetic:
            if not syn.address:
                continue                  # no management address: nothing to join on
            row = c.execute(
                "SELECT id, driver FROM devices WHERE base_mac = ? UNION "
                "SELECT d.id, d.driver FROM device_macs m JOIN devices d ON d.id = m.device_id "
                "WHERE m.mac = ? LIMIT 1", (syn.key_mac, syn.key_mac)).fetchone()
            fields = {
                "mgmt_address": syn.address, "sys_name": syn.name,
                "sys_descr": f"{syn.model or 'Access point'} (reported by {parent})",
                "sys_location": syn.location, "vendor": vendor, "model": syn.model,
                "serial": syn.serial or None, "os_version": syn.os_version,
                "device_type": syn.device_type, "type_rule": "driver",
                "type_reason": syn.type_reason, "driver": f"synthetic:{r.driver}",
                "base_mac": syn.key_mac, "last_seen": now, "last_collect_at": now,
                "last_collect_status": "ok",
            }
            if row is None:
                cols = [*fields, "first_seen"]
                cur = c.execute(
                    f"INSERT INTO devices({', '.join(cols)}) "  # noqa: S608 - fixed names
                    f"VALUES ({', '.join('?' * len(cols))})", [*fields.values(), now])
                device_id = int(cur.lastrowid)
            else:
                device_id = row["id"]
                if (row["driver"] or "").startswith("synthetic:"):
                    c.execute(f"UPDATE devices SET {', '.join(f'{k} = ?' for k in fields)} "  # noqa: S608
                              "WHERE id = ?", [*fields.values(), device_id])
                else:
                    c.execute("UPDATE devices SET last_seen = ? WHERE id = ?", (now, device_id))
            c.execute(
                "INSERT INTO device_macs(device_id, mac, source, last_seen) VALUES (?, ?, ?, ?) "
                "ON CONFLICT(device_id, mac) DO UPDATE SET last_seen = excluded.last_seen",
                (device_id, syn.key_mac, "driver", now))
            c.execute(
                "INSERT INTO device_addresses(device_id, address, last_seen) VALUES (?, ?, ?) "
                "ON CONFLICT(device_id, address) DO UPDATE SET last_seen = excluded.last_seen",
                (device_id, syn.address, now))
            c.executemany(
                "INSERT INTO interfaces(device_id, ifindex, name, descr, if_type, last_seen) "
                "VALUES (?, ?, ?, ?, 71, ?) ON CONFLICT(device_id, ifindex) DO UPDATE SET "
                "last_seen = excluded.last_seen",
                [(device_id, port, name, name, now) for port, name in syn.ports.items()])
            c.executemany(
                "INSERT INTO fdb_obs(mac, device_id, ifindex, vlan, vlan_source, method, "
                "first_seen, last_seen, last_run_id) VALUES (?, ?, ?, ?, 'none', ?, ?, ?, ?) "
                "ON CONFLICT(mac, device_id, ifindex, vlan) DO UPDATE SET "
                "last_seen = excluded.last_seen, last_run_id = excluded.last_run_id",
                [(mac, device_id, port, vlan, r.driver, now, now, run_id)
                 for mac, port, vlan in syn.stations])

    def _save_observations(self, device_id: int, r: DeviceResult, now: int, run_id: int) -> None:
        c = self.conn
        driver_extra = r.outcome_status(f"driver:{r.driver}") in (OK, PARTIAL)
        if r.outcome_status("fdb") in (OK, PARTIAL) or driver_extra:
            c.executemany(
                "INSERT INTO fdb_obs(mac, device_id, ifindex, vlan, vlan_source, method, "
                "first_seen, last_seen, last_run_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(mac, device_id, ifindex, vlan) DO UPDATE SET "
                "vlan_source = excluded.vlan_source, method = excluded.method, "
                "last_seen = excluded.last_seen, last_run_id = excluded.last_run_id",
                [(e.mac, device_id, e.ifindex, e.vlan, e.vlan_source, e.method, now, now, run_id)
                 for e in r.fdb])
            c.executemany(
                "UPDATE interfaces SET bridge_port = ? WHERE device_id = ? AND ifindex = ?",
                [(bp, device_id, ifx) for bp, ifx in r.bridge_ports.items()])
            c.executemany("UPDATE interfaces SET pvid = ? WHERE device_id = ? AND ifindex = ?",
                          [(vlan, device_id, ifx) for ifx, vlan in r.pvid.items()])
            c.executemany(
                "INSERT INTO vlans(device_id, vlan_id, name, last_seen) VALUES (?, ?, ?, ?) "
                "ON CONFLICT(device_id, vlan_id) DO UPDATE SET name = excluded.name, "
                "last_seen = excluded.last_seen",
                [(device_id, vlan, name, now) for vlan, name in r.vlans.items()])
        for protocol in ("lldp", "cdp"):
            if r.outcome_status(protocol) not in (OK, PARTIAL):
                continue
            c.executemany(
                "INSERT INTO neighbors(device_id, ifindex, protocol, remote_key, "
                "remote_chassis_id, remote_sys_name, remote_port_id, remote_port_desc, "
                "remote_mgmt_address, remote_caps, remote_platform, local_port_method, "
                "first_seen, last_seen, last_run_id) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(device_id, protocol, remote_key, remote_port_id) DO UPDATE SET "
                "ifindex = excluded.ifindex, remote_chassis_id = excluded.remote_chassis_id, "
                "remote_sys_name = excluded.remote_sys_name, "
                "remote_port_desc = excluded.remote_port_desc, "
                "remote_mgmt_address = excluded.remote_mgmt_address, "
                "remote_caps = excluded.remote_caps, remote_platform = excluded.remote_platform, "
                "local_port_method = excluded.local_port_method, "
                "last_seen = excluded.last_seen, last_run_id = excluded.last_run_id",
                [(device_id, n.local_ifindex, n.protocol, n.key, n.chassis_id, n.sys_name,
                  n.port_id, n.port_desc, ",".join(n.mgmt_addresses), ",".join(sorted(n.caps)),
                  n.platform, n.local_method, now, now, run_id)
                 for n in r.neighbors if n.protocol == protocol])
        if r.outcome_status("arp") in (OK, PARTIAL) or driver_extra:
            c.executemany(
                "INSERT INTO arp_obs(mac, address, family, device_id, ifindex, source_table, "
                "first_seen, last_seen, last_run_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(mac, address, device_id) DO UPDATE SET ifindex = excluded.ifindex, "
                "source_table = excluded.source_table, last_seen = excluded.last_seen, "
                "last_run_id = excluded.last_run_id",
                [(e.mac, e.ip, e.family, device_id, e.ifindex, e.table, now, now, run_id)
                 for e in r.arp])

    def _save_custom(self, device_id: int, r: DeviceResult, now: int) -> None:
        for name, (outcome, result) in r.custom.items():
            self.conn.execute(
                "INSERT INTO custom_runs(device_id, collector, run_at, status, rows, detail) "
                "VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT(device_id, collector) DO UPDATE SET "
                "run_at = excluded.run_at, status = excluded.status, rows = excluded.rows, "
                "detail = excluded.detail",
                (device_id, name, now, outcome.status, outcome.rows, outcome.detail))
            if outcome.status not in (OK, PARTIAL):
                continue
            self.conn.executemany(
                "INSERT INTO custom_values(device_id, collector, idx, column, value, raw, "
                "first_seen, last_seen) VALUES (?, ?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(device_id, collector, idx, column) DO UPDATE SET "
                "value = excluded.value, raw = excluded.raw, last_seen = excluded.last_seen",
                [(device_id, name, idx, column, value, raw, now, now)
                 for idx, column, value, raw in result.rows])

    def custom_current(self, device_id: int) -> dict[str, dict]:
        """Last pass of each collector on a device, with the values read at that pass."""
        runs = {row["collector"]: {"run_at": row["run_at"], "status": row["status"],
                                   "rows": row["rows"], "detail": row["detail"], "values": {},
                                   "table": []}
                for row in self.conn.execute("SELECT * FROM custom_runs WHERE device_id = ?",
                                             (device_id,))}
        for row in self.conn.execute(
                "SELECT v.* FROM custom_values v JOIN custom_runs r ON r.device_id = v.device_id "
                "AND r.collector = v.collector AND r.run_at = v.last_seen "
                "WHERE v.device_id = ? ORDER BY v.collector, v.idx, v.column", (device_id,)):
            entry = runs[row["collector"]]
            if row["idx"] == "":
                entry["values"][row["column"]] = row["value"]
            else:
                entry["table"].append((row["idx"], row["column"], row["value"]))
        return runs

    def custom_stored(self) -> dict[str, dict]:
        return {row[0]: json.loads(row[1]) for row in self.conn.execute(
            "SELECT name, definition FROM custom_collectors ORDER BY name")}

    def save_custom_collector(self, name: str, definition: dict, now: int) -> None:
        with self.conn:
            self.conn.execute(
                "INSERT INTO custom_collectors(name, definition, created_at, updated_at) "
                "VALUES (?, ?, ?, ?) ON CONFLICT(name) DO UPDATE SET "
                "definition = excluded.definition, updated_at = excluded.updated_at",
                (name, json.dumps(definition, sort_keys=True), now, now))

    def delete_custom_collector(self, name: str) -> bool:
        with self.conn:
            deleted = self.conn.execute("DELETE FROM custom_collectors WHERE name = ?",
                                        (name,)).rowcount
            self.conn.execute("DELETE FROM custom_values WHERE collector = ?", (name,))
            self.conn.execute("DELETE FROM custom_runs WHERE collector = ?", (name,))
        return bool(deleted)

    def reports_stored(self) -> dict[str, dict]:
        return {row[0]: json.loads(row[1]) for row in self.conn.execute(
            "SELECT name, definition FROM reports ORDER BY name")}

    def save_report(self, name: str, definition: dict, now: int) -> None:
        with self.conn:
            self.conn.execute(
                "INSERT INTO reports(name, definition, created_at, updated_at) "
                "VALUES (?, ?, ?, ?) ON CONFLICT(name) DO UPDATE SET "
                "definition = excluded.definition, updated_at = excluded.updated_at",
                (name, json.dumps(definition, sort_keys=True), now, now))

    def delete_report(self, name: str) -> bool:
        with self.conn:
            return bool(self.conn.execute("DELETE FROM reports WHERE name = ?",
                                          (name,)).rowcount)

    def _save_outcomes(self, run_id: int, device_id: int, outcomes) -> None:
        self.conn.executemany(
            "INSERT OR REPLACE INTO collect_status(run_id, device_id, function, status, rows, "
            "duration_ms, detail) VALUES (?, ?, ?, ?, ?, ?, ?)",
            [(run_id, device_id, o.function, o.status, o.rows, o.duration_ms, o.detail)
             for o in outcomes])

    def save_alias(self, r: DeviceResult, device_id: int, now: int) -> None:
        with self.conn:
            self.conn.execute(
                "INSERT INTO device_addresses(device_id, address, last_seen) VALUES (?, ?, ?) "
                "ON CONFLICT(device_id, address) DO UPDATE SET last_seen = excluded.last_seen",
                (device_id, r.target.host, now))
            self._target_ok(str(r.target), now, device_id, r.credential, is_alias=True)

    def save_failure(self, r: DeviceResult, now: int, run_id: int, device_id: int | None) -> None:
        with self.conn:
            self.conn.execute(
                "UPDATE targets SET last_attempt_at = ?, last_error = ?, "
                "consecutive_failures = consecutive_failures + 1 WHERE address = ?",
                (now, r.error, str(r.target)))
            if device_id is not None:
                self.conn.execute(
                    "UPDATE devices SET last_collect_at = ?, last_collect_status = 'failed' "
                    "WHERE id = ?", (now, device_id))
                self._save_outcomes(run_id, device_id,
                                    [Outcome("system", "timeout" if r.error and "timeout"
                                             in r.error else "error", detail=r.error or "")])

    def devices(self, since: int | None = None) -> list[sqlite3.Row]:
        if since is None:
            return self.conn.execute("SELECT * FROM devices ORDER BY id").fetchall()
        return self.conn.execute(
            "SELECT * FROM devices WHERE last_seen >= ? ORDER BY id", (since,)).fetchall()

    def device_macs(self) -> set[str]:
        return {r[0] for r in self.conn.execute("SELECT mac FROM device_macs")}

    def statuses(self, run_id: int) -> list[sqlite3.Row]:
        return self.conn.execute(
            "SELECT * FROM collect_status WHERE run_id = ? ORDER BY device_id, function",
            (run_id,)).fetchall()

    def forget_dns(self, only_misses: bool = False) -> int:
        """Drop the cached PTR answers so the next export asks again.

        A "no name" is remembered for ``dns.negative_ttl`` (an hour), which is right in normal
        running and wrong right after the resolver is corrected: the fix would stay invisible
        for as long. ``only_misses`` keeps the names already found.
        """
        with self.conn:
            if only_misses:
                return self.conn.execute(
                    "DELETE FROM dns_cache WHERE status != 'ok'").rowcount
            return self.conn.execute("DELETE FROM dns_cache").rowcount

    def forget_nodes(self) -> dict[str, int]:
        """Drop every MAC and ARP observation, keeping the devices, the links and the names.

        A MAC table remembers for weeks and an old mistake (a trunk taken for an access port,
        a device that has moved) stays visible for as long. This empties the memory so that the
        next collect fills it again from what the network says today. Nothing else is touched:
        the inventory, the topology, the names given by hand and the runs stay.
        """
        with self.conn:
            counts = {"fdb": self.conn.execute("DELETE FROM fdb_obs").rowcount,
                      "arp": self.conn.execute("DELETE FROM arp_obs").rowcount}
        self.conn.execute("VACUUM")          # a MAC table is most of the file
        return counts

    # ------------------------------------------------------------------ retention

    def purge(self, now: int, retention_days: int, forget_after_days: int,
              nodes_retention_days: int = 30) -> dict[str, int]:
        c = self.conn
        counts = {}
        with c:
            horizon = now - nodes_retention_days * DAY
            counts["fdb"] = c.execute("DELETE FROM fdb_obs WHERE last_seen < ?",
                                      (horizon,)).rowcount
            counts["arp"] = c.execute("DELETE FROM arp_obs WHERE last_seen < ?",
                                      (horizon,)).rowcount
            counts["neighbors"] = c.execute(
                "DELETE FROM neighbors WHERE last_seen < ?",
                (now - retention_days * DAY,)).rowcount
            c.execute("DELETE FROM dns_cache WHERE expires_at < ?", (now - 30 * DAY,))
            c.execute("DELETE FROM custom_values WHERE last_seen < ?",
                      (now - retention_days * DAY,))
            counts["devices"] = c.execute(
                "DELETE FROM devices WHERE last_seen < ?", (now - retention_days * DAY,)).rowcount
            counts["targets"] = c.execute(
                "DELETE FROM targets WHERE origin NOT IN ('seed', 'manual') AND "
                "COALESCE(last_ok_at, first_seen, 0) < ?",
                (now - forget_after_days * DAY,)).rowcount
            c.execute(
                "DELETE FROM collect_status WHERE run_id NOT IN "
                "(SELECT id FROM runs ORDER BY id DESC LIMIT ?)", (KEEP_STATUS_RUNS,))
            c.execute("DELETE FROM runs WHERE started_at < ?", (now - KEEP_RUNS_DAYS * DAY,))
        return counts
