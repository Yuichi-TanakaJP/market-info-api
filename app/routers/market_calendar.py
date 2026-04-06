from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app import cache, r2
from app.config import JPX_CLOSED_OBJECT_KEY

router = APIRouter(prefix="/market-calendar", tags=["market-calendar"])


@router.get(
    "/jpx-closed",
    summary="JPX 休場日カレンダーを取得",
    responses={
        404: {"description": "R2 にファイルが存在しない"},
        502: {"description": "R2 からの取得失敗"},
    },
)
async def get_jpx_closed() -> dict:
    """JPX 休場日の thin JSON を返す。

    - `closed_dates`: 休場日の日付リスト（YYYY-MM-DD 形式）

    更新単位: 不定期（年次カレンダー更新時）。
    mini-tools はこのデータを使って営業日判定を行う。
    """
    try:
        return await cache.get_manifest(
            "market-calendar/jpx-closed",
            lambda: r2.fetch_json(JPX_CLOSED_OBJECT_KEY),
        )
    except Exception as exc:
        status = getattr(getattr(exc, "response", None), "status_code", None)
        if status == 404:
            raise HTTPException(status_code=404, detail="jpx closed calendar not found") from exc
        raise HTTPException(status_code=502, detail=str(exc)) from exc
