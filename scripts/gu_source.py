#!/usr/bin/env python3
"""GU Monitor — accesso alla fonte Gazzetta Ufficiale.

Unico punto di verità per: URL e slug delle serie, fetch HTTP, parsing delle
pagine di elenco (archivio per anno e finestra 30 giorni) e parsing delle
pagine di dettaglio (un atto → record).

Non contiene orchestrazione: la cattura incrementale sta in capture.py, la
ricostruzione storica in rebuild_archivio.py.
"""

import random
import re
import time
from html.parser import HTMLParser
from urllib.request import Request, urlopen

BASE = "https://www.gazzettaufficiale.it"

# serie -> slug usato sia da /30giorni/ sia da /ricercaArchivioCompleto/
# sia da /gazzetta/{slug}/caricaDettaglio
SERIE_SLUGS = {
    "SG": "serie_generale",
    "S1": "corte_costituzionale",
    "S2": "unione_europea",
    "S3": "regioni",
    "S4": "concorsi",
    "S5": "contratti",
    "P2": "parte_seconda",
}

SERIE = tuple(SERIE_SLUGS)

# ── Classificazione tipo atto ──────────────────────────────────────────

# Ordine = specificità decrescente. Il token match ignora i confini a
# trattino, così "LEGGE" non intercetta "DECRETO-LEGGE" (bug storico che
# classificava tutti i decreti-legge come leggi).
TIPI_ATTO = [
    "TESTO COORDINATO",
    "DECRETO-LEGGE",
    "DECRETO",
    "LEGGE",
    "DETERMINA",
    "COMUNICATO",
    "ORDINANZA",
    "REGOLAMENTO",
    "DECISIONE",
    "RETTIFICA",
    "AVVISO",
    "GRADUATORIA",
    "CONCORSO",
    "AUTORIZZAZIONE",
    "LIQUIDAZIONE",
    "MODIFICA",
    "REVOCA",
    "VOLTURA",
    "SOSTITUZIONE",
    "RINUNCIA",
    "CONFERIMENTO",
    "CONVOCAZIONE",
    "NOMINA",
    "ISCRIZIONE",
    "NOTIFICA",
    "SENTENZA",
    "DIARIO",
    "ANNULLAMENTO",
]


def _match_token(text: str, phrase: str) -> bool:
    """True se `phrase` compare come token intero (no lettere/trattini ai lati)."""
    return re.search(rf"(?<![A-Z\-]){re.escape(phrase)}(?![A-Z])", text) is not None


def classify_tipo(testo: str) -> str:
    """Classifica il tipo atto dagli estremi ("DECRETO-LEGGE 23 luglio 2026")."""
    upper = " ".join((testo or "").upper().split())
    for tipo in TIPI_ATTO:
        if _match_token(upper, tipo):
            return tipo
    return "ALTRO"


def _pulisci_testo(testo: str) -> str:
    """Normalizza il testo dell'atto togliendo la coda tecnica della pagina.

    Es. "Regolamento ... (26G00215) Pag. 1" → "Regolamento ...".
    """
    pulito = " ".join((testo or "").split())
    pulito = re.sub(r"\s*\(\s*[0-9A-Z]{6,20}\s*\)\s*(Pag\.\s*\d+)?\s*$", "", pulito)
    pulito = re.sub(r"\s*Pag\.\s*\d+\s*$", "", pulito)
    return pulito.strip(" -—")


# ── Parsers ────────────────────────────────────────────────────────────

class ListPubblicazioniParser(HTMLParser):
    """Estrae (data, numero) delle gazzette da una pagina di elenco.

    Vale per entrambi i formati della fonte: archivio per anno
    (`dataPubblicazioneGazzetta=2026-10-29`) e finestra 30 giorni
    (`dataPubblicazioneGazzetta=20261029`). Dedup per (data, numero).
    """

    def __init__(self):
        super().__init__()
        self.pubs: list[dict] = []
        self._visti: set[tuple[str, str]] = set()

    def handle_starttag(self, tag, attrs):
        href = dict(attrs).get("href", "")
        m = re.search(
            r"dataPubblicazioneGazzetta=([0-9]{4})-?([0-9]{2})-?([0-9]{2})"
            r"&numeroGazzetta=([0-9]+)",
            href,
        )
        if not m:
            return
        data = f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
        numero = m.group(4)
        key = (data, numero)
        if key in self._visti:
            return
        self._visti.add(key)
        self.pubs.append({"data": data, "numero": numero})


