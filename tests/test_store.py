#!/usr/bin/env python3
"""Test del merge store (incrementale vs backfill) e degli URN Normattiva."""

import sys
from pathlib import Path

import duckdb
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

from collect import applica_urn, build_urn, merge, urn_pendenti  # noqa: E402

RIGA = {
    "id": "26G00151",
    "serie": "SG",
    "gazzetta_numero": "169",
    "data_pubblicazione": "2026-07-23",
    "titolo": "Misure urgenti",
    "estremi": "DECRETO-LEGGE 23 luglio 2026, n. 127",
    "tipo_atto": "DECRETO-LEGGE",
    "ente": "PRESIDENZA DEL CONSIGLIO DEI MINISTRI",
    "topic_str": "",
    "link": "L1",
    "urn_normattiva": None,
    "link_normattiva": None,
}


def _store(tmp_path: Path, righe: list[dict]) -> Path:
    store = tmp_path / "store.parquet"
    con = duckdb.connect()
    con.execute("CREATE TABLE t AS SELECT * FROM (SELECT 1) WHERE false")
    con.close()
    if righe:
        con = duckdb.connect()
        columns = ", ".join(f"{k} VARCHAR" for k in righe[0])
        con.execute(f"CREATE TABLE t ({columns})")
        segnaposto = ", ".join("?" * len(righe[0]))
        con.executemany(
            f"INSERT INTO t VALUES ({segnaposto})", [[r.get(k) for k in righe[0]] for r in righe]
        )
        con.execute(f"COPY t TO '{store}' (FORMAT PARQUET)")
        con.close()
    return store


@pytest.fixture
def tmp_store(tmp_path):
    vecchio = dict(RIGA)
    vecchio.update({"titolo": "vecchio titolo", "link": "L1", "urn_normattiva": None})
    return _store(tmp_path, [vecchio])


def test_primo_run_crea_lo_store(tmp_path):
    store = tmp_path / "nuovo.parquet"
    con = duckdb.connect()
    totale = merge(con, store, [dict(RIGA)], rebuild=False)
    con.close()
    assert totale == 1


def test_incrementale_la_riga_esistente_vince(tmp_store):
    con = duckdb.connect()
    nuovo = dict(RIGA)
    nuovo["titolo"] = "titolo nuovo"
    totale = merge(con, tmp_store, [nuovo], rebuild=False)
    titolo = con.execute("SELECT titolo FROM merged").fetchone()[0]
    con.close()
    assert totale == 1
    assert titolo == "vecchio titolo"


def test_backfill_la_riga_ricostruita_vince(tmp_store):
    con = duckdb.connect()
    nuovo = dict(RIGA)
    nuovo["titolo"] = "titolo nuovo"
    totale = merge(con, tmp_store, [nuovo], rebuild=True)
    titolo = con.execute("SELECT titolo FROM merged").fetchone()[0]
    con.close()
    assert totale == 1
    assert titolo == "titolo nuovo"


def test_chiave_id_ignora_il_link(tmp_store):
    con = duckdb.connect()
    nuovo = dict(RIGA)
    nuovo["link"] = "L1-bis"
    totale = merge(con, tmp_store, [nuovo], rebuild=True)
    con.close()
    assert totale == 1


class TestUrn:
    def test_build_urn_tipi(self):
        assert build_urn("LEGGE", 2026, 7, 16, 129) == "urn:nir:stato:legge:2026-07-16;129"
        assert (
            build_urn("DECRETO-LEGGE", 2026, 7, 23, 127)
            == "urn:nir:stato:decreto.legge:2026-07-23;127"
        )

    def test_urn_pendenti_solo_normativi_senza_urn(self):
        con = duckdb.connect()
        con.execute(
            "CREATE TABLE merged (id VARCHAR, serie VARCHAR, data_pubblicazione VARCHAR, "
            "urn_normattiva VARCHAR)"
        )
        con.execute(
            "INSERT INTO merged VALUES "
            "('26G00151','SG','2026-07-23',NULL),"
            "('26G00152','SG','2026-07-24','urn:gia:risolto'),"
            "('26A00001','SG','2026-07-24',NULL),"
            "('26G00153','S4','2026-07-24',NULL)"
        )
        assert urn_pendenti(con, "merged") == [("26G00151", "2026-07-23")]
        con.close()

    def test_applica_urn_scrive_link(self):
        con = duckdb.connect()
        con.execute(
            "CREATE TABLE merged (id VARCHAR, urn_normattiva VARCHAR, link_normattiva VARCHAR)"
        )
        con.execute("INSERT INTO merged VALUES ('26G00151', NULL, NULL)")
        applica_urn(con, "merged", [("26G00151", "urn:nir:stato:legge:2026-07-16;129")])
        urn, link = con.execute("SELECT urn_normattiva, link_normattiva FROM merged").fetchone()
        con.close()
        assert urn == "urn:nir:stato:legge:2026-07-16;129"
        assert link.startswith("https://www.normattiva.it/uri-res/N2Ls?urn:nir:")
