from __future__ import annotations

import re

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict

from app import cache, r2

router = APIRouter(prefix="/tdnet", tags=["tdnet"])

_PREFIX = "tdnet/disclosures"
_DATE_RE = re.compile(r"^\d{4}-(?:0[1-9]|1[0-2])-(?:0[1-9]|[12]\d|3[01])$")


class TdnetDisclosureItem(BaseModel):
    model_config = ConfigDict(extra="allow")
    disclosure_date: str
    disclosure_time: str
    security_code: str
    company_name: str
    title: str
    disclosure_category: str
    pdf_url: str
    xbrl_url: str
    html_url: str
    has_pdf: bool
    has_xbrl: bool
    has_html: bool
    is_financial_related: bool
    is_earnings_release: bool
    is_correction: bool
    fetched_at: str


class TdnetDisclosures(BaseModel):
    model_config = ConfigDict(extra="allow")
    target_date: str
    source: str
    total_count: int
    items: list[TdnetDisclosureItem]


@router.get(
    "/disclosures/latest",
    response_model=TdnetDisclosures,
    summary="TDNET 全適時開示一覧（最新）を取得",
    responses={
        404: {"description": "R2 にファイルが存在しない"},
        502: {"description": "R2 からの取得失敗"},
    },
)
async def get_disclosures_latest() -> dict:
    """最新日の TDNET 全適時開示一覧を返す。

    - `target_date`: データの対象日（YYYY-MM-DD）
    - `items`: 適時開示エントリの配列

    この API は PDF を再配信せず、market_info が抽出した TDNET 原文 URL を返す。
    更新単位: 平日 1日1回（TDNET 取得バッチ後）。キャッシュ TTL: 6時間（可変）。
    """
    try:
        return await cache.get_manifest(
            f"{_PREFIX}/latest",
            lambda: r2.fetch_json(f"{_PREFIX}/latest.json"),
        )
    except Exception as exc:
        status = getattr(getattr(exc, "response", None), "status_code", None)
        if status == 404:
            raise HTTPException(status_code=404, detail="tdnet disclosures latest not found") from exc
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.get(
    "/disclosures/{date}",
    response_model=TdnetDisclosures,
    summary="指定日の TDNET 全適時開示一覧を取得",
    responses={
        404: {"description": "指定日のデータが R2 に存在しない"},
        502: {"description": "R2 からの取得失敗"},
    },
)
async def get_disclosures_by_date(date: str) -> dict:
    """YYYY-MM-DD 形式の日付に対応する TDNET 全適時開示一覧を返す。

    404 の場合: 指定日のデータが存在しない（未取得日・未来日・publish 未実行日など）。
    422 の場合: date が YYYY-MM-DD 形式でない。キャッシュ TTL: 24時間（不変）。
    """
    if not _DATE_RE.match(date):
        raise HTTPException(status_code=422, detail="date must be YYYY-MM-DD format")
    try:
        return await cache.get_day(
            f"{_PREFIX}/{date}",
            lambda: r2.fetch_json(f"{_PREFIX}/{date}.json"),
        )
    except Exception as exc:
        status = getattr(getattr(exc, "response", None), "status_code", None)
        if status == 404:
            raise HTTPException(status_code=404, detail=f"tdnet disclosures not found: {date}") from exc
        raise HTTPException(status_code=502, detail=str(exc)) from exc
