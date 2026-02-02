"""Run the FastAPI server for event validation."""
import uvicorn
from event_validator.api.app import app

if __name__ == '__main__':
    # Run on all interfaces, port 8000
    # For Ubuntu deployment, use: uvicorn event_validator.api.app:app --host 0.0.0.0 --port 8000
    uvicorn.run(app, host="0.0.0.0", port=8000)
