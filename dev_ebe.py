#!/usr/bin/env python3
"""
Local EventBridge emulator (ebe) for development.

IMPORTANT: Dev-only. Production uses EventBridge scheduled rules + PutEvents
fan-out to the webhook API Destination → /_schd/ingress.

This process:
  - stores scheduled rules the local API registers (Schedule UI → Local)
  - ticks every UTC minute and POSTs due payloads to local ingress
  - accepts PutEvents fan-out and POSTs each job to ingress sequentially
  - only fires rules stamped with this machine's id

Typical flow:
  API (origin=local) → PUT /rules, POST /events → this service (:5056)
                     └─ minute tick / queue → POST http://127.0.0.1:5001/_schd/ingress
"""

from __future__ import annotations

import importlib.util
import json
import os
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from queue import Queue
from typing import Any

import requests
from flask import Flask, jsonify, request

from schedule import expression_is_due
from machine_id import schd_machine_id
from activity_store import ActivityStore

app = Flask(__name__)

_HERE = Path(__file__).resolve().parent
_DEFAULT_ENV_CONFIG = _HERE.parent / "renglo-api" / "env_config.py"
RULES_PATH = Path(os.environ.get("EBE_RULES_PATH") or _HERE / "rules.json")
ACTIVITY_DIR = Path(os.environ.get("EBE_ACTIVITY_DIR") or _HERE / "tmp" / "activity")
_legacy_activity = os.environ.get("EBE_ACTIVITY_PATH")
if _legacy_activity:
    _legacy_path = Path(_legacy_activity)
    ACTIVITY_DIR = _legacy_path if _legacy_path.suffix == "" else _legacy_path.parent / "activity"
INGRESS_PATH = "/_schd/ingress"
INGRESS_HEADER = "X-Renglo-Ingress-Secret"

_lock = threading.Lock()
_rules: dict[str, dict[str, Any]] = {}
_event_q: Queue[dict[str, Any]] = Queue()


def _load_env_config() -> dict[str, Any]:
    path = Path(
        os.environ.get("RENGLO_CONFIG_PATH")
        or os.environ.get("ENV_CONFIG_PATH")
        or _DEFAULT_ENV_CONFIG
    )
    if not path.is_file():
        return {}
    try:
        spec = importlib.util.spec_from_file_location("renglo_env_config_ebe", path)
        if not spec or not spec.loader:
            return {}
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        keys = ("RENGLO_INGRESS_SECRET", "WL_NAME", "AWS_REGION")
        out: dict[str, Any] = {"_path": str(path)}
        for key in keys:
            if hasattr(mod, key):
                out[key] = getattr(mod, key)
        return out
    except Exception as exc:
        print(f"Warning: could not load env_config from {path}: {exc}")
        return {}


_CFG = _load_env_config()


def _cfg(key: str, default: str = "") -> str:
    env_val = os.environ.get(key)
    if env_val is not None and str(env_val).strip() != "":
        return str(env_val)
    cfg_val = _CFG.get(key)
    if cfg_val is not None and str(cfg_val).strip() != "":
        return str(cfg_val)
    return default


LOCAL_API_BASE = os.environ.get("LOCAL_API_BASE", "http://127.0.0.1:5001").rstrip("/")
HOST = os.environ.get("EBE_HOST", "127.0.0.1")
PORT = int(os.environ.get("EBE_PORT", "5056"))
INGRESS_SECRET = _cfg("RENGLO_INGRESS_SECRET")
INGRESS_TIMEOUT_SECONDS = int(os.environ.get("EBE_INGRESS_TIMEOUT", "120"))
MACHINE_ID = schd_machine_id()
_activity = ActivityStore(ACTIVITY_DIR)


def _load_rules() -> None:
    if not RULES_PATH.is_file():
        return
    try:
        data = json.loads(RULES_PATH.read_text())
        if isinstance(data, dict):
            _rules.update(data)
            print(f"Loaded {len(_rules)} rule(s) from {RULES_PATH}")
    except Exception as exc:
        print(f"Warning: could not load {RULES_PATH}: {exc}")


