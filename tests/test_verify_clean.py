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
    minimo: un invariante che vale anche il 2 gennaio."""

    @pytest.fixture
    def marts(self, tmp_path):
        con = duckdb.connect()

        def vol(atti: int) -> str:
            return (
                "select 'SG' as serie, DATE '2026-01-02' as data_pubblicazione, "
                f"{atti} as atti, 1 as enti"
            )

        for nome in ("mart_atti_per_serie_giorno", "mart_atti_per_tipo"):
            con.execute(
                f"copy ({vol(3)} union all {vol(4)}) to "
                f"'{tmp_path}/{nome}.parquet' (format parquet)"
            )
        con.execute(f"copy ({vol(3)}) to '{tmp_path}/mart_normativi_urn.parquet' (format parquet)")
        return con, tmp_path

    def test_volume_coerente(self, marts):
        con, d = marts
        assert controlla_mart(con, d, 2026, righe=7, righe_urn=1) == []

    def test_volume_incoerente(self, marts):
        con, d = marts
        errori = controlla_mart(con, d, 2026, righe=5, righe_urn=9)
        assert any("somma atti 7, clean 5" in e for e in errori)
        assert any("9 righe" in e or "atti con URN 9" in e for e in errori)

    def test_mart_assente(self, marts):
        con, d = marts
        (d / "mart_atti_per_tipo.parquet").unlink()
        errori = controlla_mart(con, d, 2026, righe=7, righe_urn=1)
        assert any("mart assente" in e for e in errori)
