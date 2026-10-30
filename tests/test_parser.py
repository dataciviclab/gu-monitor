#!/usr/bin/env python3
"""Test del parser 30gg e della classificazione tipo atto.

Coprono due regressioni viste sul dataset reale:
- i decreti-legge finivano in `tipo_atto = LEGGE` perché "LEGGE" era il
  primo pattern e matchava dentro "DECRETO-LEGGE";
- ogni atto produceva due record (estremi + oggetto) e la dedup teneva il
  primo, quindi il titolo era "DECRETO 5 agosto 2026" invece dell'oggetto.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

from scrape_30gg import DetailParser, classify_tipo  # noqa: E402

PAGINA_SG = """
<html><body>
<span class="rubrica"> LEGGI ED ALTRI ATTI NORMATIVI</span>
<span class="emettitore">MINISTERO DELLA SALUTE</span>
<span class="risultato">
  <a href="/atto/serie_generale/caricaDettaglioAtto/originario?atto.dataPubblicazioneGazzetta=2026-10-29&amp;atto.codiceRedazionale=26G00215&amp;elenco30giorni=true">
    <span class="data">DECRETO 5 agosto 2026, n. 198</span>
  </a>
  <a href="/atto/serie_generale/caricaDettaglioAtto/originario?atto.dataPubblicazioneGazzetta=2026-10-29&amp;atto.codiceRedazionale=26G00215&amp;elenco30giorni=true">
    Regolamento in attuazione dell'articolo 12 della legge 10 novembre 2021, n. 175,
    recante disposizioni per la cura delle malattie rare.
    <span class="pagina">Pag. 1</span>
  </a>
</span>
</body></html>
"""

PAGINA_DL = """
<html><body>
<span class="emettitore">PRESIDENZA DEL CONSIGLIO DEI MINISTRI</span>
<span class="risultato">
  <a href="/atto/serie_generale/caricaDettaglioAtto/originario?atto.codiceRedazionale=26G00151">
    <span class="data">DECRETO-LEGGE 23 luglio 2026, n. 127</span>
  </a>
  <a href="/atto/serie_generale/caricaDettaglioAtto/originario?atto.codiceRedazionale=26G00151">
    Misure urgenti e indifferibili per lo svolgimento dei procedimenti civili e penali.
    <span class="pagina">Pag. 3</span>
  </a>
</span>
</body></html>
"""


PAGINA_P2 = """
<html><body>
<span class="rubrica"> Annunzi commerciali</span>
<span class="emettitore">Convocazioni di assemblea</span>
<span class="risultato">
  <a href="/atto/parte_seconda/caricaDettaglioAtto/originario?atto.codiceRedazionale=TX26AAA10016">
    <span class="data">RIALTO S.P.A.</span>
  </a>
  <a href="/atto/parte_seconda/caricaDettaglioAtto/originario?atto.codiceRedazionale=TX26AAA10016">
    Convocazione di assemblea
    <span class="pagina">Pag. 2</span>
  </a>
</span>
</body></html>
"""


class TestClassifyTipo:
    def test_decreto_legge_non_diventa_legge(self):
        assert classify_tipo("DECRETO-LEGGE 23 luglio 2026, n. 127") == "DECRETO-LEGGE"

    def test_legge_semplice(self):
        assert classify_tipo("LEGGE 7 agosto 2026, n. 152") == "LEGGE"

    def test_decreto_semplice(self):
        assert classify_tipo("DECRETO 5 agosto 2026, n. 198") == "DECRETO"

    def test_testo_coordinato_vince_sul_decreto_legge(self):
        assert (
            classify_tipo("TESTO COORDINATO DEL DECRETO-LEGGE 19 maggio 2020, n. 34")
            == "TESTO COORDINATO"
        )

    def test_comunicato(self):
        assert classify_tipo("COMUNICATO") == "COMUNICATO"

    def test_vuoto_e_altro(self):
        assert classify_tipo("") == "ALTRO"

    def test_non_matcha_dentro_parole(self):
        # "LEGGE" non deve matchare "LEGGI" né "ALLEGGE"
        assert classify_tipo("LEGGI ED ALTRI ATTI NORMATIVI") == "ALTRO"


class TestPuliziaTesto:
    def test_toglie_codice_e_pagina(self):
        from scrape_30gg import _pulisci_testo

        assert (
            _pulisci_testo("Regolamento in attuazione dell'articolo 12. (26G00215) Pag. 1")
            == "Regolamento in attuazione dell'articolo 12."
        )

    def test_toglie_solo_pagina(self):
        from scrape_30gg import _pulisci_testo

        assert _pulisci_testo("Avviso di cessione di crediti Pag. 2") == "Avviso di cessione di crediti"

    def test_non_tocca_parentesi_descrittive(self):
        from scrape_30gg import _pulisci_testo

        assert _pulisci_testo("Decreto (testo coordinato)") == "Decreto (testo coordinato)"


class TestDetailParser:
    def _parse(self, html: str, serie: str = "SG") -> list[dict]:
        parser = DetailParser(serie=serie)
        parser.feed(html)
        return parser.acts

    def test_un_solo_atto_per_codice(self):
        acts = self._parse(PAGINA_SG)
        assert len(acts) == 1
        assert acts[0]["codice"] == "26G00215"

    def test_titolo_e_l_oggetto_non_gli_estremi(self):
        acts = self._parse(PAGINA_SG)
        assert acts[0]["titolo"].startswith("Regolamento in attuazione")

    def test_estremi_conservati(self):
        acts = self._parse(PAGINA_SG)
        assert acts[0]["estremi"] == "DECRETO 5 agosto 2026, n. 198"

    def test_tipo_classificato_sugli_estremi(self):
        acts = self._parse(PAGINA_SG)
        assert acts[0]["tipo_atto"] == "DECRETO"

    def test_ente_da_emettitore(self):
        acts = self._parse(PAGINA_SG)
        assert acts[0]["ente"] == "MINISTERO DELLA SALUTE"

    def test_decreto_legge_classificato(self):
        acts = self._parse(PAGINA_DL)
        assert len(acts) == 1
        assert acts[0]["tipo_atto"] == "DECRETO-LEGGE"
        assert acts[0]["titolo"].startswith("Misure urgenti")

    def test_ente_non_sovrascritto_da_testo_maiuscolo(self):
        """In P2 il testo maiuscolo dentro l'anchor è il soggetto, non l'ente."""
        acts = self._parse(PAGINA_P2, serie="P2")
        assert acts[0]["ente"] == "Convocazioni di assemblea"
        assert acts[0]["estremi"] == "RIALTO S.P.A."
        assert acts[0]["titolo"] == "Convocazione di assemblea"
