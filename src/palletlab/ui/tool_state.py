"""Small, UI-independent state machine for mutually exclusive edit tools."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


ToolMode = Literal["none", "insertion", "deletion", "distance_editing", "section_editing"]


@dataclass
class ToolStateMachine:
    """Track one active tool and describe every state transition."""

    active: ToolMode = "none"

    def transition(self, tool: ToolMode, enabled: bool) -> tuple[ToolMode, ToolMode]:
        previous = self.active
        if enabled:
            self.active = tool
        elif self.active == tool:
            self.active = "none"
        return previous, self.active