class DetailParser(HTMLParser):
    """Parse detail page → extract acts."""

    def __init__(self, serie: str = "SG"):
        super().__init__()
        self.serie = serie
        self.acts = []
        self._current_ente = None
        self._in_link = False
        self._in_data_span = False
        self._in_emettitore = False
        self._emettitore_buf = ""
        self._current_act = {}
        self._buf = ""
        self._section = None  # current section header

    def handle_starttag(self, tag, attrs):
        d = dict(attrs)
        href = d.get("href", "")
        css_class = d.get("class", "")

        # <span class="emettitore"> è l'ente che emana l'atto: fonte
        # strutturata, da preferire all'euristica "testo tutto maiuscolo".
        if tag == "span" and "emettitore" in css_class:
            self._in_emettitore = True
            self._emettitore_buf = ""
            return

        if self.serie == "S2":
            # EU: detect <span class="risultato"> block
            if tag == "span" and "risultato" in css_class:
                self._in_link = True
                self._current_act = {}
                self._buf = ""
            # EU: detect <span class="data"> for tipo+date
            if tag == "span" and "data" in css_class and self._in_link:
                self._in_data_span = True
            # EU: detect section headers <span class="rubrica">
            if tag == "span" and "rubrica" in css_class:
                self._section = True
        else:
            # SG/S3/S4 etc: original logic
            if "caricaDettaglioAtto" in href:
                m = re.search(r"atto\.codiceRedazionale=([^&]+)", href)
                if m:
                    self._in_link = True
                    self._current_act = {"codice": m.group(1), "url": href}
                    self._buf = ""

    def handle_data(self, data):
        text = data.strip()
        if not text:
            return

        if self._in_emettitore:
            self._emettitore_buf += text + " "
            return

        # Section headers
        if hasattr(self, '_section') and self._section:
            self._section = None
            if text.isupper() and len(text) > 5:
                self._current_ente = None  # reset on new section

        if self.serie == "S2" and self._in_link:
            if self._in_data_span:
                self._buf += text + " "
            elif not self._in_data_span:
                # Description text
                self._buf += text + " "
        else:
            # Fallback: solo se l'ente non è già arrivato da <span class="emettitore">.
            # Non sovrascrivere: in P2 il testo maiuscolo dentro l'anchor è il
            # soggetto (società), non l'ente.
            if (self._current_ente is None and text.isupper() and len(text) > 10
                    and not text.startswith("n°")):
                if any(kw in text for kw in ["LEGGI", "DECRETI", "DELIBERE", "ORDINANZE",
                                              "COMUNICATI", "ESTRATTI", "SUPPLEMENTI",
                                              "TESTI COORDINATI", "AVVISI"]):
                    pass
                else:
                    self._current_ente = text

            if self._in_link:
                self._buf += text + " "

    def handle_endtag(self, tag):
        if tag == "span" and self._in_emettitore:
            self._in_emettitore = False
            ente = " ".join(self._emettitore_buf.split())
            if ente:
                self._current_ente = ente
            self._emettitore_buf = ""
            return

        if self.serie == "S2" and tag == "span" and self._in_data_span:
            self._in_data_span = False

        if self.serie == "S2" and self._in_link and tag == "span":
            # End of <span class="risultato">
            pass

        # For EU: try to extract act when we have enough data
        if self.serie == "S2" and self._in_link and self._buf:
            # Check if we have a code pattern (26CE1950)
            code_match = re.search(r"\((\d{2}[A-Z]{2}\d{4,5})\)", self._buf)
            if code_match:
                self._in_link = False
                codice = code_match.group(1)

                # Extract tipo from the data span text
                tipo = "ALTRO"
                for t in ["REGOLAMENTO", "DECISIONE PESC", "DECISIONE", "RETTIFICA",
                          "DIRETTIVA", "COMUNICATO"]:
                    if t in self._buf.upper():
                        tipo = t
                        break

                # Extract description (text before the code)
                desc = self._buf[:code_match.start()].strip()
                # Clean whitespace
                desc = " ".join(desc.split())
                # Remove leading type+date that's in the data span
                desc = re.sub(r"^(REGOLAMENTO|DECISIONE PESC|DECISIONE|RETTIFICA|"
                             r"DIRETTIVA)\s+\d+.*?n\.\s*\d+\s*", "", desc, flags=re.IGNORECASE)
                desc = " ".join(desc.split())  # re-clean after regex

                self._current_act = {
                    "codice": codice,
                    "titolo": desc[:200] if desc else tipo,
                    "tipo_atto": tipo,
                    "ente": "UNIONE EUROPEA",
                }
                self.acts.append(self._current_act)
                self._current_act = {}
                self._buf = ""

        # Original SG/S3/S4 logic
        if self.serie != "S2" and self._in_link and tag == "a":
            self._in_link = False
            if self._current_act.get("codice"):
                self._append_act(
                    self._current_act["codice"], _pulisci_testo(self._buf)
                )

            self._current_act = {}
            self._buf = ""

    def _append_act(self, codice: str, testo: str) -> bool:
        """Aggiunge l'atto o arricchisce quello già visto. True se era un duplicato.

        Ogni atto ha due anchor: il primo con gli estremi ("DECRETO 5 agosto
        2026, n. 198"), il secondo con l'oggetto. `titolo` è l'oggetto; gli
        estremi restano in `estremi` (servono a classificare il tipo e sono
        l'unica descrizione disponibile per le inserzioni P2).
        """
        for existing in self.acts:
            if existing.get("codice") == codice:
                if not existing.get("estremi"):
                    existing["estremi"] = testo
                elif len(testo) > len(existing.get("oggetto", "")):
                    existing["oggetto"] = testo
                existing["titolo"] = existing.get("oggetto") or existing.get("estremi", "")
                if not existing.get("ente") and self._current_ente:
                    existing["ente"] = self._current_ente
                return True

        act = dict(self._current_act)
        act["estremi"] = testo
        act["oggetto"] = ""
        act["titolo"] = testo
        act["tipo_atto"] = classify_tipo(testo)
        act["ente"] = self._current_ente
        self.acts.append(act)
        return False


