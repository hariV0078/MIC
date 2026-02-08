# Event Validator - Ollama Open Source Version

This is an open-source version of the Event Validation System using Ollama instead of Google Gemini/Groq APIs. It's designed for Ubuntu deployment and runs entirely locally.

## Features

- **Open Source**: Uses Ollama with local LLM models (no API keys required)
- **Equivalent Functionality**: Same validation logic as the Gemini version
- **Efficient**: Optimized for local deployment with caching and rate limiting
- **Standardized Scoring**: Uses a 100-point evaluation model with a 60-point acceptance threshold
- **Ubuntu Ready**: Includes setup scripts and configuration for Ubuntu servers

## Prerequisites

- Ubuntu 20.04+ (or similar Linux distribution)
- Python 3.10+
- GPU recommended (but not required - CPU works too)
- At least 8GB RAM (16GB+ recommended for better performance)

## Quick Start

### 1. Install Ollama

```bash
curl -fsSL https://ollama.com/install.sh | sh
```

### 2. Start Ollama Service

```bash
sudo systemctl start ollama
sudo systemctl enable ollama
```

### 3. Pull Required Models

```bash
# Text model (fast, efficient)
ollama pull llama3.2:3b

# Vision model (for image analysis)
ollama pull llava:latest
```

**Note**: For better quality (but slower), you can use:
- `llama3.1:8b` or `llama3.1:70b` for text
- `llava:13b` or `llava:34b` for vision

### 4. Run Setup Script

```bash
chmod +x setup_ubuntu.sh
./setup_ubuntu.sh
```

This will:
- Install system dependencies
- Create Python virtual environment
- Install Python packages
- Pull required Ollama models

### 5. Activate Virtual Environment

```bash
source venv/bin/activate
```

### 6. Configure (Optional)

Create a `.env` file in the project root:

```bash
# Ollama Configuration
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_TEXT_MODEL=llama3.2:3b
OLLAMA_VISION_MODEL=llava:latest

# For remote Ollama server (if running on different machine)
# OLLAMA_BASE_URL=http://192.168.1.100:11434
```

### 7. Run the API Server

```bash
python run_api.py
```

Or with uvicorn:

```bash
uvicorn event_validator.api.app:app --host 0.0.0.0 --port 8000
```

### 8. Process CSV Files

```bash
python -m event_validator.main input.csv
```

## Model Recommendations

### For CPU-only Systems:
- Text: `llama3.2:3b` (fastest, ~2GB RAM)
- Vision: `llava:latest` (~4GB RAM)

### For Systems with GPU:
- Text: `llama3.1:8b` or `llama3.1:70b` (better quality)
- Vision: `llava:13b` or `llava:34b` (better quality)

### For Maximum Performance:
- Text: `llama3.1:70b` (requires 40GB+ RAM or GPU)
- Vision: `llava:34b` (requires 20GB+ RAM or GPU)

## Performance Tuning

### Increase Ollama Workers

Edit `/etc/systemd/system/ollama.service`:

```ini
[Service]
Environment="OLLAMA_NUM_PARALLEL=4"
Environment="OLLAMA_MAX_LOADED_MODELS=2"
```

Then restart:
```bash
sudo systemctl daemon-reload
sudo systemctl restart ollama
```

### Adjust Rate Limits

Edit `.env` or environment variables:

```bash
# Higher rate for local deployment (no API limits)
DEFAULT_MAX_WORKERS=16
GEMINI_RPM=300  # Higher for local
```

## API Endpoints

Same as the Gemini version:

- `GET /` - API information
- `GET /health` - Health check
- `POST /validate/batch` - Validate batch of submissions
- `GET /download/{filename}` - Download results
- `GET /downloads` - List available files

## Differences from Gemini Version

1. **No API Keys**: Runs entirely locally
2. **Model Management**: Models are managed by Ollama (pull/update via `ollama` CLI)
3. **Performance**: May be slower than Gemini API, but no rate limits
4. **Resource Usage**: Uses local CPU/GPU resources
5. **Cost**: Free (no API costs)

## Troubleshooting

### Ollama not starting

```bash
# Check status
sudo systemctl status ollama

# Check logs
journalctl -u ollama -f

# Restart
sudo systemctl restart ollama
```

### Models not found

```bash
# List available models
ollama list

# Pull missing models
ollama pull llama3.2:3b
ollama pull llava:latest
```

### Connection refused

```bash
# Check if Ollama is running
curl http://localhost:11434/api/tags

# If not, start it
sudo systemctl start ollama
```

### Out of memory

- Use smaller models (`llama3.2:3b` instead of `llama3.1:70b`)
- Reduce `DEFAULT_MAX_WORKERS` in environment
- Add swap space: `sudo fallocate -l 8G /swapfile && sudo chmod 600 /swapfile && sudo mkswap /swapfile && sudo swapon /swapfile`

## Production Deployment

### Using systemd service

Create `/etc/systemd/system/event-validator.service`:

```ini
[Unit]
Description=Event Validator API
After=network.target ollama.service

[Service]
Type=simple
User=your-user
WorkingDirectory=/path/to/event_validator_ollama
Environment="PATH=/path/to/event_validator_ollama/venv/bin"
ExecStart=/path/to/event_validator_ollama/venv/bin/uvicorn event_validator.api.app:app --host 0.0.0.0 --port 8000
Restart=always

[Install]
WantedBy=multi-user.target
```

Enable and start:

```bash
sudo systemctl enable event-validator
sudo systemctl start event-validator
```

### Using Nginx reverse proxy

```nginx
server {
    listen 80;
    server_name your-domain.com;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }
}
```

## License

Same as the main project.
