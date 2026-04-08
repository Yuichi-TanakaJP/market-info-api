from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter(tags=["health"])


class HealthResponse(BaseModel):
    status: str


@router.get(
    "/health",
    response_model=HealthResponse,
    summary="ヘルスチェック",
)
async def health() -> HealthResponse:
    """API プロセスが起動しているかを確認する。R2 の疎通は検証しない。"""
    return HealthResponse(status="ok")
