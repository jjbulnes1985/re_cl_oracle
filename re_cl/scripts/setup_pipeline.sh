#!/usr/bin/env bash
# setup_pipeline.sh
# -----------------
# Single-command entry point for the RE_CL platform.
# Ensures Docker is up and the DB is healthy, then runs setup_pipeline.py.
#
# Usage:
#   bash scripts/setup_pipeline.sh               # full setup
#   bash scripts/setup_pipeline.sh --skip-data   # any flag is forwarded to Python
#   bash scripts/setup_pipeline.sh --dry-run
#   bash scripts/setup_pipeline.sh --from-step 5
#
# Requirements:
#   Docker Desktop running, docker-compose.yml in this directory.

set -euo pipefail

# ---------------------------------------------------------------------------
# Resolve paths
# ---------------------------------------------------------------------------
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

echo "============================================================"
echo "  RE_CL — Setup Pipeline"
echo "  REPO_DIR : $REPO_DIR"
echo "============================================================"

# ---------------------------------------------------------------------------
# 1. Check Docker is running
# ---------------------------------------------------------------------------
echo ""
echo "[pre] Checking Docker daemon ..."
if ! docker info > /dev/null 2>&1; then
    echo "ERROR: Docker is not running."
    echo "  Start Docker Desktop, then re-run this script."
    exit 1
fi
echo "      Docker OK"

# ---------------------------------------------------------------------------
# 2. Start docker-compose services (idempotent — safe to re-run)
# ---------------------------------------------------------------------------
echo ""
echo "[pre] Starting docker-compose services ..."
docker-compose -f "$REPO_DIR/docker-compose.yml" up -d

# ---------------------------------------------------------------------------
# 3. Wait for the DB container to become healthy
# ---------------------------------------------------------------------------
echo ""
echo "[pre] Waiting for DB to become healthy ..."

DB_CONTAINER="re_cl_db"
MAX_WAIT=120   # seconds
INTERVAL=3
elapsed=0

while true; do
    status=$(docker inspect --format='{{.State.Health.Status}}' "$DB_CONTAINER" 2>/dev/null || echo "missing")

    if [[ "$status" == "healthy" ]]; then
        echo "      DB is healthy"
        break
    fi

    if [[ "$status" == "missing" ]]; then
        # Container has no health-check — just check it's running
        running=$(docker inspect --format='{{.State.Running}}' "$DB_CONTAINER" 2>/dev/null || echo "false")
        if [[ "$running" == "true" ]]; then
            echo "      DB container is running (no health-check configured)"
            break
        fi
    fi

    if [[ $elapsed -ge $MAX_WAIT ]]; then
        echo "ERROR: DB did not become healthy within ${MAX_WAIT}s."
        echo "  Check: docker logs $DB_CONTAINER"
        exit 1
    fi

    echo "      DB status: $status — waiting ${INTERVAL}s (${elapsed}/${MAX_WAIT}s) ..."
    sleep $INTERVAL
    elapsed=$((elapsed + INTERVAL))
done

# ---------------------------------------------------------------------------
# 4. Hand off to Python
# ---------------------------------------------------------------------------
echo ""
echo "[pre] Handing off to setup_pipeline.py ..."
echo ""

# Activate virtual environment if one is detected
if [[ -f "$REPO_DIR/.venv/bin/activate" ]]; then
    # shellcheck disable=SC1091
    source "$REPO_DIR/.venv/bin/activate"
    echo "      Virtual env activated: $REPO_DIR/.venv"
elif [[ -f "$REPO_DIR/venv/bin/activate" ]]; then
    # shellcheck disable=SC1091
    source "$REPO_DIR/venv/bin/activate"
    echo "      Virtual env activated: $REPO_DIR/venv"
fi

python "$SCRIPT_DIR/setup_pipeline.py" "$@"
