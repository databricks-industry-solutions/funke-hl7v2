"""Runtime pause/resume of the demo's continuous Lakeflow pipelines from the app.

Databricks Apps have no pipeline resource binding, so the app never sees the pipeline IDs. We
resolve them by display name at runtime — the same trick the generator uses for the dashboard
(``generator._resolve_dashboard_url``). Pausing stops the continuous updates so the serverless
pipelines idle down and stop billing; resuming starts a fresh continuous update. State
transitions take minutes, so the UI polls ``status()`` to watch them settle.
"""

import logging

from databricks.sdk import WorkspaceClient
from databricks.sdk.service.pipelines import PipelineState

log = logging.getLogger(__name__)

# UI key -> pipeline display name (as defined in the DAB). Substring-matched so the dev-mode
# "[dev <user>] " prefix still resolves.
_PIPELINES = {
    "ingest": "HL7 Ingestion",
    "gold": "Bed Utilization (Gold)",
}

# States where an update is (about to be) live; pausing stops these.
_ACTIVE = {
    PipelineState.RUNNING,
    PipelineState.STARTING,
    PipelineState.DEPLOYING,
    PipelineState.RESETTING,
    PipelineState.RECOVERING,
}
# States from which a resume should kick off a new update.
_INACTIVE = {PipelineState.IDLE, PipelineState.FAILED}


class PipelineControl:
    """Resolve and pause/resume the demo's continuous pipelines by display name."""

    def __init__(self):
        self._w = WorkspaceClient()

    def _matched(self) -> list[tuple[str, object]]:
        """Return ``(key, PipelineStateInfo)`` for whichever target pipelines currently exist.

        A single ``list_pipelines`` call gives us both the ID (for actions) and the live state
        (for status). Best-effort: any API error yields an empty list so the request path never
        raises.
        """
        try:
            found = list(self._w.pipelines.list_pipelines())
        except Exception:
            log.exception("could not list pipelines")
            return []
        out = []
        for key, name in _PIPELINES.items():
            match = next((pl for pl in found if pl.name and name in pl.name), None)
            if match:
                out.append((key, match))
        return out

    def status(self) -> dict:
        return {
            "pipelines": [
                {
                    "key": key,
                    "name": pl.name,
                    "state": pl.state.value if pl.state else "UNKNOWN",
                }
                for key, pl in self._matched()
            ]
        }

    def pause(self) -> dict:
        for _key, pl in self._matched():
            if pl.state in _ACTIVE:
                try:
                    self._w.pipelines.stop(
                        pl.pipeline_id
                    )  # fire-and-return; UI polls status
                except Exception:
                    log.exception("failed to stop pipeline %s", pl.name)
        return self.status()

    def resume(self) -> dict:
        for _key, pl in self._matched():
            if pl.state in _INACTIVE:
                try:
                    self._w.pipelines.start_update(pl.pipeline_id)
                except Exception:
                    log.exception("failed to start pipeline %s", pl.name)
        return self.status()