def _save_rules() -> None:
    RULES_PATH.write_text(json.dumps(_rules, indent=2) + "\n")


def _post_ingress(payload: dict[str, Any]) -> None:
    url = f"{LOCAL_API_BASE}{INGRESS_PATH}"
    headers = {"Content-Type": "application/json"}
    if INGRESS_SECRET:
        headers[INGRESS_HEADER] = INGRESS_SECRET
    body = {"detail": payload}
    try:
        resp = requests.post(url, json=body, headers=headers, timeout=INGRESS_TIMEOUT_SECONDS)
        print(f"ingress {payload.get('type')} {payload.get('heartbeat_id') or payload.get('schd_jobs_id')} → {resp.status_code}")
        if resp.status_code >= 400:
            print(f"  body: {resp.text[:500]}")
    except Exception as exc:
        print(f"ingress failed: {exc}")


def _event_worker() -> None:
    while True:
        detail = _event_q.get()
        try:
            _post_ingress(detail)
        finally:
            _event_q.task_done()


def _seconds_until_next_minute() -> float:
    now = time.time()
    return max(0.05, 60.0 - (now % 60.0))


def _fire_due_rules() -> None:
    now = datetime.now(timezone.utc).replace(second=0, microsecond=0)
    with _lock:
        snapshot = [(name, dict(rule)) for name, rule in _rules.items()]
    fired = 0
    for name, rule in snapshot:
        if not rule.get("enabled", True):
            continue
        if str(rule.get("kind") or "schedule") == "pattern":
            continue
        if str(rule.get("machine_id") or MACHINE_ID) != MACHINE_ID:
            continue
        expression = str(rule.get("schedule_expression") or "")
        if not expression:
            continue
        try:
            due = expression_is_due(expression, now)
        except Exception as exc:
            print(f"rule {name} matcher error: {exc}")
            continue
        if not due:
            continue
        payload = rule.get("payload") or {}
        if not isinstance(payload, dict):
            payload = {}
        payload = dict(payload)
        payload.setdefault("schedule_origin", "local")
        payload.setdefault("schd_machine_id", MACHINE_ID)
        print(f"tick {now.isoformat()} fire {name} ({expression})")
        _post_ingress(payload)
        fired += 1
    if fired:
        print(f"tick {now.isoformat()} fired {fired} rule(s)")


def _ticker() -> None:
    while True:
        time.sleep(_seconds_until_next_minute())
        try:
            _fire_due_rules()
        except Exception as exc:
            print(f"ticker error: {exc}")


@app.get("/health")
def health():
    with _lock:
        count = len(_rules)
    return jsonify({"ok": True, "rules": count, "schd_machine_id": MACHINE_ID})


@app.get("/rules")
def list_rules():
    with _lock:
        return jsonify({"success": True, "rules": dict(_rules)})


@app.put("/rules")
@app.put("/rules/<name>")
def put_rule(name: str | None = None):
    data = request.get_json(silent=True) or {}
    rule_name = str(name or data.get("name") or "").strip()
    if not rule_name:
        return jsonify({"success": False, "output": "name required"}), 400
    kind = str(data.get("kind") or "schedule")
    enabled = data.get("enabled", True)
    if isinstance(enabled, str):
        enabled = enabled.strip().lower() in {"1", "true", "yes", "enabled"}
    rule = {
        "name": rule_name,
        "kind": kind,
        "schedule_expression": str(data.get("schedule_expression") or ""),
        "payload": data.get("payload") if isinstance(data.get("payload"), dict) else {},
        "event_source": str(data.get("event_source") or ""),
        "machine_id": str(data.get("machine_id") or MACHINE_ID),
        "enabled": bool(enabled),
    }
    with _lock:
        _rules[rule_name] = rule
        _save_rules()
    return jsonify({"success": True, "rule": rule})


