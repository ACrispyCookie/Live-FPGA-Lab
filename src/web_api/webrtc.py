"""Gate and proxy WebRTC SDP to a loopback-only go2rtc media service."""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

log = logging.getLogger(__name__)
UPSTREAM = "http://127.0.0.1:1984/api/webrtc?src=fpga"


class Offer(BaseModel):
    sdp: str
    type: str


def create_webrtc_router(service, client: httpx.AsyncClient | None = None) -> APIRouter:
    owned_client = client is None
    client = client or httpx.AsyncClient(timeout=20)

    @asynccontextmanager
    async def lifespan(_app):
        try:
            yield
        finally:
            if owned_client:
                await client.aclose()

    router = APIRouter(lifespan=lifespan)

    @router.post('/video/webrtc/offer', include_in_schema=False)
    async def offer(payload: Offer) -> dict[str, str]:
        if not service.gate.enabled():
            raise HTTPException(404, "Video endpoint is disabled")
        if payload.type != 'offer' or not payload.sdp or len(payload.sdp) > 100_000:
            raise HTTPException(400, 'Expected a WebRTC offer')
        try:
            response = await client.post(UPSTREAM, json=payload.model_dump())
            response.raise_for_status()
            answer = response.json()
            if answer.get('type') != 'answer' or not answer.get('sdp'):
                raise ValueError('Invalid answer from media server')
            return {'type': 'answer', 'sdp': answer['sdp']}
        except (httpx.HTTPError, ValueError, KeyError) as exc:
            log.warning('WebRTC media server unavailable: %s', exc)
            raise HTTPException(503, 'WebRTC media server unavailable') from exc

    return router
