"""Stable identities for restoring a GTK inventory after asynchronous refresh."""
from dataclasses import dataclass, field


@dataclass
class ApplicationViewState:
    ordered_ids: list[str] = field(default_factory=list)
    anchor_id: str | None = None
    anchor_offset: float = 0.0
    selected_ids: set[str] = field(default_factory=set)
    scroll_value: float = 0.0

    def surviving_anchor(self, available: set[str]) -> str | None:
        if self.anchor_id in available:
            return self.anchor_id
        if self.anchor_id not in self.ordered_ids:
            return None
        index = self.ordered_ids.index(self.anchor_id)
        # Prefer the following row; at the end use the preceding row.
        for identity in self.ordered_ids[index + 1:] + self.ordered_ids[:index][::-1]:
            if identity in available:
                return identity
        return None
