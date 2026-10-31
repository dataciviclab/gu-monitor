#!/usr/bin/env python3
"""Test del parser della Gazzetta.

Coprono le regressioni viste sul dataset reale:
- i decreti-legge finivano in `tipo_atto = LEGGE` perché "LEGGE" era il primo
  pattern e matchava dentro "DECRETO-LEGGE";
- ogni atto produceva due record (estremi + oggetto) e la dedup teneva il
  primo, quindi il titolo era "DECRETO 5 agosto 2026" invece dell'oggetto;
- la serie UE (S2) non ha link per atto: si punta alla pagina della gazzetta.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

from gu_source import (  # noqa: E402
    _pubblicazioni_da_html,
    _pulisci_testo,
    atti_da_html,
    classify_tipo,
)

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

PAGINA_S2 = """
<html><body>
<span class="risultato">
  <a href="/do/gazzetta/unione_europea/3/pdfPaginato?numPagina=3">
    <span class="data">DECISIONE 3 marzo 2026 , n. 1</span>
  </a>
  <a href="/do/gazzetta/unione_europea/3/pdfPaginato?numPagina=3">
    Decisione n. 1/2026 del comitato per l'agevolazione degli investimenti (26CE2527)
    <span class="pagina">Pag. 1</span>
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

    def test_decisione_pesc_prima_di_decisione(self):
        assert classify_tipo("DECISIONE PESC 12 maggio 2026, n. 3") == "DECISIONE PESC"

    def test_direttiva(self):
        assert classify_tipo("DIRETTIVA (UE) 2024/123") == "DIRETTIVA"

    def test_comunicato(self):
        assert classify_tipo("COMUNICATO") == "COMUNICATO"

    def test_vuoto_e_altro(self):
        assert classify_tipo("") == "ALTRO"

    def test_non_matcha_dentro_parole(self):
        assert classify_tipo("LEGGI ED ALTRI ATTI NORMATIVI") == "ALTRO"


class TestPuliziaTesto:
    def test_toglie_codice_e_pagina(self):
        assert (
            _pulisci_testo("Regolamento in attuazione dell'articolo 12. (26G00215) Pag. 1")
            == "Regolamento in attuazione dell'articolo 12."
        )

    def test_toglie_solo_pagina(self):
        assert _pulisci_testo("Avviso di cessione di crediti Pag. 2") == "Avviso di cessione di crediti"

    def test_non_tocca_parentesi_descrittive(self):
        assert _pulisci_testo("Decreto (testo coordinato)") == "Decreto (testo coordinato)"


class TestElenco:
    def test_estrae_data_e_numero_senza_duplicati(self):
        html = """
        <a href="/gazzetta/serie_generale/caricaDettaglio?dataPubblicazioneGazzetta=2026-01-02&numeroGazzetta=1">x</a>
        <a href="/gazzetta/serie_generale/caricaDettaglio?dataPubblicazioneGazzetta=2026-01-02&numeroGazzetta=1">x</a>
        <a href="/gazzetta/serie_generale/caricaDettaglio?dataPubblicazioneGazzetta=2026-01-03&numeroGazzetta=2">y</a>
        <a href="/altro/link">z</a>
        """
        assert _pubblicazioni_da_html(html) == [
            {"data": "2026-01-02", "numero": "1"},
            {"data": "2026-01-03", "numero": "2"},
        ]

    def test_formato_30gg_senza_trattini(self):
        html = '<a href="/x?dataPubblicazioneGazzetta=20261029&numeroGazzetta=252">x</a>'
        assert _pubblicazioni_da_html(html) == [{"data": "2026-10-29", "numero": "252"}]


class TestAtti:
    def _parse(self, html: str, serie: str = "SG") -> list[dict]:
        return atti_da_html(html, serie, "252", "2026-10-29")

    def test_un_solo_atto_per_codice(self):
        acts = self._parse(PAGINA_SG)
        assert len(acts) == 1
        assert acts[0]["id"] == "26G00215"

    def test_titolo_e_l_oggetto_non_gli_estremi(self):
        assert self._parse(PAGINA_SG)[0]["titolo"].startswith("Regolamento in attuazione")

    def test_estremi_conservati(self):
        assert self._parse(PAGINA_SG)[0]["estremi"] == "DECRETO 5 agosto 2026, n. 198"

    def test_tipo_classificato_sugli_estremi(self):
        assert self._parse(PAGINA_SG)[0]["tipo_atto"] == "DECRETO"

    def test_ente_da_emettitore(self):
        assert self._parse(PAGINA_SG)[0]["ente"] == "MINISTERO DELLA SALUTE"

    def test_decreto_legge_classificato(self):
        acts = self._parse(PAGINA_DL)
        assert acts[0]["tipo_atto"] == "DECRETO-LEGGE"
        assert acts[0]["titolo"].startswith("Misure urgenti")

    def test_p2_soggetto_negli_estremi(self):
        acts = self._parse(PAGINA_P2, serie="P2")
        assert acts[0]["estremi"] == "RIALTO S.P.A."
        assert acts[0]["titolo"] == "Convocazione di assemblea"

    def test_s2_codice_dal_testo_e_link_alla_gazzetta(self):
        acts = self._parse(PAGINA_S2, serie="S2")
        assert acts[0]["id"] == "26CE2527"
        assert acts[0]["ente"] == "UNIONE EUROPEA"
        assert "/gazzetta/unione_europea/caricaDettaglio?" in acts[0]["link"]

    def test_link_atto_non_canonico(self):
        """Il flag di navigazione lo toglie to_parquet, non il parser."""
        assert "codiceRedazionale=26G00215" in self._parse(PAGINA_SG)[0]["link"]
