from __future__ import annotations

import re

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict

from app import cache, r2

router = APIRouter(prefix="/investor-flow", tags=["investor-flow"])

_PREFIX = "investor-flow"
_ANALYSIS_PREFIX = "investor-flow-analysis"
_DATE_RE = re.compile(r"^\d{4}-(?:0[1-9]|1[0-2])-(?:0[1-9]|[12]\d|3[01])$")


class InvestorFlowWeekRef(BaseModel):
    model_config = ConfigDict(extra="allow")
    start_date: str
    end_date: str
    path: str


class InvestorFlowManifest(BaseModel):
    model_config = ConfigDict(extra="allow")
    data_source: str
    latest: InvestorFlowWeekRef
    weeks: list[InvestorFlowWeekRef]
    generated_at_jst: str


class InvestorFlowRecord(BaseModel):
    model_config = ConfigDict(extra="allow")
    row_index: int
    category: str
    sell_thousand_yen: int
    share_sell_pct: float | None
    buy_thousand_yen: int
    share_buy_pct: float | None
    diff_thousand_yen: int
    sell_yen: int
    buy_yen: int
    diff_yen: int


class InvestorFlowPayload(BaseModel):
    model_config = ConfigDict(extra="allow")
    data_source: str
    source_url: str
    source_file: str
    week_label_raw: str
    start_date: str
    end_date: str
    market_scope: str
    unit: str
    generated_at_jst: str
    records: list[InvestorFlowRecord]


class InvestorFlowAnalysisManifest(BaseModel):
    model_config = ConfigDict(extra="allow")
    data_source: str
    schema_version: str
    latest: InvestorFlowWeekRef
    weeks: list[InvestorFlowWeekRef]
    generated_at_jst: str


class InvestorFlowAnalysisCategoryAmount(BaseModel):
    model_config = ConfigDict(extra="allow")
    category: str
    diff_yen: int


class InvestorFlowCompositionItem(BaseModel):
    model_config = ConfigDict(extra="allow")
    group: str
    denominator_category: str
    category: str
    parent_category: str
    amount_yen: int
    share_pct: float | None
    level: int
    is_top_level: bool


class InvestorFlowNetRankingItem(BaseModel):
    model_config = ConfigDict(extra="allow")
    category: str
    buy_yen: int | None
    sell_yen: int | None
    diff_yen: int
    direction: str
    previous_diff_yen: int | None
    diff_change_yen: int | None
    rank_by_abs_diff: int


class InvestorFlowReversalItem(BaseModel):
    model_config = ConfigDict(extra="allow")
    category: str
    from_direction: str
    to_direction: str
    previous_diff_yen: int
    current_diff_yen: int
    change_yen: int
    strength: str


class InvestorFlowStreakItem(BaseModel):
    model_config = ConfigDict(extra="allow")
    category: str
    direction: str
    weeks: int
    current_diff_yen: int | None
    started_start_date: str | None
    started_end_date: str | None


class InvestorFlowMajorFlowItem(BaseModel):
    model_config = ConfigDict(extra="allow")
    category: str
    buy_yen: int | None
    sell_yen: int | None
    diff_yen: int | None
    direction: str
    previous_diff_yen: int | None
    diff_change_yen: int | None


class InvestorFlowHistoryMatrixCell(BaseModel):
    model_config = ConfigDict(extra="allow")
    start_date: str | None
    end_date: str | None
    buy_yen: int | None
    sell_yen: int | None
    diff_yen: int | None
    direction: str
    strength: str | None


class InvestorFlowHistoryMatrixWeek(BaseModel):
    model_config = ConfigDict(extra="allow")
    start_date: str | None
    end_date: str | None
    source_snapshot_path: str


class InvestorFlowHistoryMatrixRow(BaseModel):
    model_config = ConfigDict(extra="allow")
    category: str
    cells: list[InvestorFlowHistoryMatrixCell]


class InvestorFlowHistoryMatrix(BaseModel):
    model_config = ConfigDict(extra="allow")
    weeks: list[InvestorFlowHistoryMatrixWeek]
    rows: list[InvestorFlowHistoryMatrixRow]


class InvestorFlowAnalysisSummary(BaseModel):
    model_config = ConfigDict(extra="allow")
    largest_net_buy: InvestorFlowAnalysisCategoryAmount | None
    largest_net_sell: InvestorFlowAnalysisCategoryAmount | None


class InvestorFlowAnalysisPayload(BaseModel):
    model_config = ConfigDict(extra="allow")
    schema_version: str
    data_source: str
    analysis_scope: str
    start_date: str
    end_date: str
    previous_start_date: str | None
    previous_end_date: str | None
    generated_at_jst: str
    source_snapshot_path: str
    lookback_weeks: int
    summary: InvestorFlowAnalysisSummary
    buy_composition: list[InvestorFlowCompositionItem]
    sell_composition: list[InvestorFlowCompositionItem]
    net_ranking: list[InvestorFlowNetRankingItem]
    reversals: list[InvestorFlowReversalItem]
    streaks: list[InvestorFlowStreakItem]
    major_flows: list[InvestorFlowMajorFlowItem]
    history_matrix: InvestorFlowHistoryMatrix | None = None


