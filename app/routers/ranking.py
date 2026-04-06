from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app import cache, r2

router = APIRouter(prefix="/ranking", tags=["ranking"])

_PREFIX = "stock-ranking"


@router.get(
    "/manifest",
    summary="ランキング manifest を取得",
    responses={502: {"description": "R2 からの取得失敗"}},
)
async def get_manifest() -> dict:
    """manifest.json を返す。

    - `latest`: 最新日付（YYYY-MM-DD）
    - `dates`: 利用可能な日付の一覧

    更新単位: 営業日ごと（market_info の日次バッチ完了後に R2 へ publish される）。
    """
    try:
        return await cache.get_manifest(
            f"{_PREFIX}/manifest",
            lambda: r2.fetch_json(f"{_PREFIX}/manifest.json"),
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.get(
    "/{date}",
    summary="指定日のランキング JSON を取得",
    responses={
        404: {"description": "指定日のデータが R2 に存在しない（休場日・未来日・バッチ未実行日）"},
        502: {"description": "R2 からの取得失敗"},
    },
)
async def get_day(date: str) -> dict:
    """YYYY-MM-DD 形式の日付に対応する日次ランキング JSON を返す。

    - `date`: 対象日（YYYY-MM-DD）
    - `rankings`: 銘柄ごとのランキングデータ配列

    404 の場合: 休場日・未来日・バッチ未実行日のいずれか。
    mini-tools 側は manifest の `dates` に含まれる日付のみリクエストすること。
    """
    file_key = date.replace("-", "")
    try:
        return await cache.get_day(
            f"{_PREFIX}/{file_key}",
            lambda: r2.fetch_json(f"{_PREFIX}/{file_key}.json"),
        )
    except Exception as exc:
        status = getattr(getattr(exc, "response", None), "status_code", None)
        if status == 404:
            raise HTTPException(status_code=404, detail=f"ranking not found: {date}") from exc
        raise HTTPException(status_code=502, detail=str(exc)) from exc
