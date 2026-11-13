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

# Dedicated private credit-history scope; absent configuration fails closed.
CREDIT_HISTORY_API_KEY = os.getenv("CREDIT_HISTORY_API_KEY", "").strip()
CREDIT_HISTORY_PRIVATE_BUCKET = os.getenv("CREDIT_HISTORY_PRIVATE_BUCKET", "").strip()
CREDIT_HISTORY_PRIVATE_ENDPOINT = os.getenv("CREDIT_HISTORY_PRIVATE_ENDPOINT", "").strip()
CREDIT_HISTORY_PRIVATE_ACCESS_KEY_ID = os.getenv("CREDIT_HISTORY_PRIVATE_ACCESS_KEY_ID", "").strip()
CREDIT_HISTORY_PRIVATE_SECRET_ACCESS_KEY = os.getenv("CREDIT_HISTORY_PRIVATE_SECRET_ACCESS_KEY", "").strip()
CREDIT_HISTORY_PRIVATE_REGION = os.getenv("CREDIT_HISTORY_PRIVATE_REGION", "auto").strip() or "auto"

# Dedicated private dividend source read scope; no public/auth fallback.
DIVIDEND_SOURCE_API_KEY = os.getenv("DIVIDEND_SOURCE_API_KEY", "").strip()
DIVIDEND_SOURCE_PRIVATE_BUCKET = os.getenv("DIVIDEND_SOURCE_PRIVATE_BUCKET", "").strip()
DIVIDEND_SOURCE_PRIVATE_ENDPOINT = os.getenv("DIVIDEND_SOURCE_PRIVATE_ENDPOINT", "").strip()
DIVIDEND_SOURCE_PRIVATE_ACCESS_KEY_ID = os.getenv("DIVIDEND_SOURCE_PRIVATE_ACCESS_KEY_ID", "").strip()
DIVIDEND_SOURCE_PRIVATE_SECRET_ACCESS_KEY = os.getenv("DIVIDEND_SOURCE_PRIVATE_SECRET_ACCESS_KEY", "").strip()
DIVIDEND_SOURCE_PRIVATE_REGION = os.getenv("DIVIDEND_SOURCE_PRIVATE_REGION", "auto").strip() or "auto"

# Dedicated pending comparison read scope; no public/other-feature fallback.
YUTAI_COMPARISON_API_KEY = os.getenv("YUTAI_COMPARISON_API_KEY", "").strip()
YUTAI_COMPARISON_PRIVATE_BUCKET = os.getenv("YUTAI_COMPARISON_PRIVATE_BUCKET", "").strip()
YUTAI_COMPARISON_PRIVATE_ENDPOINT = os.getenv("YUTAI_COMPARISON_PRIVATE_ENDPOINT", "").strip()
YUTAI_COMPARISON_PRIVATE_ACCESS_KEY_ID = os.getenv("YUTAI_COMPARISON_PRIVATE_ACCESS_KEY_ID", "").strip()
YUTAI_COMPARISON_PRIVATE_SECRET_ACCESS_KEY = os.getenv("YUTAI_COMPARISON_PRIVATE_SECRET_ACCESS_KEY", "").strip()
YUTAI_COMPARISON_PRIVATE_REGION = os.getenv("YUTAI_COMPARISON_PRIVATE_REGION", "auto").strip() or "auto"

# Dedicated reviewed V2 source scope; no comparison/public fallback.
YUTAI_NORMALIZED_API_KEY = os.getenv("YUTAI_NORMALIZED_API_KEY", "").strip()
YUTAI_NORMALIZED_PRIVATE_BUCKET = os.getenv("YUTAI_NORMALIZED_PRIVATE_BUCKET", "").strip()
YUTAI_NORMALIZED_PRIVATE_ENDPOINT = os.getenv("YUTAI_NORMALIZED_PRIVATE_ENDPOINT", "").strip()
YUTAI_NORMALIZED_PRIVATE_ACCESS_KEY_ID = os.getenv("YUTAI_NORMALIZED_PRIVATE_ACCESS_KEY_ID", "").strip()
YUTAI_NORMALIZED_PRIVATE_SECRET_ACCESS_KEY = os.getenv("YUTAI_NORMALIZED_PRIVATE_SECRET_ACCESS_KEY", "").strip()
YUTAI_NORMALIZED_PRIVATE_REGION = os.getenv("YUTAI_NORMALIZED_PRIVATE_REGION", "auto").strip()
