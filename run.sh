#!/bin/bash
# Local EventBridge emulator (ebe) runner.
#
# Usage:
#   source run.sh              # activate venv in this shell, then start ebe
#   ./run.sh                   # start ebe in a subshell
#
# Loads RENGLO_INGRESS_SECRET from ../renglo-api/env_config.py
# (override with RENGLO_CONFIG_PATH).

_EBE_SOURCED=0
if [ -n "${ZSH_VERSION:-}" ]; then
  case ${ZSH_EVAL_CONTEXT:-} in *:file*) _EBE_SOURCED=1 ;; esac
elif [ -n "${BASH_VERSION:-}" ]; then
  (return 0 2>/dev/null) && _EBE_SOURCED=1
fi

_EBE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
cd "$_EBE_DIR" || return 1 2>/dev/null || exit 1

if [ ! -d "ebe-venv" ]; then
  echo "ebe-venv not found — running setup_venv.sh..."
  ./setup_venv.sh || return 1 2>/dev/null || exit 1
fi

# shellcheck disable=SC1091
source "$_EBE_DIR/ebe-venv/bin/activate"

ENV_CONFIG="${RENGLO_CONFIG_PATH:-$_EBE_DIR/../renglo-api/env_config.py}"
if [ ! -f "$ENV_CONFIG" ]; then
  echo "Warning: env_config not found at $ENV_CONFIG"
  echo "  Set RENGLO_CONFIG_PATH or copy env_config.py into dev/renglo-api/"
else
  eval "$(
    ENV_CONFIG_PATH="$ENV_CONFIG" "$_EBE_DIR/ebe-venv/bin/python" - <<'PY'
import os
import importlib.util
from pathlib import Path

path = Path(os.environ["ENV_CONFIG_PATH"])
spec = importlib.util.spec_from_file_location("env_config_run", path)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

def q(s: str) -> str:
    return "'" + str(s).replace("'", "'\"'\"'") + "'"

mapping = [
    ("RENGLO_INGRESS_SECRET", "RENGLO_INGRESS_SECRET"),
    ("WL_NAME", "WL_NAME"),
    ("AWS_REGION", "AWS_REGION"),
]
seen = set()
for src, dest in mapping:
    if dest in seen:
        continue
    val = getattr(mod, src, None)
    if val is None or str(val).strip() == "":
        continue
    if os.environ.get(dest):
        continue
    print(f"export {dest}={q(val)}")
    seen.add(dest)

print(f"export RENGLO_CONFIG_PATH={q(path)}")
print(f'echo "Loaded config from {path}"')
secret = getattr(mod, "RENGLO_INGRESS_SECRET", "")
if secret:
    print('echo "  RENGLO_INGRESS_SECRET: set"')
else:
    print('echo "  RENGLO_INGRESS_SECRET: empty — set it in env_config.py"')
PY
  )"
fi

export LOCAL_API_BASE="${LOCAL_API_BASE:-http://127.0.0.1:5001}"
export EBE_HOST="${EBE_HOST:-127.0.0.1}"
export EBE_PORT="${EBE_PORT:-5056}"

echo ""
echo "============================================================"
echo " EventBridge emulator (ebe) → http://${EBE_HOST}:${EBE_PORT}"
echo "============================================================"
echo ""
echo " Requires local API on ${LOCAL_API_BASE}"
echo " Requires Schedule UI → Local, and EVENTBRIDGE_EMULATOR_URL in env_config.py"
echo ""

python "$_EBE_DIR/dev_ebe.py"
_status=$?

if [ "$_EBE_SOURCED" = "1" ]; then
  return $_status
fi
exit $_status
