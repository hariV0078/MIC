# Event Validator - Ollama Open Source Version

A complete open-source implementation of the Event Validation System using Ollama instead of Google Gemini/Groq APIs. This version is designed for Ubuntu deployment and runs entirely locally with no API keys required.

## 🚀 Quick Start

```bash
# 1. Install Ollama
curl -fsSL https://ollama.com/install.sh | sh

# 2. Pull models
ollama pull llama3.2:3b
ollama pull llava:latest

# 3. Setup project
cd event_validator_ollama
chmod +x setup_ubuntu.sh
./setup_ubuntu.sh

# 4. Run
source venv/bin/activate
python -m event_validator.main input.csv
```

## 📁 Project Structure

```
event_validator_ollama/
├── event_validator/          # Main validation package
│   ├── api/                  # FastAPI server
│   ├── config/               # Validation rules
│   ├── extractors/           # PDF and image extraction
│   ├── orchestration/        # Main processing logic
│   ├── validators/           # Validation logic
│   │   └── ollama_client.py  # Ollama client (replaces Gemini/Groq)
│   └── utils/                # Utilities
├── main.py                   # CLI entry point
├── run_api.py                # API server entry point
├── requirements.txt          # Python dependencies
├── setup_ubuntu.sh           # Ubuntu setup script
├── README_OLLAMA.md          # Detailed documentation
├── DEPLOYMENT.md             # Deployment guide
└── INSTALL.md                # Installation guide
```

## 🔧 Key Differences from Gemini Version

1. **No API Keys**: Runs entirely locally
2. **Ollama Client**: Replaces `GeminiClient` and `GroqClient`
3. **Local Models**: Uses locally installed Ollama models
4. **Same Interface**: All validation logic remains identical
5. **Ubuntu Optimized**: Setup scripts and configuration for Linux

## 📋 Requirements

- Ubuntu 20.04+ (or similar Linux)
- Python 3.10+
- 8GB+ RAM (16GB+ recommended)
- GPU optional but recommended

## 🎯 Features

- ✅ Same validation logic as Gemini version
- ✅ Theme validation (lenient relevancy checking)
- ✅ PDF validation (title, expert, learning outcomes, objectives, participants)
- ✅ Image validation (geotag, banner, real activity, mode, participants)
- ✅ Duplicate detection (ignores same-submission duplicates)
- ✅ Graduated participant scoring (15-20 scale)
- ✅ Event driven 2 auto-pass for event mode
- ✅ Level auto-correction based on duration
- ✅ MIC event auto-acceptance for PDF validation
- ✅ Requirements Not Met formatted by category

## 📖 Documentation

- **README_OLLAMA.md**: Complete feature documentation
- **DEPLOYMENT.md**: Production deployment guide
- **INSTALL.md**: Quick installation guide
- **.env.example**: Configuration template

## 🔌 API Endpoints

Same as Gemini version:
- `GET /` - API information
- `GET /health` - Health check
- `POST /validate/batch` - Validate batch of submissions
- `GET /download/{filename}` - Download results
- `GET /downloads` - List available files

## ⚙️ Configuration

Create `.env` file:

```bash
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_TEXT_MODEL=llama3.2:3b
OLLAMA_VISION_MODEL=llava:latest
DEFAULT_MAX_WORKERS=12
ACCEPTANCE_THRESHOLD=60
```

## 🐛 Troubleshooting

See `DEPLOYMENT.md` for detailed troubleshooting.

Common issues:
- Ollama not running: `sudo systemctl start ollama`
- Models not found: `ollama pull llama3.2:3b`
- Out of memory: Use smaller models or add swap

## 📝 License

Same as the main project.
