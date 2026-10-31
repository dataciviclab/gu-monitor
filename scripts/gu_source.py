#!/usr/bin/env python3
"""GU Monitor — accesso alla fonte Gazzetta Ufficiale.

Unico punto di verità per: URL e slug delle serie, fetch HTTP, parsing delle
pagine di elenco (archivio per anno e finestra 30 giorni) e delle pagine di
dettaglio.

Non contiene orchestrazione: la cattura incrementale e il backfill stanno in
collect.py.
"""

import random
import re
import time
from urllib.request import Request, urlopen

from bs4 import BeautifulSoup

BASE = "https://www.gazzettaufficiale.it"

# serie -> slug usato da /30giorni/, /ricercaArchivioCompleto/ e /gazzetta/
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

# I valori sono contratto pubblico (colonna tipo_atto): aggiungerne uno nuovo
# è un cambio di schema. L'ordine è per specificità decrescente.
TIPI_ATTO = (
    "TESTO COORDINATO",
    "DECRETO DEL PRESIDENTE DELLA REPUBBLICA",
    "DECRETO DEL PRESIDENTE DEL CONSIGLIO",
    "DECRETO LEGISLATIVO",
    "DECRETO-LEGGE",
    "DECISIONE PESC",
    "DECISIONE",
    "DIRETTIVA",
    "RETTIFICA",
    "DECRETO",
    "LEGGE",
    "DETERMINA",
    "COMUNICATO",
    "ORDINANZA",
    "REGOLAMENTO",
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
)


def _match_token(text: str, phrase: str) -> bool:
    """True se `phrase` compare come token intero (no lettere/trattini ai lati)."""
    return re.search(rf"(?<![A-Z\-]){re.escape(phrase)}(?![A-Z])", text) is not None


def classify_tipo(testo: str) -> str:
    """Classifica il tipo atto dagli estremi ("DECRETO-LEGGE 23 luglio 2026").

    Match a token intero: "LEGGE" non intercetta "DECRETO-LEGGE" né "LEGGI".
    """
    upper = " ".join((testo or "").upper().split())
    for tipo in TIPI_ATTO:
        if _match_token(upper, tipo):
            return tipo
    return "ALTRO"


def _testo(el) -> str:
    return " ".join(el.get_text(" ").split()) if el else ""


def _pulisci_testo(testo: str) -> str:
    """Toglie la coda tecnica della pagina: "(26G00215) Pag. 1"."""
    pulito = " ".join((testo or "").split())
    pulito = re.sub(r"\s*\(\s*[0-9A-Z]{6,20}\s*\)\s*(Pag\.\s*\d+)?\s*$", "", pulito)
    pulito = re.sub(r"\s*Pag\.\s*\d+\s*$", "", pulito)
    return pulito.strip(" -—")


# ── Fetch ──────────────────────────────────────────────────────────────


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
                wait = random.uniform(0, 2**attempt)
                print(f"    Retry {attempt}/{retries} tra {wait:.1f}s ({e})", flush=True)
                time.sleep(wait)
    raise last_err


# ── Pagine di elenco ───────────────────────────────────────────────────


def _pubblicazioni_da_html(html: str) -> list[dict]:
    """Estrae (data, numero) delle gazzette da una pagina di elenco.

    Vale per l'archivio per anno (`dataPubblicazioneGazzetta=2026-10-29`) e per
    la finestra 30 giorni (`20261029`). Dedup per (data, numero).
    """
    soup = BeautifulSoup(html, "lxml")
    visti: set[tuple[str, str]] = set()
    pubs: list[dict] = []
    for a in soup.find_all("a", href=True):
        m = re.search(
            r"dataPubblicazioneGazzetta=([0-9]{4})-?([0-9]{2})-?([0-9]{2})"
            r"&numeroGazzetta=([0-9]+)",
            a["href"],
        )
        if not m:
            continue
        chiave = (f"{m.group(1)}-{m.group(2)}-{m.group(3)}", m.group(4))
        if chiave in visti:
            continue
        visti.add(chiave)
        pubs.append({"data": chiave[0], "numero": chiave[1]})
    return pubs


