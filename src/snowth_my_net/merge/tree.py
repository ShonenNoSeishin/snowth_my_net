"""The network as a tree, for the terminal: each device under the one it was reached through.

The same links as the Topology page, read the other way: breadth first from the best connected
device, so a core switch comes first and an access switch hangs under its distribution switch.
A link that closes a loop (a redundant uplink, a second cable of a trunk) is not a branch; it is
listed on the device that meets it, as "also".
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Edge:
    a: str
    a_port: str
    b: str
    b_port: str
    protocol: str = ""


@dataclass
class Extra:
    port: str                  # on this device
    other: str
    other_port: str
    protocol: str


@dataclass
class TreeNode:
    name: str
    port: str = ""             # this device's port towards its parent
    parent_port: str = ""      # the parent's port towards this device
    protocol: str = ""
    children: list[TreeNode] = field(default_factory=list)
    extras: list[Extra] = field(default_factory=list)


def build_tree(names: list[str], edges: list[Edge]) -> tuple[list[TreeNode], list[str]]:
    """``(roots, isolated)``: one root per connected group, the biggest first, and the names
    that no link touches."""
    known = set(names)
    links: dict[str, list[tuple[int, Edge]]] = {n: [] for n in names}
    clean = [e for e in edges if e.a != e.b and e.a in known and e.b in known]
    for i, e in enumerate(clean):
        links[e.a].append((i, e))
        links[e.b].append((i, e))

    def other(n: str, e: Edge) -> tuple[str, str, str]:
        """(neighbour, my port, its port)"""
        return (e.b, e.a_port, e.b_port) if e.a == n else (e.a, e.b_port, e.a_port)

    seen: set[str] = set()
    groups: list[tuple[int, str, TreeNode]] = []
    order = sorted(names, key=lambda n: (-len(links[n]), n.casefold()))
    used: set[int] = set()
    for start in order:
        if start in seen or not links[start]:
            continue
        root = TreeNode(start)
        seen.add(start)
        nodes = {start: root}
        queue = deque([root])
        while queue:
            node = queue.popleft()
            for i, e in sorted(links[node.name],
                               key=lambda item: (other(node.name, item[1])[0].casefold(),
                                                 other(node.name, item[1])[1])):
                if i in used:
                    continue
                used.add(i)
                neighbour, mine, theirs = other(node.name, e)
                if neighbour in seen:
                    node.extras.append(Extra(mine, neighbour, theirs, e.protocol))
                    continue
                seen.add(neighbour)
                child = TreeNode(neighbour, theirs, mine, e.protocol)
                node.children.append(child)
                nodes[neighbour] = child
                queue.append(child)
        groups.append((len(nodes), start, root))
    groups.sort(key=lambda g: (-g[0], g[1].casefold()))
    isolated = sorted((n for n in names if n not in seen), key=str.casefold)
    return [root for _size, _name, root in groups], isolated
