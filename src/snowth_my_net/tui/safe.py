"""What the terminal interface shows of text it did not write.

Textual and Rich read square brackets as markup: a neighbour that announces ``[/x]`` as its port
name, or a host that states ``[@click=...]`` as its name, would otherwise stop the interface or
plant an action under a click. Everything that comes from a device or a host goes through here,
never through markup.
"""

from __future__ import annotations

from rich.text import Text
from textual.widgets import DataTable


def escape(text: object) -> str:
    """Every bracket made literal (Textual's own ``escape`` only covers some tag shapes)."""
    return str(text).replace("\\", "\\\\").replace("[", "\\[")


class SafeTable(DataTable):
    """A table whose text cells are text, never markup."""

    def add_row(self, *cells, height=1, key=None, label=None):
        shown = [Text(cell) if isinstance(cell, str) else cell for cell in cells]
        if isinstance(label, str):
            label = Text(label)
        return super().add_row(*shown, height=height, key=key, label=label)
