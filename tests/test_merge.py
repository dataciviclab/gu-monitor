#!/usr/bin/env python3
"""Test della semantica di merge parquet (incrementale vs rebuild)."""

import sys
from pathlib import Path

import duckdb
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

from to_parquet import merge_esistente_nuovo  # noqa: E402


@pytest.fixture
def con():
    con = duckdb.connect(":memory:")
    con.execute(
        "CREATE TABLE existing (id VARCHAR, link VARCHAR, titolo VARCHAR, estremi VARCHAR)"
    )
    con.execute(
        "INSERT INTO existing VALUES "
        "('26G00151','L1','DECRETO 23 luglio 2026','DECRETO 23 luglio 2026'),"
        "('26A00001','L2','vecchio titolo','ALTRO')"
    )
    con.execute(
        "CREATE TABLE new_data (id VARCHAR, link VARCHAR, titolo VARCHAR, estremi VARCHAR)"
    )
    con.execute(
        "INSERT INTO new_data VALUES "
        "('26G00151','L1','Misure urgenti sui procedimenti','DECRETO-LEGGE 23 luglio 2026'),"
        "('26G00999','L3','Nuovo atto','DECRETO 1 ottobre 2026')"
    )
    yield con
    con.close()


def test_incrementale_la_riga_esistente_vince(con):
    merge_esistente_nuovo(con, rebuild=False)

    titolo = con.execute("SELECT titolo FROM merged WHERE id = '26G00151'").fetchone()[0]
    assert titolo == "DECRETO 23 luglio 2026"
    # il nuovo atto viene aggiunto
    assert con.execute("SELECT count(*) FROM merged").fetchone()[0] == 3


def test_rebuild_la_riga_ricostruita_vince(con):
    merge_esistente_nuovo(con, rebuild=True)

    titolo, estremi = con.execute(
        "SELECT titolo, estremi FROM merged WHERE id = '26G00151'"
    ).fetchone()
    assert titolo == "Misure urgenti sui procedimenti"
    assert estremi == "DECRETO-LEGGE 23 luglio 2026"
    # nessuna riga persa né duplicata
    assert con.execute("SELECT count(*) FROM merged").fetchone()[0] == 3


def test_chiave_id_ignora_il_link(con):
    """Stesso id con link diverso (flag elenco30giorni) non deve duplicare."""
    con.execute("UPDATE new_data SET link = 'L1-bis' WHERE id = '26G00151'")
    merge_esistente_nuovo(con, rebuild=True)

    assert (
        con.execute("SELECT count(*) FROM merged WHERE id = '26G00151'").fetchone()[0] == 1
    )
    assert (
        con.execute("SELECT link FROM merged WHERE id = '26G00151'").fetchone()[0] == "L1-bis"
    )


def test_colonne_allineate_tra_le_due_tabelle(con):
    """Una colonna nuova nel JSON deve comparire anche nelle righe esistenti."""
    con.execute("ALTER TABLE new_data ADD COLUMN origine VARCHAR")
    con.execute("UPDATE new_data SET origine = 'rebuild'")
    merge_esistente_nuovo(con, rebuild=True)

    cols = {r[0] for r in con.execute("DESCRIBE merged").fetchall()}
    assert "origine" in cols
    # le due righe ricostruite portano il valore, quella solo-esistente resta NULL
    assert (
        con.execute("SELECT count(*) FROM merged WHERE origine = 'rebuild'").fetchone()[0] == 2
    )
    assert con.execute("SELECT count(*) FROM merged WHERE origine IS NULL").fetchone()[0] == 1
