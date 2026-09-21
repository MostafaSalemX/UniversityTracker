"""Persisted memory of what the checker has already seen."""
from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field


@dataclass
class EventState:
    due: int
    reminded_3d: bool = False
    reminded_24h: bool = False


@dataclass
class State:
    version: int = 1
    initialized: bool = False
    failing: bool = False
    courses: dict[str, str] = field(default_factory=dict)
    events: dict[str, EventState] = field(default_factory=dict)
    discussions: set[str] = field(default_factory=set)
    modules: set[str] = field(default_factory=set)
    grades: dict[str, str] = field(default_factory=dict)


def load(path: str) -> State:
    if not os.path.exists(path):
        return State()
    with open(path, encoding="utf-8") as f:
        raw = json.load(f)
    return State(
        version=raw.get("version", 1),
        initialized=raw.get("initialized", False),
        failing=raw.get("failing", False),
        courses=dict(raw.get("courses", {})),
        events={k: EventState(**v) for k, v in raw.get("events", {}).items()},
        discussions=set(raw.get("discussions", [])),
        modules=set(raw.get("modules", [])),
        grades=dict(raw.get("grades", {})),
    )


def save(state: State, path: str) -> None:
    raw = asdict(state)
    raw["discussions"] = sorted(state.discussions)
    raw["modules"] = sorted(state.modules)
    parent = os.path.dirname(os.path.abspath(path))
    os.makedirs(parent, exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(raw, f, indent=2, sort_keys=True)
    os.replace(tmp, path)
