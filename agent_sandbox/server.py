import os

from fastapi import FastAPI
import uvicorn

# Default manager port; set MANAGER_PORT to override it during development.
MANAGER_PORT = int(os.environ.get("MANAGER_PORT", "3013"))


if __name__ == "__main__":
    from agent_sandbox.app import app as xapp
    uvicorn.run(xapp, host="0.0.0.0", port=MANAGER_PORT, log_level="debug")
