#!/usr/bin/env python3
"""Test delle regole di pubblicazione (freschezza e rollover di gennaio).

La guardia deve restare accesa (se il dataset smette di crescere, lo dice) senza
spegnere la pubblicazione quando il nuovo anno non ha ancora atti: è il caso
che il gate dei 1.000 atti trasformava in un blocco di ~10 giorni.
"""

import sys
from datetime import date
from pathlib import Path

import duckdb
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

from verify_clean import (  # noqa: E402
    MIN_RIGHE,
    anno_da_partizione,
    anno_da_richiedere,
    controlla_mart,
    errore_partizione_mancante,
    minimo_righe,
)


class TestRollover:
    """1° gennaio: lo store non ha ancora atti del nuovo anno."""

    def test_store_fermo_all_anno_prima_non_chiede_la_partizione(self):
        assert anno_da_richiedere(date(2026, 12, 31), date(2027, 1, 2)) is None
        assert errore_partizione_mancante([2025, 2026], date(2026, 12, 31), date(2027, 1, 2)) is None

    def test_primo_atto_dell_anno_nuovo_chiede_la_partizione(self):
        assert anno_da_richiedere(date(2027, 1, 2), date(2027, 1, 2)) == 2027
        errore = errore_partizione_mancante([2025, 2026], date(2027, 1, 2), date(2027, 1, 2))
        assert errore is not None
        assert "2027" in errore and "years" in errore

    def test_store_assente_non_inventa_un_errore(self):
        assert anno_da_richiedere(None, date(2027, 1, 2)) is None

    def test_partizione_dell_anno_presente_non_e_un_errore(self):
        assert errore_partizione_mancante([2025, 2026], date(2026, 11, 21), date(2026, 11, 24)) is None

    def test_partizione_dell_anno_vecchia_resta_un_errore(self):
        errore = errore_partizione_mancante([2024, 2025], date(2026, 11, 21), date(2026, 11, 24))
        assert errore is not None and "2026" in errore


class TestMinimoRighe:
    """Un anno chiuso è corposo; l'anno aperto può avere poche decine di atti."""

    def test_anno_chiuso(self):
        assert minimo_righe(2025, date(2026, 1, 2)) == MIN_RIGHE

    def test_anno_aperto(self):
        assert minimo_righe(2026, date(2026, 1, 2)) == 1
        assert minimo_righe(2026, date(2026, 11, 24)) == 1


class TestPartizione:
    def test_anno_dalla_directory(self):
        f = Path("out/data/clean/gu_atti/2024/gu_atti_2024_clean.parquet")
        assert anno_da_partizione(f) == 2024

    def test_directory_non_anno(self):
        assert anno_da_partizione(Path("out/data/clean/gu_atti/tmp/x.parquet")) is None


class TestMart:
    """I mart devono essere una derivazione esatta del clean, non un volume
    minimo: volume, gruppi e grana valgono anche il 2 gennaio."""

    @pytest.fixture
    def scenario(self, tmp_path):
        con = duckdb.connect()
        clean = tmp_path / "clean.parquet"
        # 7 atti, un solo gruppo (serie, giorno), 2 tipi, 1 con URN.
        con.execute(
            f"""copy (select * from (values
                ('SG', DATE '2026-01-02', 'LEGGE', 'urn:a'),
                ('SG', DATE '2026-01-02', 'LEGGE', ''),
                ('SG', DATE '2026-01-02', 'LEGGE', ''),
                ('SG', DATE '2026-01-02', 'LEGGE', ''),
                ('SG', DATE '2026-01-02', 'DECRETO', ''),
                ('SG', DATE '2026-01-02', 'DECRETO', ''),
                ('SG', DATE '2026-01-02', 'DECRETO', '')
            ) t(serie, data_pubblicazione, tipo_atto, urn_normattiva))
            to '{clean}' (format parquet)"""
        )
        con.execute(
            f"""copy (select 'SG' as serie, DATE '2026-01-02' as data_pubblicazione,
                      7 as atti, 1 as enti) to
                '{tmp_path}/mart_atti_per_serie_giorno.parquet' (format parquet)"""
        )
        con.execute(
            f"""copy (select * from (values ('LEGGE', 4, 1, 1), ('DECRETO', 3, 1, 1))
                      t(tipo_atto, atti, serie, enti)) to
                '{tmp_path}/mart_atti_per_tipo.parquet' (format parquet)"""
        )
        con.execute(
            f"""copy (select 'urn:a' as urn_normattiva) to
                '{tmp_path}/mart_normativi_urn.parquet' (format parquet)"""
        )
        return con, tmp_path, clean

    def test_derivazione_esatta(self, scenario):
        con, d, clean = scenario
        assert controlla_mart(con, clean, d, 2026, righe=7, righe_urn=1) == []

    def test_volume_incoerente(self, scenario):
        con, d, clean = scenario
        errori = controlla_mart(con, clean, d, 2026, righe=5, righe_urn=9)
        assert any("somma atti 7, clean 5" in e for e in errori)
        assert any("atti con URN 9" in e for e in errori)

    def test_gruppi_collassati(self, scenario):
        """Un GROUP BY che perde `data_pubblicazione` tiene la somma e dimezza
        le righe: è il caso che i floor vecchi coprivano e la somma no."""
        con, d, clean = scenario
        con.execute(
            f"""copy (select * from (values
                ('SG', DATE '2026-01-02', 'LEGGE', 'urn:a'),
                ('SG', DATE '2026-01-03', 'LEGGE', ''),
                ('SG', DATE '2026-01-03', 'LEGGE', ''),
                ('SG', DATE '2026-01-03', 'LEGGE', ''),
                ('SG', DATE '2026-01-03', 'DECRETO', ''),
                ('SG', DATE '2026-01-03', 'DECRETO', ''),
                ('SG', DATE '2026-01-03', 'DECRETO', '')
            ) t(serie, data_pubblicazione, tipo_atto, urn_normattiva))
            to '{clean}' (format parquet)"""
        )
        errori = controlla_mart(con, clean, d, 2026, righe=7, righe_urn=1)
        assert any("1 righe, 2 gruppi nel clean" in e for e in errori)
        assert not any("somma atti" in e for e in errori)

    def test_mart_assente(self, scenario):
        con, d, clean = scenario
        (d / "mart_atti_per_tipo.parquet").unlink()
        errori = controlla_mart(con, clean, d, 2026, righe=7, righe_urn=1)
        assert any("mart assente" in e for e in errori)
