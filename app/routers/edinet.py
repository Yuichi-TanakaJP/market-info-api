from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict

from app import cache, r2

router = APIRouter(prefix="/edinet", tags=["edinet"])

_PREFIX = "edinet/document-list"


class EdinetItem(BaseModel):
    model_config = ConfigDict(extra="allow")
    doc_id: str
    submit_datetime: str | None
    edinet_code: str | None
    sec_code: str | None
    filer_name: str | None
    doc_type_code: str | None
    doc_description: str | None
    has_xbrl: bool
    has_pdf: bool
    has_csv: bool


class EdinetDocumentList(BaseModel):
    model_config = ConfigDict(extra="allow")
    as_of_date: str
    total_count: int
    items: list[EdinetItem]


@router.get(
    "/document-list/latest",
    response_model=EdinetDocumentList,
    summary="EDINET書類一覧（最新）を取得",
    responses={502: {"description": "R2 からの取得失敗"}},
)
async def get_latest() -> dict:
    """最新日の EDINET 提出書類一覧を返す。

    - `as_of_date`: データの対象日（YYYY-MM-DD）
    - `total_count`: 提出書類の総件数
    - `items`: 書類エントリの配列

    更新単位: 日次（平日）。週末・祝日は件数 0 になる場合がある。
    """
    try:
        return await cache.get_manifest(
            f"{_PREFIX}/latest",
            lambda: r2.fetch_json(f"{_PREFIX}/latest.json"),
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.get(
    "/document-list/{date}",
    response_model=EdinetDocumentList,
    summary="EDINET書類一覧（日付指定）を取得",
    responses={
        404: {"description": "指定日のデータが R2 に存在しない"},
        502: {"description": "R2 からの取得失敗"},
    },
)
async def get_by_date(date: str) -> dict:
    """YYYY-MM-DD 形式の日付に対応する EDINET 提出書類一覧を返す。

    404 の場合: 指定日のデータが存在しない（未取得日・休日など）。
    """
    try:
        return await cache.get_day(
            f"{_PREFIX}/{date}",
            lambda: r2.fetch_json(f"{_PREFIX}/{date}.json"),
        )
    except Exception as exc:
        status = getattr(getattr(exc, "response", None), "status_code", None)
        if status == 404:
            raise HTTPException(status_code=404, detail=f"edinet document-list not found: {date}") from exc
        raise HTTPException(status_code=502, detail=str(exc)) from exc
