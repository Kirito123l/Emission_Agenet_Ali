#!/bin/bash

set -e

echo "=========================================="
echo "🚀 Emission Agent Deployment Script"
echo "=========================================="

# Navigate to project directory
cd /opt/emission_agent

# Pull latest code
echo "📥 Pulling latest code from GitHub..."
git fetch origin
git reset --hard origin/main

# Activate virtual environment
echo "🐍 Activating virtual environment..."
source venv/bin/activate

# Install/update dependencies
echo "📦 Installing dependencies..."
pip install -r requirements.txt --upgrade

# Create necessary directories if not exist
echo "📁 Ensuring runtime directories exist..."
mkdir -p data/sessions data/collection data/logs logs outputs
chmod 755 data/sessions data/collection data/logs logs outputs

# Restart service
echo "🔄 Restarting service..."
sudo systemctl restart emission-agent

# Wait for service to start
sleep 3

# Check service status
echo "🔍 Checking service status..."
if sudo systemctl is-active --quiet emission-agent; then
    echo "✅ Service is running"
    sudo systemctl status emission-agent --no-pager
else
    echo "❌ Service failed to start"
    sudo systemctl status emission-agent --no-pager
    exit 1
fi

echo "=========================================="
echo "✅ Deployment completed successfully!"
echo "=========================================="
