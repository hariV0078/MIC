# Installation Guide - Event Validator with Ollama

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

### 3. Pull Models

```bash
# Text model (choose one based on your system)
ollama pull llama3.2:3b      # Fast, ~2GB RAM
# OR
ollama pull llama3.1:8b      # Better, ~5GB RAM

# Vision model
ollama pull llava:latest      # Fast, ~4GB RAM
```

### 4. Setup Python Environment

```bash
cd event_validator_ollama
chmod +x setup_ubuntu.sh
./setup_ubuntu.sh
```

### 5. Configure

```bash
cp .env.example .env
# Edit .env with your settings
```

### 6. Run

```bash
source venv/bin/activate
python -m event_validator.main input.csv
```

Or start API server:

```bash
python run_api.py
```

## Model Recommendations

| System | Text Model | Vision Model | RAM Required |
|--------|-----------|--------------|--------------|
| CPU, 8GB | llama3.2:3b | llava:latest | ~6GB |
| CPU, 16GB | llama3.1:8b | llava:13b | ~13GB |
| GPU, 16GB+ | llama3.1:8b | llava:13b | ~13GB |
| GPU, 40GB+ | llama3.1:70b | llava:34b | ~60GB |

## Troubleshooting

See `DEPLOYMENT.md` for detailed troubleshooting guide.
