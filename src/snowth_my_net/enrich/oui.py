"""MAC address vendors from the IEEE registries (MA-L, MA-M, MA-S).

The database is a gzip'd TSV of ``<hex prefix>\\t<organization name>`` lines, where the prefix
has 6 (MA-L), 7 (MA-M) or 9 (MA-S) hex digits. A copy is embedded in the package; ``oui-update``
writes a fresher one to the state directory, which then takes precedence.
"""

from __future__ import annotations

import csv
import gzip
import io
import re
import urllib.request
from collections.abc import Iterable
from importlib import resources
from pathlib import Path

from snowth_my_net.export.atomic import atomic_write
from snowth_my_net.snmp.values import is_locally_administered

# IEEE rejects the default Python-urllib User-Agent with HTTP 418.
USER_AGENT = "snowth_my_net (+oui-update)"
PREFIX_LENGTHS = (9, 7, 6)
REGISTRY_FILES = ("oui.csv", "mam.csv", "oui36.csv")

_SUFFIX = re.compile(
    r"[\s,]+(incorporated|inc|corporation|corp|company|co|limited|ltd|llc|l\.l\.c|gmbh|ag|"
    r"s\.?a\.?s?|s\.?p\.?a|s\.?r\.?l|b\.?v|n\.?v|oy|ab|a/s|as|kg|plc|pte|pty|k\.?k|sarl|"
    r"sdn\.? bhd|bhd)\.?$",
    re.IGNORECASE,
)
_CO = re.compile(r"[\s,]+co\.?$", re.IGNORECASE)


def clean_name(name: str) -> str:
    """``"Cisco Systems, Inc"`` -> ``"Cisco Systems"``; ``"HUAWEI TECHNOLOGIES CO.,LTD"`` ->
    ``"HUAWEI TECHNOLOGIES"``. Never returns an empty string for a non-empty name."""
    text = re.sub(r"\s+", " ", name).strip().strip(",")
    shorter = _SUFFIX.sub("", text).strip().strip(",").strip()
    if not shorter or shorter == text:
        return text
    # "Co., Ltd." style: one legal form may follow "Co", but "Big Corp, Inc." keeps "Corp".
    shortest = _CO.sub("", shorter).strip().strip(",").strip()
    return shortest or shorter


class OuiDatabase:
    def __init__(self, entries: dict[str, str]) -> None:
        self._entries = entries

    def __len__(self) -> int:
        return len(self._entries)

    @classmethod
    def from_tsv(cls, data: bytes) -> OuiDatabase:
        entries = {}
        for line in gzip.decompress(data).decode("utf-8").splitlines():
            prefix, _, name = line.partition("\t")
            if prefix and name:
                entries[prefix.lower()] = name
        return cls(entries)

    def lookup(self, mac: str, clean: bool = True) -> str:
        """Vendor of a normalized MAC, or ``""`` (unknown, or locally administered)."""
        if not mac or is_locally_administered(mac):
            return ""
        compact = mac.replace(":", "").lower()
        for length in PREFIX_LENGTHS:
            name = self._entries.get(compact[:length])
            if name:
                return clean_name(name) if clean else name
        return ""


def parse_registries(csv_texts: Iterable[str]) -> dict[str, str]:
    """IEEE CSV files (any of MA-L/MA-M/MA-S) -> ``{hex prefix: organization}``."""
    entries: dict[str, str] = {}
    for text in csv_texts:
        reader = csv.reader(io.StringIO(text))
        header = next(reader, None)
        if not header or header[:3] != ["Registry", "Assignment", "Organization Name"]:
            raise ValueError("not an IEEE registry CSV (unexpected header)")
        for row in reader:
            if len(row) < 3:
                continue
            prefix = row[1].strip().lower()
            name = re.sub(r"\s+", " ", row[2]).strip()
            if re.fullmatch(r"[0-9a-f]{6}|[0-9a-f]{7}|[0-9a-f]{9}", prefix) and name:
                entries[prefix] = name
    if len(entries) < 1000:
        raise ValueError(f"only {len(entries)} registry entries found; refusing to use them")
    return entries


def to_tsv(entries: dict[str, str]) -> bytes:
    body = "".join(f"{p}\t{entries[p]}\n" for p in sorted(entries))
    return gzip.compress(body.encode("utf-8"), mtime=0)


def load_database(state_copy: Path | None = None, explicit: Path | None = None) -> OuiDatabase:
    """Explicit file > state-directory copy (``oui-update``) > embedded copy."""
    for candidate in (explicit, state_copy):
        if candidate is not None and candidate.exists():
            return OuiDatabase.from_tsv(candidate.read_bytes())
    data = resources.files("snowth_my_net.enrich").joinpath("data/oui.tsv.gz").read_bytes()
    return OuiDatabase.from_tsv(data)


def download_registries(urls: list[str], timeout: float = 120) -> list[str]:
    texts = []
    for url in urls:
        if not url.startswith("https://"):
            raise ValueError(f"refusing a non-HTTPS registry URL: {url}")
        request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})  # noqa: S310
        with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
            texts.append(response.read().decode("utf-8", errors="replace"))
    return texts


def update_database(dest: Path, urls: list[str], from_dir: Path | None = None) -> int:
    """Refresh ``dest`` from the IEEE (or local CSV copies); returns the number of prefixes."""
    if from_dir is not None:
        texts = [p.read_text(encoding="utf-8", errors="replace")
                 for name in REGISTRY_FILES if (p := from_dir / name).exists()]
        if not texts:
            raise ValueError(f"no {', '.join(REGISTRY_FILES)} in {from_dir}")
    else:
        texts = download_registries(urls)
    entries = parse_registries(texts)
    atomic_write(dest, to_tsv(entries))
    return len(entries)
