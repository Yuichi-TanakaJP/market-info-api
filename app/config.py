from __future__ import annotations

import os


def _required(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"missing required env var: {name}")
    return value


R2_PUBLIC_BASE_URL: str = _required("R2_PUBLIC_BASE_URL")
JPX_CLOSED_OBJECT_KEY: str = "market_closed/jpx_market_closed_latest.json"
US_CLOSED_OBJECT_KEY: str = "market_closed/us_market_closed_latest.json"

# 未設定 = 認証なし（将来 env var を設定するだけで有効化）
MARKET_INFO_API_KEY: str = os.getenv("MARKET_INFO_API_KEY", "").strip()

YUTAI_STOCK_PRICES_API_KEY: str = os.getenv("YUTAI_STOCK_PRICES_API_KEY", "").strip()
YUTAI_STOCK_PRICES_PRIVATE_BUCKET: str = os.getenv(
    "YUTAI_STOCK_PRICES_PRIVATE_BUCKET", ""
).strip()
YUTAI_STOCK_PRICES_PRIVATE_ENDPOINT: str = os.getenv(
    "YUTAI_STOCK_PRICES_PRIVATE_ENDPOINT", ""
).strip()
YUTAI_STOCK_PRICES_PRIVATE_ACCESS_KEY_ID: str = os.getenv(
    "YUTAI_STOCK_PRICES_PRIVATE_ACCESS_KEY_ID", ""
).strip()
YUTAI_STOCK_PRICES_PRIVATE_SECRET_ACCESS_KEY: str = os.getenv(
    "YUTAI_STOCK_PRICES_PRIVATE_SECRET_ACCESS_KEY", ""
).strip()
YUTAI_STOCK_PRICES_PRIVATE_REGION: str = (
    os.getenv("YUTAI_STOCK_PRICES_PRIVATE_REGION", "auto").strip() or "auto"
)
