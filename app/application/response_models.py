from dataclasses import dataclass, field
from typing import Any


@dataclass
class AppAction:
    label: str
    action: str
    ticket_id: str


@dataclass
class AppResult:
    status: str
    message: str
    files: list[str] = field(default_factory=list)
    actions: list[AppAction] = field(default_factory=list)
    data: dict[str, Any] = field(default_factory=dict)