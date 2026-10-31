"""Smoke test della dashboard: compila le pagine e legge il registry."""

from __future__ import annotations

import json
import py_compile
from pathlib import Path

import pytest

pytestmark = pytest.mark.smoke

DASH = Path(__file__).resolve().parent.parent
ROOT = DASH.parent
REGISTRY = ROOT / "registry" / "registry.json"

MODULI = [
    DASH / "app.py",
    DASH / "sources.py",
    *sorted((DASH / "pages").glob("*.py")),
]


@pytest.mark.parametrize("path", MODULI, ids=lambda p: p.name)
def test_compila(path: Path):
    py_compile.compile(str(path), doraise=True)


def test_registry_esiste_e_contiene_il_dataset():
    assert REGISTRY.exists(), "registry/registry.json mancante"
    reg = json.loads(REGISTRY.read_text())
    slug = {d["slug"] for d in reg.get("datasets", [])}
    assert "gu_atti" in slug


def test_requirements_allineato_al_pyproject():
    req = (DASH / "requirements.txt").read_text()
    assert "streamlit" in req
    assert "plotly" in req


def test_pagine_girano_senza_eccezioni():
    """Esegue le pagine davvero: una query su una colonna rimossa passa il
    py_compile ma esplode qui (è il caso topic_str)."""
    import sys

    AppTest = pytest.importorskip("streamlit.testing.v1").AppTest
    sys.path.insert(0, str(DASH))

    import sources  # fuori dal try: un ImportError è una rottura, non un skip

    try:
        colonne = sources.query("SELECT * FROM clean_input LIMIT 0").columns
    except Exception as e:  # noqa: BLE001
        pytest.skip(f"clean non raggiungibile: {e}")

    # Tra il merge e il rebuild il clean pubblicato ha ancora lo schema
    # vecchio: la dashboard non può girare, e il test deve dirlo invece di
    # fallire. Dopo il rebuild questa riga non salta più.
    if "codice_genere" not in colonne:
        pytest.skip("clean pubblicato non ancora migrato (rebuild in coda)")

    for page in sorted((DASH / "pages").glob("*.py")):
        at = AppTest.from_file(str(page), default_timeout=120)
        at.run()
        assert not at.exception, f"{page.name}: {[e.value for e in at.exception][:1]}"
