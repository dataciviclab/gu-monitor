from pathlib import Path

from lab_connectors.duckdb.sql_page import render_sql_query
from lab_connectors.registry import load_registry
from sources import PREFIX, SLUG

ROOT = Path(__file__).resolve().parent.parent.parent

render_sql_query(
    registry=load_registry(ROOT / "registry" / "registry.json"),
    prefix=PREFIX,
    default_slug=SLUG,
    title="🧪 Query SQL",
)