# ── Fetch helpers ──────────────────────────────────────────────────────

def fetch(url: str, timeout: int = 20, retries: int = 3) -> str:
    last_err = None
    for attempt in range(1, retries + 1):
        try:
            req = Request(url, headers={"User-Agent": "GU-Monitor/0.1"})
            with urlopen(req, timeout=timeout) as resp:
                return resp.read().decode("utf-8", errors="replace")
        except (OSError, TimeoutError) as e:
            last_err = e
            if attempt < retries:
                wait = random.uniform(0, 2 ** attempt)
                print(f"    Retry {attempt}/{retries} tra {wait:.1f}s ({e})", flush=True)
                time.sleep(wait)
    raise last_err


def elenco_30gg(serie: str) -> list[dict]:
    """Pubblicazioni degli ultimi 30 giorni per una serie."""
    parser = ListPubblicazioniParser()
    parser.feed(fetch(f"{BASE}/30giorni/{SERIE_SLUGS[serie]}"))
    return parser.pubs


def elenco_archivio(serie: str, anno: int) -> list[dict]:
    """Tutte le pubblicazioni di una serie in un anno (archivio completo)."""
    slug = SERIE_SLUGS[serie]
    parser = ListPubblicazioniParser()
    parser.feed(fetch(f"{BASE}/ricercaArchivioCompleto/{slug}/{anno}?anno={anno}"))
    return parser.pubs


def url_dettaglio(serie: str, pub: dict) -> str:
    return (
        f"{BASE}/gazzetta/{SERIE_SLUGS[serie]}/caricaDettaglio"
        f"?dataPubblicazioneGazzetta={pub['data']}&numeroGazzetta={pub['numero']}"
    )


def atti_da_html(html: str, serie: str, numero: str, data: str) -> list[dict]:
    """Parsa la pagina di dettaglio di una pubblicazione e restituisce gli atti.

    Unico punto di verità per il formato record: usato sia dal collector
    rolling 30gg sia dalla ricostruzione da archivio.
    """
    parser = DetailParser(serie=serie)
    parser.feed(html)

    acts = []
    for a in parser.acts:
        link = a.get("url", "")
        if link and not link.startswith("http"):
            link = BASE + link
        if not link:
            # La serie UE (S2) elenca gli atti senza link per atto: si punta
            # alla pagina della pubblicazione, che è comunque navigabile.
            link = url_dettaglio(serie, {"data": data, "numero": numero})
        acts.append({
            "id": a["codice"],
            "serie": serie,
            "gazzetta_numero": numero,
            "data_pubblicazione": data,
            "titolo": a.get("titolo", ""),
            "estremi": a.get("estremi", ""),
            "tipo_atto": a.get("tipo_atto", "ALTRO"),
            "ente": a.get("ente"),
            "link": link,
        })

    return acts


def fetch_detail(serie: str, pub: dict) -> list[dict]:
    """Scarica e parsa la pagina di dettaglio di una pubblicazione."""
    html = fetch(url_dettaglio(serie, pub))
    return atti_da_html(html, serie, pub["numero"], pub["data"])
