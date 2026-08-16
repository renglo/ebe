#!/bin/bash
# Setup script for EventBridge emulator virtual environment

cd "$(dirname "$0")"

if [ ! -d "ebe-venv" ]; then
    echo "Creating virtual environment..."
    python3 -m venv ebe-venv
fi

echo "Activating virtual environment..."
# shellcheck disable=SC1091
source ebe-venv/bin/activate

echo "Installing dependencies..."
pip install --upgrade pip
pip install -r requirements.txt

echo "Setup complete! To activate the virtual environment, run:"
echo "  source ebe-venv/bin/activate"
echo ""
echo "Then run the service with:"
echo "  python dev_ebe.py"
echo "or:"
echo "  source run.sh"
