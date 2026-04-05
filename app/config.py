from __future__ import annotations

import os


def _required(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"missing required env var: {name}")
    return value


R2_PUBLIC_BASE_URL: str = _required("R2_PUBLIC_BASE_URL")

# 未設定 = 認証なし（将来 env var を設定するだけで有効化）
MARKET_INFO_API_KEY: str = os.getenv("MARKET_INFO_API_KEY", "").strip()


def get_jpx_closed_object_key() -> str:
    value = os.getenv("JPX_CLOSED_OBJECT_KEY", "").strip()
    if not value:
        raise RuntimeError("missing required env var for /market-calendar/jpx-closed: JPX_CLOSED_OBJECT_KEY")
    return value
