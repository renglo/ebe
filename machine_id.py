"""Stable per-laptop id for ebe. Same rules as renglo.schd.schd_machine_id."""

from __future__ import annotations

import os
import subprocess
import sys
import uuid
from pathlib import Path

_CACHE = Path.home() / ".renglo" / "schd_machine_id"
_cached: str | None = None


def schd_machine_id() -> str:
    global _cached
    if _cached:
        return _cached
    from_env = str(os.environ.get("SCHD_MACHINE_ID") or "").strip()
    if from_env:
        _cached = from_env
        return _cached
    try:
        text = _CACHE.read_text().strip()
        if text:
            _cached = text
            return _cached
    except OSError:
        pass
    resolved = _os_machine_id() or uuid.uuid4().hex
    try:
        _CACHE.parent.mkdir(parents=True, exist_ok=True)
        _CACHE.write_text(resolved + "\n")
    except OSError:
        pass
    _cached = resolved
    return _cached


def _os_machine_id() -> str:
    if sys.platform == "darwin":
        try:
            out = subprocess.check_output(
                ["ioreg", "-rd1", "-c", "IOPlatformExpertDevice"],
                text=True,
                timeout=5,
            )
        except (OSError, subprocess.SubprocessError):
            return ""
        for line in out.splitlines():
            if "IOPlatformUUID" not in line:
                continue
            parts = line.split('"', 3)
            if len(parts) >= 4:
                return parts[3].rstrip('"').strip()
        return ""
    if sys.platform.startswith("linux"):
        for path in (Path("/etc/machine-id"), Path("/var/lib/dbus/machine-id")):
            try:
                text = path.read_text().strip()
                if text:
                    return text
            except OSError:
                continue
        return ""
    return ""
