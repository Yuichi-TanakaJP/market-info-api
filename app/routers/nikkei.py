from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app import cache, r2

router = APIRouter(prefix="/nikkei", tags=["nikkei"])

_PREFIX = "nikkei-contribution"
_MANIFEST_FILE = "nikkei_contribution_manifest.json"


@router.get(
    "/manifest",
    summary="日経寄与度 manifest を取得",
    responses={502: {"description": "R2 からの取得失敗"}},
)
async def get_manifest() -> dict:
    """nikkei_contribution_manifest.json を返す。

    - `latest_date`: 最新日付（YYYY-MM-DD）
    - `dates`: 利用可能な日付の一覧

    更新単位: 営業日ごと。
    """
    try:
        return await cache.get_manifest(
            f"{_PREFIX}/manifest",
            lambda: r2.fetch_json(f"{_PREFIX}/{_MANIFEST_FILE}"),
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.get(
    "/{date}",
    summary="指定日の日経寄与度 JSON を取得",
    responses={
        404: {"description": "指定日のデータが R2 に存在しない"},
        502: {"description": "R2 からの取得失敗"},
    },
)
async def get_day(date: str) -> dict:
    """YYYY-MM-DD 形式の日付に対応する日経平均寄与度 JSON を返す。

    - `date`: 対象日（YYYY-MM-DD）
    - `contributions`: 銘柄ごとの寄与度データ配列

    404 の場合: 休場日・未来日・バッチ未実行日のいずれか。
    """
    file_name = f"nikkei_contribution_{date}.json"
    try:
        return await cache.get_day(
            f"{_PREFIX}/{date}",
            lambda: r2.fetch_json(f"{_PREFIX}/{file_name}"),
        )
    except Exception as exc:
        status = getattr(getattr(exc, "response", None), "status_code", None)
        if status == 404:
            raise HTTPException(status_code=404, detail=f"nikkei contribution not found: {date}") from exc
        raise HTTPException(status_code=502, detail=str(exc)) from exc
