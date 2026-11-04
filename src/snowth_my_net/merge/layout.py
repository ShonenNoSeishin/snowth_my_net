"""A layered drawing of a network: the root on top, one row per hop away from it.

Deterministic (same links, same drawing), no dependency, and readable on a tree with a few
redundant links, which is what a switched network is. A force layout was the alternative: it
looks lively and puts the core wherever it falls, which is the opposite of what a reader of a
topology wants — "what hangs under what".

Nodes with no link at all are not part of the picture of the network; they are placed in a
block of their own below it, so that a device announcing no neighbour is seen as such.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass

DX = 210                  # distance between two nodes of a row
DY = 150                  # distance between two rows
GAP = 1                   # empty slots between two separate networks
ISOLATED_PER_ROW = 8
SWEEPS = 4


@dataclass(frozen=True)
class Placed:
    x: float
    y: float
    layer: int            # hops from the root of its network; -1 for a node without link
    network: int          # which connected group, 0 for the largest; -1 for a node without link


def layered(labels: dict[str, str], edges: list[tuple[str, str]],
            root: str | None = None) -> dict[str, Placed]:
    """``labels`` maps each node id to the text it is ordered by; ``root`` is preferred as the
    top of the network it belongs to (any other network picks its best connected node)."""
    adj: dict[str, set[str]] = {n: set() for n in labels}
    for a, b in edges:
        if a != b and a in adj and b in adj:
            adj[a].add(b)
            adj[b].add(a)

    def order(n: str) -> tuple[str, str]:
        return labels[n].casefold(), n

    seen: set[str] = set()
    networks: list[list[str]] = []
    isolated = []
    for n in sorted(labels, key=order):
        if n in seen:
            continue
        group, queue = [], deque([n])
        seen.add(n)
        while queue:
            cur = queue.popleft()
            group.append(cur)
            for nxt in sorted(adj[cur], key=order):
                if nxt not in seen:
                    seen.add(nxt)
                    queue.append(nxt)
        (networks if len(group) > 1 else isolated).append(group)
    networks.sort(key=lambda g: (-len(g), order(min(g, key=order))))

    placed: dict[str, Placed] = {}
    cursor = 0.0                         # left edge of the next network, in slots
    for index, group in enumerate(networks):
        start = root if root in group else min(
            group, key=lambda n: (-len(adj[n]), *order(n)))
        layer = {start: 0}
        queue = deque([start])
        while queue:
            cur = queue.popleft()
            for nxt in sorted(adj[cur], key=order):
                if nxt not in layer:
                    layer[nxt] = layer[cur] + 1
                    queue.append(nxt)
        rows: list[list[str]] = [[] for _ in range(max(layer.values()) + 1)]
        for n in sorted(group, key=order):
            rows[layer[n]].append(n)
        _untangle(rows, adj)
        slots = _spread(rows, adj, layer)
        left = min(slots.values())
        for n, slot in slots.items():
            placed[n] = Placed((cursor + slot - left) * DX, layer[n] * DY, layer[n], index)
        cursor += max(slots.values()) - left + 1 + GAP

    if isolated:
        top = (max((p.y for p in placed.values()), default=-DY) + DY * 1.4) if placed else 0
        singles = sorted((g[0] for g in isolated), key=order)
        for i, n in enumerate(singles):
            placed[n] = Placed((i % ISOLATED_PER_ROW) * DX, top + (i // ISOLATED_PER_ROW) * DY,
                               -1, -1)
    return placed


def _untangle(rows: list[list[str]], adj: dict[str, set[str]]) -> None:
    """Barycentre sweeps: each node moves toward the average place of its neighbours in the
    row it was just aligned against, which removes most crossings of a tree plus a few links."""
    for _ in range(SWEEPS):
        for step in (1, -1):
            span = range(1, len(rows)) if step == 1 else range(len(rows) - 2, -1, -1)
            for depth in span:
                column = {n: i for i, n in enumerate(rows[depth - step])}
                current = {n: i for i, n in enumerate(rows[depth])}

                def centre(n: str, column=column, current=current) -> float:
                    near = [column[m] for m in adj[n] if m in column]
                    return sum(near) / len(near) if near else current[n]

                rows[depth].sort(key=lambda n, c=centre: (c(n), current[n]))


def _spread(rows: list[list[str]], adj: dict[str, set[str]],
            layer: dict[str, int]) -> dict[str, float]:
    """Horizontal places, in slots of one node: children under their parent, a parent over its
    children, never two nodes closer than one slot and never a change of order.

    Each pass moves a row toward where the row above (or below) wants it, then pushes apart
    whatever overlaps and re-centres the row on what it wanted — so a long row opens up around
    its crowded part instead of drifting to one side.
    """
    x: dict[str, float] = {}
    for row in rows:
        for i, n in enumerate(row):
            x[n] = i - (len(row) - 1) / 2

    def settle(row: list[str], wanted: dict[str, float]) -> None:
        pos, previous = [], None
        for n in row:
            here = wanted[n] if previous is None else max(wanted[n], previous + 1)
            pos.append(here)
            previous = here
        drift = sum(w - p for w, p in zip((wanted[n] for n in row), pos, strict=True)) / len(row)
        for n, p in zip(row, pos, strict=True):
            x[n] = p + drift
        for i in range(1, len(row)):             # the shift must not close a gap
            x[row[i]] = max(x[row[i]], x[row[i - 1]] + 1)

    for _ in range(3):
        for depth in range(1, len(rows)):
            settle(rows[depth], {n: _mean([x[m] for m in adj[n] if layer[m] == depth - 1], x[n])
                                 for n in rows[depth]})
        for depth in range(len(rows) - 2, -1, -1):
            settle(rows[depth], {n: _mean([x[m] for m in adj[n] if layer[m] == depth + 1], x[n])
                                 for n in rows[depth]})
    return x


def _mean(values: list[float], default: float) -> float:
    return sum(values) / len(values) if values else default
