#!/usr/bin/env python3
"""Test delle regole di pubblicazione (freschezza e rollover di gennaio).

La guardia deve restare accesa (se il dataset smette di crescere, lo dice) senza
spegnere la pubblicazione quando il nuovo anno non ha ancora atti: è il caso
che il gate dei 1.000 atti trasformava in un blocco di ~10 giorni.
"""

import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

from verify_clean import (  # noqa: E402
    MIN_RIGHE,
    anno_da_partizione,
    anno_da_richiedere,
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
