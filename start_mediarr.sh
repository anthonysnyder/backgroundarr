#!/bin/bash
# Mediarr Launcher Script for macOS
# This script starts Mediarr and opens it in the default browser

# Get the directory where this script is located
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$SCRIPT_DIR"

# Check if Python 3 is installed
if ! command -v python3 &> /dev/null; then
    osascript -e 'display notification "Python 3 is required but not installed" with title "Mediarr Error"'
    exit 1
fi

# Check if required packages are installed
if ! python3 -c "import flask" 2>/dev/null; then
    echo "Installing required Python packages..."
    python3 -m pip install --user -r requirements.txt
fi

# Export environment variables for configuration
# Check if .env file exists and load it
if [ -f "$SCRIPT_DIR/.env" ]; then
    echo "Loading environment variables from .env file..."
    export $(cat "$SCRIPT_DIR/.env" | grep -v '^#' | xargs)
else
    echo "Warning: No .env file found. TMDb API key may not be set."
    echo "Create a .env file with: TMDB_API_KEY=your_key_here"
fi

# Start Flask app in the background
echo "Starting Mediarr..."
python3 -u app.py > /tmp/mediarr.log 2>&1 &
FLASK_PID=$!

# Save PID for later shutdown
echo $FLASK_PID > /tmp/mediarr.pid

# Wait for Flask to start
sleep 2

# Open in default browser
open "http://localhost:6789"

# Show notification
osascript -e 'display notification "Mediarr is running on port 6789" with title "Mediarr Started"'

echo "Mediarr is running (PID: $FLASK_PID)"
echo "Access it at: http://localhost:6789"
echo "Logs: tail -f /tmp/mediarr.log"
echo "To stop: kill $FLASK_PID"
