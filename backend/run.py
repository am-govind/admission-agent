"""Dev runner: `python run.py` starts the API with reload."""
from __future__ import annotations

import uvicorn

from app.core.config import settings

if __name__ == "__main__":
    uvicorn.run("app.main:app", host=settings.api_host, port=settings.api_port, reload=True)
