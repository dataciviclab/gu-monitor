#!/usr/bin/env python3
"""Guardia sull'event log (lo store).

Lo store non è in git: se manca, i test si saltano (`make store-pull` per
averlo). Quando c'è, questi test proteggono il contratto delle colonne.
"""

import sys
from pathlib import Path

import duckdb
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

STORE = Path(__file__).parent.parent / "data" / "gu_acts.parquet"

ATTESE = {
    "id", "serie", "gazzetta_numero", "data_pubblicazione", "titolo",
    "estremi", "tipo_atto", "ente", "topic_str", "link",
    "urn_normattiva", "link_normattiva",
}


@pytest.fixture(scope="module")
def con():
    if not STORE.exists():
        pytest.skip("event log assente: esegui `make store-pull`")
    conn = duckdb.connect()
    conn.execute(f"CREATE TABLE atti AS SELECT * FROM read_parquet('{STORE}')")
    yield conn
    conn.close()


def test_schema(con):
    colonne = {r[0] for r in con.execute("DESCRIBE atti").fetchall()}
    assert ATTESE.issubset(colonne)


def test_chiave_id_unica(con):
    duplicati = con.execute(
        "SELECT count(*) FROM (SELECT id FROM atti GROUP BY 1 HAVING count(*) > 1)"
    ).fetchone()[0]
    assert duplicati == 0


def test_tutte_le_serie(con):
    serie = {r[0] for r in con.execute("SELECT DISTINCT serie FROM atti").fetchall()}
    assert serie == {"SG", "S1", "S2", "S3", "S4", "S5", "P2"}


def test_date_valide(con):
    minore, maggiore = con.execute(
        "SELECT min(data_pubblicazione), max(data_pubblicazione) FROM atti"
    ).fetchone()
    assert minore is not None and maggiore is not None
    assert maggiore >= minore


def test_urn_solo_su_atti_normativi(con):
    """Un URN fuori dai codici AAGG###### sarebbe un errore di crossref."""
    sporchi = con.execute(
        """SELECT count(*) FROM atti
           WHERE urn_normattiva <> '' AND NOT regexp_matches(id, '^[0-9]{2}G')"""
    ).fetchone()[0]
    assert sporchi == 0
