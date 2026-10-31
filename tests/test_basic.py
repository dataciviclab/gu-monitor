#!/usr/bin/env python3
"""Contratto dello store (schema, chiave, classificazioni).

Non dipende dal file reale su GCS: costruisce uno store con `merge` e ne
verifica la forma. Così il test gira anche in CI, dove l'event log non c'è.
"""

import sys
from pathlib import Path

import duckdb
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

from collect import COLONNE, merge, urn_pendenti  # noqa: E402


def _riga(**override):
    base = {
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
    base.update(override)
    return base


@pytest.fixture
def con():
    con = duckdb.connect()
    yield con
    con.close()


def test_lo_store_ha_esattamente_le_colonne_del_contratto(con, tmp_path):
    merge(con, tmp_path / "store.parquet", [_riga()], rebuild=False)
    colonne = [r[0] for r in con.execute("DESCRIBE merged").fetchall()]
    assert colonne == list(COLONNE)


def test_la_chiave_e_id(con, tmp_path):
    store = tmp_path / "store.parquet"
    con_a = duckdb.connect()
    merge(con_a, store, [_riga()], rebuild=False)
    con_a.execute(f"COPY merged TO '{store}' (FORMAT PARQUET)")
    con_a.close()

    merge(con, store, [_riga(titolo="titolo nuovo")], rebuild=True)
    duplicati = con.execute(
        "SELECT count(*) FROM (SELECT id FROM merged GROUP BY 1 HAVING count(*) > 1)"
    ).fetchone()[0]
    assert duplicati == 0


def test_urn_solo_su_codici_normativi(con, tmp_path):
    """La regola che protegge il ponte: solo AAGG###### può avere un URN."""
    righe = [
        _riga(id="26G00151", urn_normattiva="urn:nir:stato:decreto.legge:2026-07-23;127"),
        _riga(id="26A00001", urn_normattiva=None),
    ]
    merge(con, tmp_path / "store.parquet", righe, rebuild=False)
    sporchi = con.execute(
        """SELECT count(*) FROM merged
           WHERE urn_normattiva <> '' AND NOT regexp_matches(id, '^[0-9]{2}G')"""
    ).fetchone()[0]
    assert sporchi == 0


def test_i_pendenti_escludono_chi_ha_gia_l_urn(con, tmp_path):
    righe = [
        _riga(id="26G00151"),
        _riga(id="26G00152", urn_normattiva="urn:nir:stato:legge:2026-07-16;129"),
    ]
    merge(con, tmp_path / "store.parquet", righe, rebuild=False)
    assert [r[0] for r in urn_pendenti(con, "merged")] == ["26G00151"]
