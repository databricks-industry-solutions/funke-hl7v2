"""FastAPI entry point for the ADT control-room app.

Serves the JSON control API under ``/api`` and the built React single-page app for everything
else. Run locally with ``python app.py`` (reads ``DATABRICKS_APP_PORT``, default 8000); in
Databricks Apps the same command is launched via ``app.yaml``.
"""

import logging
import os

import uvicorn
from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from flow import FlowController
from generator import GeneratorController
from pipelines import PipelineControl

logging.basicConfig(level=logging.INFO)

app = FastAPI(title="ADT Control Room")
controller = GeneratorController()
pipelines = PipelineControl()
flow = FlowController()

_FRONTEND_DIR = os.path.join(os.path.dirname(__file__), "frontend", "dist")


class ConfigUpdate(BaseModel):
    peak_rate_per_hour: float | None = None
    emr_weights: dict[str, float] | None = None


@app.post("/api/start")
def start() -> dict:
    return controller.start()


@app.post("/api/stop")
def stop() -> dict:
    return controller.stop()


@app.get("/api/status")
def status() -> dict:
    return controller.status()


@app.get("/api/census")
def census() -> dict:
    return controller.census()


@app.post("/api/config")
def set_config(update: ConfigUpdate) -> dict:
    return controller.set_config(
        peak_rate_per_hour=update.peak_rate_per_hour,
        emr_weights=update.emr_weights,
    )


@app.get("/api/flow")
def flow_metrics() -> dict:
    return flow.metrics()


@app.get("/api/flow/sample")
def flow_sample() -> dict:
    return flow.sample()


@app.get("/api/pipelines")
def pipelines_status() -> dict:
    return pipelines.status()


@app.post("/api/pipelines/pause")
def pipelines_pause() -> dict:
    return pipelines.pause()


@app.post("/api/pipelines/resume")
def pipelines_resume() -> dict:
    return pipelines.resume()


# --- static frontend (mounted last so /api routes win) ---------------------------------
if os.path.isdir(_FRONTEND_DIR):
    app.mount(
        "/assets",
        StaticFiles(directory=os.path.join(_FRONTEND_DIR, "assets")),
        name="assets",
    )

    @app.get("/{full_path:path}")
    def spa(full_path: str) -> FileResponse:
        """Serve the SPA shell for any non-API path (client-side routing)."""
        return FileResponse(os.path.join(_FRONTEND_DIR, "index.html"))


if __name__ == "__main__":
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=int(os.environ.get("DATABRICKS_APP_PORT", "8000")),
    )
