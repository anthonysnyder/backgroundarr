#!/bin/bash
# Mediarr Stop Script for macOS

if [ -f /tmp/mediarr.pid ]; then
    PID=$(cat /tmp/mediarr.pid)
    if kill -0 $PID 2>/dev/null; then
        echo "Stopping Mediarr (PID: $PID)..."
        kill $PID
        rm /tmp/mediarr.pid
        osascript -e 'display notification "Mediarr has been stopped" with title "Mediarr"'
        echo "Mediarr stopped successfully"
    else
        echo "Mediarr is not running (stale PID file)"
        rm /tmp/mediarr.pid
    fi
else
    echo "Mediarr is not running (no PID file found)"
    # Try to find and kill any running python app.py processes
    pkill -f "python.*app.py" && echo "Killed stray Mediarr process"
fi
