from __future__ import annotations

from fastapi import APIRouter

router = APIRouter(tags=["health"])


@router.get(
    "/health",
    summary="ヘルスチェック",
    responses={200: {"content": {"application/json": {"example": {"status": "ok"}}}}},
)
async def health() -> dict:
    """API プロセスが起動しているかを確認する。R2 の疎通は検証しない。"""
    return {"status": "ok"}
