#!/usr/bin/env python3
"""Test della cattura a watermark.

Il watermark sostituisce `processed.json`: la cattura riparte dall'ultima data
presente nell'event log, quindi è idempotente e recupera da sola i buchi.
"""

import sys
from datetime import date
from pathlib import Path

import duckdb

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

from capture import (  # noqa: E402
    anni_da_scandire,
    inizio_finestra,
    seleziona_pubblicazioni,
    watermark,
)


class TestInizioFinestra:
    def test_senza_event_log_usa_il_lookback(self):
        assert inizio_finestra(None, date(2026, 10, 30), overlap=3, lookback=30) == date(
            2026, 9, 30
        )

    def test_con_watermark_torna_indietro_dell_overlap(self):
        assert inizio_finestra(date(2026, 10, 29), date(2026, 10, 30), overlap=3) == date(
            2026, 10, 26
        )

    def test_watermark_vecchio_apre_una_finestra_lunga(self):
        """Dopo un fermo di 40 giorni la finestra copre tutto il buco."""
        da = inizio_finestra(date(2026, 9, 20), date(2026, 10, 30), overlap=3)
        assert (date(2026, 10, 30) - da).days == 43


class TestAnni:
    def test_anno_singolo(self):
        assert anni_da_scandire(date(2026, 1, 2), date(2026, 10, 30)) == [2026]

    def test_a_cavallo_di_capodanno(self):
        assert anni_da_scandire(date(2026, 12, 30), date(2027, 1, 2)) == [2026, 2027]


class TestSelezione:
    def test_filtra_per_data(self):
        pubs = [
            {"data": "2026-10-01", "numero": "1"},
            {"data": "2026-10-28", "numero": "2"},
        ]
        assert seleziona_pubblicazioni(pubs, date(2026, 10, 20)) == [
            {"data": "2026-10-28", "numero": "2"}
        ]

    def test_dedup_per_data_e_numero(self):
        """Archivio e lista 30gg possono restituire la stessa gazzetta."""
        pubs = [
            {"data": "2026-10-29", "numero": "252"},
            {"data": "2026-10-29", "numero": "252"},
        ]
        assert len(seleziona_pubblicazioni(pubs, date(2026, 10, 1))) == 1


class TestWatermark:
    def test_store_assente(self, tmp_path):
        assert watermark(tmp_path / "manca.parquet") is None

    def test_store_vuoto(self, tmp_path):
        store = tmp_path / "vuoto.parquet"
        con = duckdb.connect()
        con.execute("CREATE TABLE t (data_pubblicazione VARCHAR)")
        con.execute(f"COPY t TO '{store}' (FORMAT PARQUET)")
        con.close()
        assert watermark(store) is None

    def test_legge_la_data_massima(self, tmp_path):
        store = tmp_path / "store.parquet"
        con = duckdb.connect()
        con.execute("CREATE TABLE t (data_pubblicazione VARCHAR)")
        con.execute(
            "INSERT INTO t VALUES ('2026-10-01'), ('2026-10-29'), ('2026-03-04')"
        )
        con.execute(f"COPY t TO '{store}' (FORMAT PARQUET)")
        con.close()
        assert watermark(store) == date(2026, 10, 29)
