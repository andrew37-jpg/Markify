"""Production start: accepts the hosting provider's PORT, no development reload."""
import os
from pathlib import Path
import sys
import uvicorn

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

if __name__ == '__main__':
    port = int(os.getenv('PORT', '8000'))
    if not 1 <= port <= 65535:
        raise SystemExit('PORT must be between 1 and 65535')
    uvicorn.run('app.main:app', host='0.0.0.0', port=port, reload=False, workers=1)
