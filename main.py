import sys
from pathlib import Path

# Add backend to sys.path so 'app' can be imported correctly
# This ensures that 'import app' works as expected in backend/app/main.py
backend_path = Path(__file__).parent / "backend"
sys.path.insert(0, str(backend_path))

import uvicorn
from app.main import app

if __name__ == "__main__":
    # We use the port 8000 as default for the service
    uvicorn.run(app, host="0.0.0.0", port=8000)
