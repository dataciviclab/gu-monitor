"""Data access layer — GU Monitor.

Tutti i dati vengono dal clean pubblicato su GCS, risolto dal registry del
repo. Nessun URL hardcoded, nessuna lettura dall'event log locale.
"""

from __future__ import annotations

from pathlib import Path

import streamlit as st
from lab_connectors.duckdb.queries import (
    load_mart_table as _load_mart_table,
)
from lab_connectors.duckdb.queries import (
    query_clean as _query_clean,
)
from lab_connectors.duckdb.queries import years_from_registry
from lab_connectors.formatters import fmt_num, fmt_pct
from lab_connectors.registry import load_registry

__all__ = ["PREFIX", "SLUG", "YEAR_DEFAULT", "YEARS", "query", "load_mart", "urn_url", "fmt_num", "fmt_pct"]

ROOT = Path(__file__).parent.parent
PREFIX = "gu-monitor/"
SLUG = "gu_atti"
YEAR_DEFAULT = 2026

registry = load_registry(ROOT / "registry" / "registry.json")
YEARS = years_from_registry(registry, slug=SLUG) or [YEAR_DEFAULT]


@st.cache_data(ttl=3600, show_spinner=False)
def query(sql: str, year: int = YEAR_DEFAULT):
    return _query_clean(SLUG, sql, [year], prefix=PREFIX, registry=registry)


@st.cache_data(ttl=3600, show_spinner=False)
def load_mart(table: str, year: int = YEAR_DEFAULT):
    return _load_mart_table(SLUG, table, year, prefix=PREFIX, registry=registry)


def urn_url(urn: str) -> str:
    return f"https://www.normattiva.it/uri-res/N2Ls?{urn}"