@router.get(
    "/latest",
    response_model=InvestorFlowPayload,
    summary="投資主体別売買動向（最新）を取得",
    responses={
        404: {"description": "最新データが R2 に存在しない"},
        502: {"description": "R2 からの取得失敗"},
    },
)
async def get_latest() -> dict:
    """最新週の JPX 投資主体別売買動向を返す。

    更新単位: 週次。キャッシュ TTL: 6時間（可変）。
    """
    try:
        return await cache.get_manifest(
            f"{_PREFIX}/latest",
            lambda: r2.fetch_json(f"{_PREFIX}/latest.json"),
        )
    except Exception as exc:
        status = getattr(getattr(exc, "response", None), "status_code", None)
        if status == 404:
            raise HTTPException(status_code=404, detail="investor-flow latest not found") from exc
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.get(
    "/manifest",
    response_model=InvestorFlowManifest,
    summary="投資主体別売買動向 manifest を取得",
    responses={502: {"description": "R2 からの取得失敗"}},
)
async def get_manifest() -> dict:
    """利用可能な週次 snapshot の一覧を返す。

    キャッシュ TTL: 6時間（可変）。
    """
    try:
        return await cache.get_manifest(
            f"{_PREFIX}/manifest",
            lambda: r2.fetch_json(f"{_PREFIX}/manifest.json"),
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.get(
    "/weeks/{start_date}/{end_date}",
    response_model=InvestorFlowPayload,
    summary="指定週の投資主体別売買動向を取得",
    responses={
        404: {"description": "指定週のデータが R2 に存在しない"},
        422: {"description": "start_date / end_date が YYYY-MM-DD 形式でない"},
        502: {"description": "R2 からの取得失敗"},
    },
)
async def get_week(start_date: str, end_date: str) -> dict:
    """YYYY-MM-DD の開始日・終了日に対応する週次 snapshot を返す。

    404 の場合: 指定週のデータが存在しない。manifest の `weeks[].path` に含まれる週のみリクエストすること。
    422 の場合: start_date / end_date が YYYY-MM-DD 形式でない。キャッシュ TTL: 24時間（不変）。
    """
    if not _DATE_RE.match(start_date) or not _DATE_RE.match(end_date):
        raise HTTPException(status_code=422, detail="start_date and end_date must be YYYY-MM-DD format")
    object_name = f"investor_flow_{start_date}_to_{end_date}.json"
    try:
        return await cache.get_day(
            f"{_PREFIX}/{start_date}/{end_date}",
            lambda: r2.fetch_json(f"{_PREFIX}/{object_name}"),
        )
    except Exception as exc:
        status = getattr(getattr(exc, "response", None), "status_code", None)
        if status == 404:
            raise HTTPException(
                status_code=404,
                detail=f"investor-flow week not found: {start_date} to {end_date}",
            ) from exc
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.get(
    "/analysis/latest",
    response_model=InvestorFlowAnalysisPayload,
    summary="投資主体別売買動向の分析サマリー（最新）を取得",
    responses={
        404: {"description": "最新分析データが R2 に存在しない"},
        502: {"description": "R2 からの取得失敗"},
    },
)
async def get_analysis_latest() -> dict:
    """最新週の JPX 投資主体別売買動向から生成した分析サマリーを返す。

    更新単位: 週次。キャッシュ TTL: 6時間（可変）。
    """
    try:
        return await cache.get_manifest(
            f"{_ANALYSIS_PREFIX}/latest",
            lambda: r2.fetch_json(f"{_ANALYSIS_PREFIX}/latest.json"),
        )
    except Exception as exc:
        status = getattr(getattr(exc, "response", None), "status_code", None)
        if status == 404:
            raise HTTPException(status_code=404, detail="investor-flow analysis latest not found") from exc
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.get(
    "/analysis/manifest",
    response_model=InvestorFlowAnalysisManifest,
    summary="投資主体別売買動向の分析 manifest を取得",
    responses={502: {"description": "R2 からの取得失敗"}},
)
async def get_analysis_manifest() -> dict:
    """利用可能な分析サマリー snapshot の一覧を返す。

    キャッシュ TTL: 6時間（可変）。
    """
    try:
        return await cache.get_manifest(
            f"{_ANALYSIS_PREFIX}/manifest",
            lambda: r2.fetch_json(f"{_ANALYSIS_PREFIX}/manifest.json"),
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.get(
    "/analysis/weeks/{start_date}/{end_date}",
    response_model=InvestorFlowAnalysisPayload,
    summary="指定週の投資主体別売買動向の分析サマリーを取得",
    responses={
        404: {"description": "指定週の分析データが R2 に存在しない"},
        422: {"description": "start_date / end_date が YYYY-MM-DD 形式でない"},
        502: {"description": "R2 からの取得失敗"},
    },
)
async def get_analysis_week(start_date: str, end_date: str) -> dict:
    """YYYY-MM-DD の開始日・終了日に対応する分析サマリー snapshot を返す。

    404 の場合: 指定週のデータが存在しない。manifest の `weeks[].path` に含まれる週のみリクエストすること。
    422 の場合: start_date / end_date が YYYY-MM-DD 形式でない。キャッシュ TTL: 24時間（不変）。
    """
    if not _DATE_RE.match(start_date) or not _DATE_RE.match(end_date):
        raise HTTPException(status_code=422, detail="start_date and end_date must be YYYY-MM-DD format")
    object_name = f"investor_flow_analysis_{start_date}_to_{end_date}.json"
    try:
        return await cache.get_day(
            f"{_ANALYSIS_PREFIX}/{start_date}/{end_date}",
            lambda: r2.fetch_json(f"{_ANALYSIS_PREFIX}/{object_name}"),
        )
    except Exception as exc:
        status = getattr(getattr(exc, "response", None), "status_code", None)
        if status == 404:
            raise HTTPException(
                status_code=404,
                detail=f"investor-flow analysis week not found: {start_date} to {end_date}",
            ) from exc
        raise HTTPException(status_code=502, detail=str(exc)) from exc
