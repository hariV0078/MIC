#!/bin/bash
# Setup script for Ubuntu deployment of Event Validator with Ollama

set -e

echo "=========================================="
echo "Event Validator - Ollama Setup for Ubuntu"
echo "=========================================="

# Update system packages
echo "Updating system packages..."
sudo apt-get update
sudo apt-get upgrade -y

# Install Python 3.10+ and pip
echo "Installing Python and pip..."
sudo apt-get install -y python3 python3-pip python3-venv

# Install system dependencies for PDF/image processing
echo "Installing system dependencies..."
sudo apt-get install -y \
    libpoppler-cpp-dev \
    poppler-utils \
    tesseract-ocr \
    libtesseract-dev \
    libmagic1 \
    libjpeg-dev \
    zlib1g-dev \
    libpng-dev

# Install Ollama
echo "Installing Ollama..."
curl -fsSL https://ollama.com/install.sh | sh

# Start Ollama service
echo "Starting Ollama service..."
sudo systemctl enable ollama
sudo systemctl start ollama

# Wait for Ollama to be ready
echo "Waiting for Ollama to start..."
sleep 5

# Pull required models
echo "Pulling Ollama models (this may take a while)..."
ollama pull llama3.2:3b
ollama pull llava:latest

# Create virtual environment
echo "Creating Python virtual environment..."
python3 -m venv venv
source venv/bin/activate

# Upgrade pip
pip install --upgrade pip

# Install Python dependencies
echo "Installing Python dependencies..."
pip install -r requirements.txt

# Create necessary directories
echo "Creating necessary directories..."
mkdir -p outputs
mkdir -p downloaded_files

# Set permissions
chmod +x run_api.py

echo ""
echo "=========================================="
echo "Setup complete!"
echo "=========================================="
echo ""
echo "To start the API server:"
echo "  source venv/bin/activate"
echo "  python run_api.py"
echo ""
echo "Or use uvicorn directly:"
echo "  uvicorn event_validator.api.app:app --host 0.0.0.0 --port 8000"
echo ""
echo "To process CSV files:"
echo "  python -m event_validator.main input.csv"
echo ""
echo "Environment variables (optional, in .env file):"
echo "  OLLAMA_BASE_URL=http://localhost:11434"
echo "  OLLAMA_TEXT_MODEL=llama3.2:3b"
echo "  OLLAMA_VISION_MODEL=llava:latest"
echo ""
