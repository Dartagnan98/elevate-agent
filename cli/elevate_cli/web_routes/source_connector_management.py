"""Source connector management routes."""

import logging
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from elevate_cli.web_routes.source_connector_actions import run_source_connector_action


class SourceConnectorAction(BaseModel):
    action: str
    sourceId: str


def register_source_connector_management_routes(router: APIRouter, *, log: logging.Logger) -> None:
    @router.get("/api/source-connectors")
    async def get_source_connectors(include_prompts: bool = False):
        try:
            from elevate_cli.source_connectors import build_source_connectors_response

            return build_source_connectors_response(include_prompts=include_prompts)
        except Exception as exc:
            log.exception("GET /api/source-connectors failed")
            raise HTTPException(status_code=500, detail=f"Source connectors failed: {exc}")

    @router.post("/api/source-connectors")
    async def update_source_connector(body: SourceConnectorAction):
        if body.action not in {"scaffold", "refresh", "run-prompt"}:
            raise HTTPException(status_code=400, detail="Unsupported source connector action")
        try:
            from elevate_cli.source_connectors import build_source_connectors_response

            action_result = run_source_connector_action(body.action, body.sourceId, log=log)

            payload: dict[str, Any] = {
                "ok": True,
                **build_source_connectors_response(include_prompts=False),
            }
            payload.update(action_result)
            return payload
        except Exception as exc:
            log.exception("POST /api/source-connectors failed")
            raise HTTPException(status_code=500, detail=f"Source connector update failed: {exc}")

    @router.get("/api/source-connectors/{source_id}/prompt")
    async def get_source_connector_prompt(source_id: str):
        try:
            from elevate_cli.source_connectors import source_prompt_for

            prompt = source_prompt_for(source_id)
            if not prompt:
                raise ValueError(f"Unknown source connector: {source_id}")
            return {"sourceId": source_id, "prompt": prompt}
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc))
        except Exception as exc:
            log.exception("GET /api/source-connectors/%s/prompt failed", source_id)
            raise HTTPException(status_code=500, detail=f"Source prompt failed: {exc}")

    @router.get("/api/source-connectors/{source_id}/records")
    async def get_source_connector_records(source_id: str, limit: int = 12):
        try:
            from elevate_cli.source_connectors import build_source_records_response

            return build_source_records_response(source_id, limit=limit)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc))
        except Exception as exc:
            log.exception("GET /api/source-connectors/%s/records failed", source_id)
            raise HTTPException(status_code=500, detail=f"Source records failed: {exc}")
