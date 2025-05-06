#!/bin/bash

echo "🔧 Installing dependencies..."
sudo apt update
sudo apt install -y python3 python3-venv python3-pip

echo "🐍 Setting up virtual environment..."
python3 -m venv venv
source venv/bin/activate

echo "📦 Installing Python packages..."
pip install --upgrade pip
pip install -r requirements.txt

echo "✅ Setup complete. Run with:"
echo "source venv/bin/activate && python3 app.py"
