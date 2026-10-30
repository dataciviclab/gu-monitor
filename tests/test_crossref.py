#!/usr/bin/env python3
"""Test del ponte GU → Normattiva.

Regressione coperta: gli URN venivano applicati solo alle righe del JSON
del run corrente, quindi un atto il cui URN era stato trovato nei giorni
successivi alla pubblicazione non lo riceveva mai. Misurato sul repo:
71 lookup riusciti, 28 URN nel parquet, fermi per 15 commit.
"""

import json
import sys
from pathlib import Path

import duckdb
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

from to_parquet import apply_crossref  # noqa: E402


@pytest.fixture
def con():
    con = duckdb.connect(":memory:")
    yield con
    con.close()


def test_urn_applicato_anche_alle_righe_gia_presenti(tmp_path, con):
    con.execute("CREATE TABLE merged (id VARCHAR, titolo VARCHAR)")
    con.execute("INSERT INTO merged VALUES ('26G00151', 'vecchio'), ('26A00001', 'altro')")
    crossref = tmp_path / "gu_crossref.json"
    crossref.write_text(
        json.dumps(
            [
                {"id_gu": "26G00151", "urn": "urn:nir:stato:decreto.legge:2026-07-23;127"},
                {"id_gu": "26A00001", "urn": None},
            ]
        )
    )

    matched = apply_crossref(con, "merged", crossref)

    assert matched == 1
    urn, link = con.execute(
        "SELECT urn_normattiva, link_normattiva FROM merged WHERE id = '26G00151'"
    ).fetchone()
    assert urn == "urn:nir:stato:decreto.legge:2026-07-23;127"
    assert link.startswith("https://www.normattiva.it/uri-res/N2Ls?urn:nir:")
    assert con.execute(
        "SELECT urn_normattiva FROM merged WHERE id = '26A00001'"
    ).fetchone()[0] == ""


def test_senza_crossref_non_esplode(tmp_path, con):
    con.execute("CREATE TABLE merged (id VARCHAR)")
    con.execute("INSERT INTO merged VALUES ('26G00151')")

    assert apply_crossref(con, "merged", tmp_path / "assente.json") == 0
    assert con.execute("SELECT urn_normattiva FROM merged").fetchone()[0] == ""


def test_filtro_normativi_non_dipende_dall_anno(con):
    """Il filtro deve prendere 27G* a gennaio: niente anno hardcoded."""
    from crossref import SQL_NORMATIVI

    con.execute(
        "CREATE TABLE atti (id VARCHAR, serie VARCHAR, data_pubblicazione VARCHAR, "
        "titolo VARCHAR, tipo_atto VARCHAR)"
    )
    con.execute(
        "INSERT INTO atti VALUES "
        "('26G00151','SG','2026-07-23','a','DECRETO'),"
        "('27G00001','SG','2027-01-02','b','LEGGE'),"
        "('26A00001','SG','2026-07-23','c','DECRETO'),"
        "('26G99999','S4','2026-07-23','d','CONCORSO')"
    )

    ids = [r[0] for r in con.execute(SQL_NORMATIVI).fetchall()]
    assert ids == ["26G00151", "27G00001"]
