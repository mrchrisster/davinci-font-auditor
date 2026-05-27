#!/bin/bash
cd "$(dirname "$0")"
echo "============================================="
echo "Starting DaVinci Font Mapper..."
echo "============================================="

# Check for python3
if ! command -v python3 &> /dev/null; then
    echo "ERROR: Python 3 could not be found."
    echo "Please download and install Python from: https://www.python.org/downloads/"
    echo "Make sure to check the option to add Python to your PATH."
    read -p "Press Enter to exit..."
    exit 1
fi

echo "Installing/updating dependencies..."
python3 -m pip install -r requirements.txt

# Start backend server in the background and capture PID
echo "Starting backend server on http://127.0.0.1:5001..."
python3 app.py &
APP_PID=$!

# Wait for server to initialize
sleep 1.5

# Open the dashboard in the default browser
echo "Opening web dashboard..."
if command -v open &> /dev/null; then
    open http://127.0.0.1:5001
else
    echo "Dashboard available at: http://127.0.0.1:5001"
fi

# Keep terminal open and block on the backend process
wait $APP_PID
