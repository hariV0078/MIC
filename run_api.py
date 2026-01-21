"""Run FastAPI server."""
import uvicorn
import signal
import sys
from dotenv import load_dotenv
from event_validator.utils.logging_config import setup_logging
from event_validator.utils.downloader import stop_periodic_cleanup

# Load environment variables from .env file
load_dotenv()

def signal_handler(sig, frame):
    """Handle shutdown signals gracefully."""
    print("\nShutting down server...")
    # Stop cleanup thread on shutdown
    stop_periodic_cleanup()
    sys.exit(0)

if __name__ == "__main__":
    # Register signal handlers for graceful shutdown
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    setup_logging()
    
    try:
        uvicorn.run(
            "event_validator.api.app:app",
            host="0.0.0.0",
            port=8000,
            reload=True,  # Enable auto-reload for development
            log_level="info"
        )
    except KeyboardInterrupt:
        print("\nServer stopped by user")
        sys.exit(0)
    except Exception as e:
        print(f"Server error: {e}")
        sys.exit(1)

