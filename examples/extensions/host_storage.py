"""Example Python extension: disk and memory usage of hosts running net-snmp.

Enable it by copying this file into the extensions directory and listing it:

    general:
      python_extensions: [host_storage]

It shows the three extension points:

* a table collector reading HOST-RESOURCES-MIB hrStorageTable (values appear in the device
  sheet, in snapshot.json and in the report dataset ``custom:host-storage``);
* a report dataset ``py:disk-usage`` with typed numbers, so reports can filter on them
  (``used_pct gt 85``);
* an exporter writing a Prometheus "textfile collector" file, ``metrics/snowth_my_net.prom``.

Test it without a network: see tests in the snowth_my_net repository
(``tests/unit/test_python_extensions.py``) and :mod:`snowth_my_net.testing`.
"""

from snowth_my_net.api import Extension, Field, number, text

extension = Extension("host_storage")

HR_STORAGE = "1.3.6.1.2.1.25.2.3.1"
KINDS = {"1.3.6.1.2.1.25.2.1.2": "ram", "1.3.6.1.2.1.25.2.1.3": "virtual",
         "1.3.6.1.2.1.25.2.1.4": "disk"}


@extension.collector(
    "host-storage", table=True,
    columns=["kind", "description", "size_gb", "used_gb", "used_pct"],
    applies_to={"sys_object_ids": ["1.3.6.1.4.1.8072.3.2"]},     # net-snmp agents
    every="1h", description="Disk and memory usage (HOST-RESOURCES-MIB)")
async def host_storage(device, snmp):
    columns = {}
    for arc, key in ((2, "type"), (3, "descr"), (4, "unit"), (5, "size"), (6, "used")):
        for index, value in await snmp.walk(f"{HR_STORAGE}.{arc}"):
            columns.setdefault(index, {})[key] = value
    rows = []
    for index, entry in sorted(columns.items(), key=lambda item: int(item[0])):
        kind = KINDS.get(text(entry.get("type")))
        unit, size, used = (number(entry.get(k)) for k in ("unit", "size", "used"))
        if kind is None or not unit or not size or used is None:
            continue                     # CD-ROMs, network mounts without sizes…
        rows.append({"index": index, "kind": kind, "description": text(entry.get("descr")),
                     "size_gb": round(size * unit / 1e9, 1),
                     "used_gb": round(used * unit / 1e9, 1),
                     "used_pct": round(100 * used / size)})
    return rows


@extension.report_dataset(
    "disk-usage", description="Storage usage per host, with numbers you can filter on",
    fields=[Field("device"), Field("kind"), Field("description"),
            Field("size_gb", "integer", "size in GB (rounded)"),
            Field("used_pct", "integer", "percentage used"),
            Field("collected", "time", default=False)])
def disk_usage(ctx):
    return [{"device": row["device"], "kind": row["kind"], "description": row["description"],
             "size_gb": round(float(row["size_gb"] or 0)),
             "used_pct": int(row["used_pct"]) if row["used_pct"] else None,
             "collected": row["collected"]}
            for row in ctx.dataset_rows("custom:host-storage")]


@extension.exporter("metrics/snowth_my_net.prom",
                    description="Prometheus textfile: devices, nodes and collect status")
def prometheus(snapshot):
    def label(value):
        return str(value).replace("\\", "\\\\").replace('"', '\\"').replace("\n", " ")

    lines = ["# HELP snowth_devices Managed devices within the retention window.",
             "# TYPE snowth_devices gauge", f"snowth_devices {len(snapshot['devices'])}",
             "# HELP snowth_nodes End nodes currently known.", "# TYPE snowth_nodes gauge",
             f"snowth_nodes {len(snapshot['nodes'])}",
             "# HELP snowth_device_ok 1 when the last collect of the device succeeded.",
             "# TYPE snowth_device_ok gauge"]
    for device in snapshot["devices"]:
        ok = 1 if device.get("last_collect_status") == "ok" else 0
        lines.append(f'snowth_device_ok{{device="{label(device["name"])}"}} {ok}')
    return ("\n".join(lines) + "\n").encode("utf-8")
