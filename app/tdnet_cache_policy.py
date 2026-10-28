"""Freshness policy for mutable TDNET pointers, shared by all cache layers."""

TDNET_MUTABLE_KEYS = frozenset({
    "tdnet/disclosures/latest",
    "tdnet/router-events/latest",
    "tdnet/router-events/manifest",
    "disclosure-events/latest",
    "disclosure-events/manifest",
})
TDNET_MUTABLE_OBJECTS = frozenset(f"{key}.json" for key in TDNET_MUTABLE_KEYS)
TDNET_MUTABLE_API_PATHS = frozenset(f"/{key}" for key in TDNET_MUTABLE_KEYS)
TDNET_HTTP_CACHE_CONTROL = "no-store"
