# Ubuntu Deployment Guide - Event Validator with Ollama

This guide covers deploying the Event Validation System with Ollama on an Ubuntu server.

## Prerequisites

- Ubuntu 20.04+ (or similar Linux distribution)
- Python 3.10+
- At least 8GB RAM (16GB+ recommended)
- GPU optional but recommended for better performance
- Root/sudo access

## Step 1: Install System Dependencies

```bash
# Install Poppler (CRITICAL for PDF OCR)
sudo apt-get update
sudo apt-get install -y poppler-utils libgl1-mesa-glx libglib2.0-0

# Install Ollama
curl -fsSL https://ollama.com/install.sh | sh

# Start and enable Ollama service
sudo systemctl enable ollama
sudo systemctl start ollama

# Verify Ollama is running
curl http://localhost:11434/api/tags
```

## Step 2: Pull Required Models

```bash
# Pull text model (choose based on your system)
ollama pull llama3.2:3b      # Fast, efficient (~2GB RAM)
# OR
ollama pull llama3.1:8b      # Better quality (~5GB RAM)
# OR
ollama pull llama3.1:70b     # Best quality (~40GB RAM, requires GPU)

# Pull vision model
ollama pull llava:latest     # Fast (~4GB RAM)
# OR
ollama pull llava:13b        # Better quality (~8GB RAM)
# OR
ollama pull llava:34b        # Best quality (~20GB RAM, requires GPU)
```

## Step 3: Setup Project

```bash
# Navigate to project directory
cd event_validator_ollama

# Run setup script
chmod +x setup_ubuntu.sh
./setup_ubuntu.sh
```

The setup script will:
- Install system dependencies
- Create Python virtual environment
- Install Python packages
- Create necessary directories

## Step 4: Configure Environment

Create `.env` file:

```bash
cp .env.example .env
nano .env
```

Edit with your configuration:

```bash
# Ollama Configuration
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_TEXT_MODEL=llama3.2:3b
OLLAMA_VISION_MODEL=llava:latest

# Processing Configuration (Optimized for 16-core CPU)
DEFAULT_MAX_WORKERS=4
GEMINI_RPM=15

# Acceptance threshold
ACCEPTANCE_THRESHOLD=60
```

## Step 5: Test Installation

```bash
# Activate virtual environment
source venv/bin/activate

# Test Ollama connection
python -c "import ollama; print(ollama.list())"

# Run a test validation
python -m event_validator.main test_data_10.csv
```

## Step 6: Run API Server

### Development Mode

```bash
source venv/bin/activate
python run_api.py
```

### Production Mode with systemd

Create `/etc/systemd/system/event-validator.service`:

```ini
[Unit]
Description=Event Validator API with Ollama
After=network.target ollama.service
Requires=ollama.service

[Service]
Type=simple
User=your-user
WorkingDirectory=/path/to/event_validator_ollama
Environment="PATH=/path/to/event_validator_ollama/venv/bin"
Environment="OLLAMA_BASE_URL=http://localhost:11434"
Environment="OLLAMA_TEXT_MODEL=llama3.2:3b"
Environment="OLLAMA_VISION_MODEL=llava:latest"
ExecStart=/path/to/event_validator_ollama/venv/bin/uvicorn event_validator.api.app:app --host 0.0.0.0 --port 8000
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

Enable and start:

```bash
sudo systemctl daemon-reload
sudo systemctl enable event-validator
sudo systemctl start event-validator
sudo systemctl status event-validator
```

## Performance Optimization

### Increase Ollama Workers

Edit `/etc/systemd/system/ollama.service`:

```ini
[Service]
Environment="OLLAMA_NUM_PARALLEL=4"
Environment="OLLAMA_MAX_LOADED_MODELS=2"
```

Restart:

```bash
sudo systemctl daemon-reload
sudo systemctl restart ollama
```

### GPU Acceleration

If you have an NVIDIA GPU:

```bash
# Install NVIDIA drivers and CUDA
sudo apt-get install nvidia-driver-535 nvidia-cuda-toolkit

# Ollama will automatically use GPU if available
# Verify GPU usage
nvidia-smi
```

## Monitoring

### Check Ollama Status

```bash
# Service status
sudo systemctl status ollama

# Check logs
journalctl -u ollama -f

# Test API
curl http://localhost:11434/api/tags
```

### Check Application Status

```bash
# Service status
sudo systemctl status event-validator

# Check logs
journalctl -u event-validator -f

# Health check
curl http://localhost:8000/health
```

## Troubleshooting

### Ollama not starting

```bash
# Check if port 11434 is in use
sudo netstat -tulpn | grep 11434

# Check Ollama logs
journalctl -u ollama -n 50

# Restart Ollama
sudo systemctl restart ollama
```

### Out of Memory

- Use smaller models (`llama3.2:3b` instead of `llama3.1:70b`)
- Reduce `DEFAULT_MAX_WORKERS` in `.env`
- Add swap space:
  ```bash
  sudo fallocate -l 8G /swapfile
  sudo chmod 600 /swapfile
  sudo mkswap /swapfile
  sudo swapon /swapfile
  ```

### Models not loading

```bash
# List available models
ollama list

# Pull missing models
ollama pull llama3.2:3b
ollama pull llava:latest

# Remove and re-pull if corrupted
ollama rm llama3.2:3b
ollama pull llama3.2:3b
```

## Security Considerations

1. **Firewall**: Only expose port 8000 if needed
   ```bash
   sudo ufw allow 8000/tcp
   ```

2. **Reverse Proxy**: Use Nginx for HTTPS
   ```nginx
   server {
       listen 443 ssl;
       server_name your-domain.com;
       
       ssl_certificate /path/to/cert.pem;
       ssl_certificate_key /path/to/key.pem;
       
       location / {
           proxy_pass http://127.0.0.1:8000;
           proxy_set_header Host $host;
           proxy_set_header X-Real-IP $remote_addr;
       }
   }
   ```

3. **User Permissions**: Run service as non-root user

## Backup and Maintenance

### Backup Models

```bash
# Models are stored in ~/.ollama/models
# Backup this directory
tar -czf ollama-models-backup.tar.gz ~/.ollama/models
```

### Update Models

```bash
# Update a model
ollama pull llama3.2:3b

# Remove old version
ollama rm llama3.2:3b
```

## Support

For issues:
1. Check Ollama logs: `journalctl -u ollama -f`
2. Check application logs: `journalctl -u event-validator -f`
3. Verify models are available: `ollama list`
4. Test Ollama API: `curl http://localhost:11434/api/tags`
