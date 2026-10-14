"""A bounded operation history containing only redacted summaries."""

from datetime import datetime, timezone
import json
import os
from pathlib import Path

from sourcedock.core.process import redact_text
from sourcedock.core.json_store import write_json


class OperationHistory:
    def __init__(self, path=None):
        cache = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache"))
        if path:
            self.path = Path(path)
        else:
            current_path = cache / "sourcedock" / "history.json"
            legacy_path = cache / "voltapp" / "history.json"
            self.path = current_path if current_path.exists() or not legacy_path.exists() else legacy_path

    def load(self):
        try:
            items = json.loads(self.path.read_text(encoding="utf-8"))
            return (
                [
                    item
                    for item in items
                    if isinstance(item, dict)
                    and all(
                        isinstance(item.get(key, ""), str) for key in ("time", "action", "source", "message")
                    )
                ][-200:]
                if isinstance(items, list)
                else []
            )
        except (OSError, ValueError):
            return []

    def append(self, action, source, success, message):
        items = self.load()
        items.append(
            {
                "time": datetime.now(timezone.utc).isoformat(),
                "action": redact_text(action),
                "source": redact_text(source),
                "success": bool(success),
                "message": redact_text(message),
            }
        )
        self.save(items[-200:])

    def save(self, items):
        write_json(self.path, items)

    def clear(self):
        self.save([])

    def export(self, path):
        Path(path).write_text(json.dumps(self.load(), ensure_ascii=False, indent=2), encoding="utf-8")
