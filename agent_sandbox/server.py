from fastapi import FastAPI
import uvicorn


if __name__ == "__main__":
    from agent_sandbox.app import app as xapp
    uvicorn.run(xapp, host="0.0.0.0", port=8000, log_level="debug")
