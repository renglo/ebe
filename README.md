# EventBridge emulator (ebe)

A **parallel local scheduler** so you can run jobs on your laptop without replacing cloud EventBridge.

**IMPORTANT:** This is not production. Cloud EventBridge keeps firing production jobs at the cloud API. ebe only runs jobs created in the Schedule UI **Local** mode on **this machine**.

Unlike [`dev/wss`](../wss/README.md) / [`dev/webhook`](../webhook/README.md), ebe does not replace a cloud hop. Both clocks stay on; artifacts are stamped `schedule_origin=local` plus an automatic machine id (`~/.renglo/schd_machine_id`). There is no promote — duplicate a job in Cloud if you want it in EventBridge.

## Why

```
Cloud:
  EventBridge cron/rate → API Destination → cloud API /_schd/ingress
  (origin=cloud jobs only)

Local (this tool):
  Schedule UI Local → API stamps origin=local + machine id
                   → PUT /rules, POST /events → this service (:5056)
                   → UTC minute tick / sequential queue
                   → POST http://127.0.0.1:5001/_schd/ingress
                   (this machine's local jobs only)
  Activity stays in tmp/activity/YYYY-MM-DD.jsonl — not production Dynamo/S3.
```

Another developer in the same org with their own ebe will not run your local jobs.

## Crontab

There is no OS crontab. The process stays up and wakes on each **UTC minute** boundary, then fires every ENABLED scheduled rule whose `rate()` / `cron()` expression is due.

`rate()` matching is **wall-clock UTC** (e.g. `rate(5 minutes)` at `:00`, `:05`, `:10`). AWS EventBridge `rate()` is relative to when the rule was created — that difference is intentional for local DX.

`cron(...)` uses EventBridge’s 6-field form (the same strings the Schedule UI builder emits). `L` / `W` / `#` are not supported.

Pattern rules (`create_event_pattern_target`) are stored as no-ops. Fan-out is `POST /events`; the emulator POSTs each job to ingress **one after another**.

## Prerequisites

- Local Renglo API on port **5001** with `/_schd/ingress`
- `EVENTBRIDGE_EMULATOR_URL = 'http://127.0.0.1:5056'` in `dev/renglo-api/env_config.py`
- `RENGLO_INGRESS_SECRET` set (same value the API uses)
- Schedule UI switched to **Local**

## Setup (once)

```bash
cd dev/ebe
./setup_venv.sh
```

## Running

**Terminal A — local API**

```bash
cd dev/renglo-api
./run.sh
```

**Terminal B — ebe**

```bash
cd dev/ebe
source run.sh
```

That activates `ebe-venv`, loads `RENGLO_INGRESS_SECRET` from `../renglo-api/env_config.py`, and starts on `http://127.0.0.1:5056`.

Then Seed / subscribe a heartbeat in the Schedule UI. At the next UTC minute, ebe POSTs `type=heartbeat` to ingress.

## HTTP (internal)

| Method | Path | Purpose |
| ------ | ---- | ------- |
| `PUT` | `/rules` | Register a scheduled rule `{name, schedule_expression, payload}` |
| `DELETE` | `/rules/<name>` | Remove a rule |
| `GET` | `/rules` | Debug listing |
| `POST` | `/events` | Fan-out `{entries: [detail, …]}` — 202, sequential ingress |
| `POST` | `/activity` | Append a local activity row (API only; never S3) |
| `GET` | `/activity` | List compact rows from `tmp/activity/YYYY-MM-DD.jsonl` |
| `GET` | `/activity/<id>` | Full row including handler detail |
| `GET` | `/health` | Liveness |

Rules persist in `rules.json` (gitignored). Local run history is one JSONL file per UTC day under `tmp/activity/` (gitignored). A new file starts at midnight — no restart and no row cap. If the rules file is empty, opening Schedule / Seed re-syncs from Dynamo.

If ebe is down, rule sync fails the same way local WSS fails when `:8080` is down. Local activity is not written anywhere else — it does not fall back to S3.

## Env

| Variable | Default | Purpose |
| -------- | ------- | ------- |
| `LOCAL_API_BASE` | `http://127.0.0.1:5001` | Local Renglo API |
| `EBE_HOST` | `127.0.0.1` | Bind host |
| `EBE_PORT` | `5056` | Bind port (API `5001`, webhook `5055`, WSS `8080`) |
| `RENGLO_INGRESS_SECRET` | from env_config | Ingress header |
| `EBE_INGRESS_TIMEOUT` | `120` | Seconds to wait for each ingress POST |
| `EBE_RULES_PATH` | `./rules.json` | Rule persistence |
| `EBE_ACTIVITY_DIR` | `./tmp/activity` | Daily local activity logs (`YYYY-MM-DD.jsonl`, not S3) |