def elenco_30gg(serie: str) -> list[dict]:
    """Pubblicazioni degli ultimi 30 giorni per una serie."""
    return _pubblicazioni_da_html(fetch(f"{BASE}/30giorni/{SERIE_SLUGS[serie]}"))


def elenco_archivio(serie: str, anno: int) -> list[dict]:
    """Tutte le pubblicazioni di una serie in un anno (archivio completo)."""
    slug = SERIE_SLUGS[serie]
    return _pubblicazioni_da_html(
        fetch(f"{BASE}/ricercaArchivioCompleto/{slug}/{anno}?anno={anno}")
    )


def url_dettaglio(serie: str, pub: dict) -> str:
    return (
        f"{BASE}/gazzetta/{SERIE_SLUGS[serie]}/caricaDettaglio"
        f"?dataPubblicazioneGazzetta={pub['data']}&numeroGazzetta={pub['numero']}"
    )


# ── Pagine di dettaglio ────────────────────────────────────────────────


def _codice_atto(blocco) -> str | None:
    """Codice redazionale: dal link (SG/S1/S3/S4/S5/P2) o dal testo (S2)."""
    for a in blocco.find_all("a", href=True):
        m = re.search(r"codiceRedazionale=([^&]+)", a["href"])
        if m:
            return m.group(1)
    m = re.search(r"\((\d{2}[A-Z]{2}\d{3,5})\)", blocco.get_text(" "))
    return m.group(1) if m else None


def atti_da_html(html: str, serie: str, numero: str, data: str) -> list[dict]:
    """Parsa una pagina di dettaglio: un record per atto."""
    soup = BeautifulSoup(html, "lxml")
    atti: list[dict] = []

    for blocco in soup.select("span.risultato"):
        codice = _codice_atto(blocco)
        if not codice:
            continue

        anchors = blocco.find_all("a")
        estremi = _testo(blocco.select_one("span.data"))
        # Il primo anchor porta gli estremi, l'ultimo l'oggetto.
        oggetto = _pulisci_testo(_testo(anchors[-1])) if anchors else ""

        # `sezione` è la rubrica della pagina (Annunzi commerciali, Sentenze…):
        # un titolo di sezione, NON un ente. `ente` resta valorizzato solo dove
        # il campo della fonte è davvero l'emittente.
        rubrica = _testo(blocco.find_previous("span", class_="rubrica"))
        emettitore = _testo(blocco.find_previous("span", class_="emettitore"))
        if serie in ("P2", "S5"):
            # Qui `emettitore` è la rubrica di secondo livello ("Eredita'",
            # "Aste immobiliari"): è una sezione, non chi pubblica.
            ente, sezione = None, emettitore or rubrica
        elif serie == "S1":
            # La Corte non ha emettitore nel markup: l'emittente è noto.
            ente, sezione = "CORTE COSTITUZIONALE", rubrica
        elif serie == "S2":
            ente, sezione = "UNIONE EUROPEA", rubrica
        else:
            ente, sezione = emettitore or None, rubrica

        href = anchors[0]["href"] if anchors else ""
        link = (
            BASE + href
            if href.startswith("/") and "caricaDettaglioAtto" in href
            else url_dettaglio(serie, {"data": data, "numero": numero})
        )

        atti.append({
            "id": codice,
            "serie": serie,
            "gazzetta_numero": numero,
            "data_pubblicazione": data,
            "titolo": oggetto or estremi,
            "estremi": estremi,
            "tipo_atto": classify_tipo(estremi),
            "ente": ente or None,
            "sezione": sezione or None,
            "link": link,
        })

    return atti


def fetch_detail(serie: str, pub: dict) -> list[dict]:
    """Scarica e parsa la pagina di dettaglio di una pubblicazione."""
    return atti_da_html(fetch(url_dettaglio(serie, pub)), serie, pub["numero"], pub["data"])
