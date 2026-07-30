"""Dev runner: `python run.py` starts the API with reload."""
from __future__ import annotations

import uvicorn

from app.core.config import settings
from app.core.logs import setup_logging

if __name__ == "__main__":
    setup_logging()
    uvicorn.run(
        "app.main:app",
        host=settings.api_host,
        port=settings.api_port,
        reload=True,
        # Ours is already installed; uvicorn's default config would replace the
        # formatter and drop the request id from every line.
        log_config=None,
        access_log=False,  # the request middleware logs this, with the request id
    )
