"""Line-delimited JSON protocol used by the STEP import worker.

The worker's stdout is intentionally a small, versioned interface: unrelated
library output and incomplete lines must never be interpreted as UI commands.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from typing import Any


PROTOCOL_VERSION = 1


def encode_message(kind: str, **payload: object) -> str:
    """Return one ASCII-safe protocol line."""
    return json.dumps({"version": PROTOCOL_VERSION, "kind": kind, **payload}, ensure_ascii=True) + "\n"


def _parse_message(raw: object) -> dict[str, object] | None:
    if not isinstance(raw, dict) or raw.get("version") != PROTOCOL_VERSION:
        return None
    kind = raw.get("kind")
    if kind == "progress":
        value = raw.get("value")
        label = raw.get("label")
        if not isinstance(value, int | float) or isinstance(value, bool) or not isinstance(label, str):
            return None
        return {"kind": kind, "value": max(0, min(100, int(value))), "label": label}
    if kind == "stage":
        name = raw.get("name")
        return {"kind": kind, "name": name} if isinstance(name, str) else None
    if kind == "error":
        message = raw.get("message")
        return {"kind": kind, "message": message} if isinstance(message, str) else None
    if kind == "done":
        return {"kind": kind}
    return None


def consume_messages(buffer: str, chunk: str) -> tuple[list[dict[str, object]], str]:
    """Decode complete valid messages and preserve an unfinished final line."""
    lines = (buffer + chunk).split("\n")
    tail = lines.pop()
    messages: list[dict[str, object]] = []
    for line in lines:
        try:
            parsed: Any = json.loads(line)
        except json.JSONDecodeError:
            continue
        message = _parse_message(parsed)
        if message is not None:
            messages.append(message)
    return messages, tail


def describe_messages(messages: Iterable[dict[str, object]]) -> str | None:
    """Return the last explicit worker error, if the stream contains one."""
    return next((str(message["message"]) for message in reversed(list(messages)) if message["kind"] == "error"), None)