@app.patch("/rules/<name>")
def patch_rule(name: str):
    data = request.get_json(silent=True) or {}
    with _lock:
        rule = _rules.get(name)
        if not rule:
            return jsonify({"success": False, "output": "not found"}), 404
        if "enabled" in data:
            enabled = data.get("enabled")
            if isinstance(enabled, str):
                enabled = enabled.strip().lower() in {"1", "true", "yes", "enabled"}
            rule["enabled"] = bool(enabled)
        if "schedule_expression" in data:
            rule["schedule_expression"] = str(data.get("schedule_expression") or "")
        if "payload" in data and isinstance(data.get("payload"), dict):
            rule["payload"] = data["payload"]
        _save_rules()
        out = dict(rule)
    return jsonify({"success": True, "rule": out})


@app.delete("/rules/<name>")
def delete_rule(name: str):
    with _lock:
        existed = name in _rules
        _rules.pop(name, None)
        _save_rules()
    return jsonify({"success": True, "deleted": existed, "rule_name": name})


@app.post("/events")
def put_events():
    data = request.get_json(silent=True)
    if isinstance(data, list):
        entries = data
    elif isinstance(data, dict):
        entries = data.get("entries") or []
    else:
        entries = []
    queued = 0
    for detail in entries:
        if not isinstance(detail, dict):
            continue
        item = dict(detail)
        item.setdefault("schedule_origin", "local")
        item.setdefault("schd_machine_id", MACHINE_ID)
        if str(item.get("schd_machine_id") or MACHINE_ID) != MACHINE_ID:
            continue
        _event_q.put(item)
        queued += 1
    return jsonify({"success": True, "queued": queued, "FailedEntryCount": 0}), 202


@app.post("/activity")
def post_activity():
    data = request.get_json(silent=True) or {}
    if not isinstance(data, dict) or not data:
        return jsonify({"success": False, "output": "entry required"}), 400
    entry = dict(data)
    entry.setdefault("schedule_origin", "local")
    entry.setdefault("schd_machine_id", MACHINE_ID)
    if str(entry.get("schd_machine_id") or MACHINE_ID) != MACHINE_ID:
        return jsonify({"success": False, "output": "machine mismatch"}), 403
    with _lock:
        stored = _activity.append(entry)
    return jsonify({"success": True, "entry": stored})


@app.get("/activity")
def list_activity():
    with _lock:
        items = _activity.list_recent(
            days=request.args.get("days", 7),
            limit=request.args.get("limit", 100),
            event_type=request.args.get("event_type", ""),
            schd_jobs_id=request.args.get("schd_jobs_id", ""),
            portfolio=request.args.get("portfolio", ""),
            org=request.args.get("org", ""),
            schd_machine_id=request.args.get("schd_machine_id", "") or MACHINE_ID,
        )
    return jsonify({"success": True, "items": items, "count": len(items)})


@app.get("/activity/<event_id>")
def get_activity(event_id: str):
    with _lock:
        entry = _activity.get(event_id)
    if not entry:
        return jsonify({"success": False, "output": "not found"}), 404
    return jsonify({"success": True, "entry": entry})


def main() -> None:
    _load_rules()
    threading.Thread(target=_event_worker, name="ebe-events", daemon=True).start()
    threading.Thread(target=_ticker, name="ebe-ticker", daemon=True).start()
    cfg_path = _CFG.get("_path") or "(none)"
    print("")
    print("=" * 60)
    print(f" EventBridge emulator (ebe) → http://{HOST}:{PORT}")
    print("=" * 60)
    print(f" Ingress: {LOCAL_API_BASE}{INGRESS_PATH}")
    print(f" Config:  {cfg_path}")
    print(f" Secret:  {'set' if INGRESS_SECRET else 'empty — set RENGLO_INGRESS_SECRET'}")
    print(f" Machine: {MACHINE_ID}")
    print(f" Rules:   {RULES_PATH} ({len(_rules)} loaded)")
    print(f" Activity:{ACTIVITY_DIR}")
    print(" Ticker:  UTC minute boundary (wall-clock rate()/cron())")
    print("=" * 60)
    print("")
    app.run(host=HOST, port=PORT, threaded=True)


if __name__ == "__main__":
    main()
