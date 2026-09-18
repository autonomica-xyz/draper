#!/bin/bash
# Draper Marketing Pipeline - Startup Script

cd "$(dirname "$0")"
if [ -f .venv/bin/activate ]; then
    source .venv/bin/activate
fi

PYTHON_BIN="${PYTHON:-python}"
if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
    if command -v python3 >/dev/null 2>&1; then
        PYTHON_BIN="python3"
    else
        echo "Python is required. Install Python 3.10+ or set PYTHON=/path/to/python."
        exit 1
    fi
fi

command="${1:-dashboard}"
if [ $# -gt 0 ]; then
    shift
fi

case "$command" in
    dashboard)
        echo "🚀 Starting dashboard"
        "$PYTHON_BIN" dashboard/unified_dashboard.py --run-server --port 8765 "$@"
        ;;
    generate)
        echo "🤖 Generating content batch..."
        "$PYTHON_BIN" pipeline.py --generate --batch-size "${1:-5}"
        ;;
    status)
        echo "📊 Pipeline status:"
        "$PYTHON_BIN" pipeline.py --status
        ;;
    # Scheduling moved to services/job_runner.py (scheduler/content_scheduler.py
    # removed in plan 01-03); no \`scheduler\` command here.
    *)
        echo "Usage: ./run.sh [dashboard|generate|status]"
        echo ""
        echo "  dashboard  - Start web dashboard (default)"
        echo "  generate N - Generate N posts (default: 5)"
        echo "  status     - Show pipeline status"
        ;;
esac
