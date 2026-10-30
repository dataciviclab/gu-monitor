#!/usr/bin/env python3
"""GU Monitor — Scraper archivio 30 giorni.

Scraarpa la pagina 30 giorni per ogni serie, poi il dettaglio di ogni pubblicazione.
Estrae tutti gli atti con: codice, ente, tipo, descrizione, pagina.
"""

import json
import random
import re
import sys
import time
from html.parser import HTMLParser
from pathlib import Path
from urllib.request import Request, urlopen

BASE = "https://www.gazzettaufficiale.it"

SERIE_30GG = {
    "SG": "/30giorni/serie_generale",
    "S1": "/30giorni/corte_costituzionale",
    "S2": "/30giorni/unione_europea",
    "S3": "/30giorni/regioni",
    "S4": "/30giorni/concorsi",
    "S5": "/30giorni/contratti",
    "P2": "/30giorni/parte_seconda",
}

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

class List30ggParser(HTMLParser):
    """Parse 30gg page → extract publication links."""

    def __init__(self):
        super().__init__()
        self.pubs = []
        self._in_link = False
        self._current = {}

    def handle_starttag(self, tag, attrs):
        d = dict(attrs)
        href = d.get("href", "")
        # Match detail page links
        if "caricaDettaglio" in href and "elenco30giorni" in href:
            self._in_link = True
            self._current = {"url": href}
        # Match PDF download links for date/number extraction
        if "downloadPdf" in href and "tipoSupplemento=GU" in href:
            m = re.search(r"dataPubblicazioneGazzetta=(\d+)&numeroGazzetta=(\d+)", href)
            if m:
                self._current["data_raw"] = m.group(1)
                self._current["numero"] = m.group(2)

    def handle_data(self, data):
        text = data.strip()
        if self._in_link and text:
            # "n° 192 del 20-08-2026"
            m = re.match(r"n°\s*(\d+)\s+del\s+(\d{2}-\d{2}-\d{4})", text)
            if m:
                self._current["numero"] = m.group(1)
                self._current["data"] = m.group(2)

    def handle_endtag(self, tag):
        if self._in_link and tag == "a":
            self._in_link = False
            if self._current.get("url"):
                self.pubs.append(self._current)
            self._current = {}


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


def fetch_30gg_list(serie: str) -> list[dict]:
    """Fetch the 30-day archive page for a series, return list of publications."""
    slug = SERIE_30GG.get(serie)
    if not slug:
        return []

    html = fetch(f"{BASE}{slug}")
    parser = List30ggParser()
    parser.feed(html)

    # Deduplicate and clean
    seen = set()
    pubs = []
    for p in parser.pubs:
        url = p["url"]
        if url in seen:
            continue
        seen.add(url)

        # Parse date from text or data_raw
        data_raw = p.get("data_raw", "")
        if data_raw and len(data_raw) == 8:
            data_fmt = f"{data_raw[:4]}-{data_raw[4:6]}-{data_raw[6:8]}"
        else:
            data_fmt = p.get("data", "unknown")

        pubs.append({
            "serie": serie,
            "numero": p.get("numero", "?"),
            "data": data_fmt,
            "url": BASE + url if url.startswith("/") else url,
        })

    return pubs


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


def fetch_detail(pub: dict) -> list[dict]:
    """Fetch detail page for a publication, return list of acts."""
    html = fetch(pub["url"])
    return atti_da_html(html, pub["serie"], pub["numero"], pub["data"])


# ── Main ───────────────────────────────────────────────────────────────

def load_processed(data_dir: Path) -> set[tuple[str, str]]:
    """Load set of (serie, numero) pairs already processed."""
    index_file = data_dir / "processed.json"
    if index_file.exists():
        data = json.loads(index_file.read_text())
        return {(p["serie"], p["numero"]) for p in data}
    return set()


def save_processed(data_dir: Path, processed: set[tuple[str, str]]):
    """Save processed index."""
    index_file = data_dir / "processed.json"
    data = [{"serie": s, "numero": n} for s, n in sorted(processed)]
    index_file.write_text(json.dumps(data, indent=2))


def main():
    data_dir = Path(__file__).parent.parent / "data"
    data_dir.mkdir(exist_ok=True)
    output_file = data_dir / "gu_acts_30gg.json"

    # Load existing acts and processed index
    existing = []
    if output_file.exists():
        existing = json.loads(output_file.read_text())
    seen_ids = {(a["id"], a["serie"]) for a in existing}
    processed = load_processed(data_dir)

    all_new = []
    total_pubs = 0
    skipped = 0
    failures = []

    for serie in SERIE_30GG:
        print(f"\n[{serie}] Fetching lista 30gg...")
        try:
            pubs = fetch_30gg_list(serie)
        except Exception as e:
            print(f"  ERRORE fetching lista: {e}")
            failures.append((serie, "lista", str(e)))
            continue
        print(f"  {len(pubs)} pubblicazioni trovate")

        for i, pub in enumerate(pubs):
            key = (pub["serie"], pub["numero"])

            # Skip if already processed
            if key in processed:
                skipped += 1
                continue

            print(f"  [{i+1}/{len(pubs)}] n°{pub['numero']} del {pub['data']}...", end=" ", flush=True)
            try:
                acts = fetch_detail(pub)
                # Filter out already seen
                new_acts = [a for a in acts if (a["id"], a["serie"]) not in seen_ids]
                for a in new_acts:
                    seen_ids.add((a["id"], a["serie"]))
                all_new.extend(new_acts)
                processed.add(key)
                print(f"{len(new_acts)} atti")
                time.sleep(0.5)  # Be polite
            except Exception as e:
                print(f"ERRORE: {e}")
                failures.append((serie, pub.get("numero", "?"), str(e)))

        total_pubs += len(pubs)

    # Merge and save
    merged = existing + all_new
    output_file.write_text(json.dumps(merged, indent=2, ensure_ascii=False))
    save_processed(data_dir, processed)

    print(f"\n{'=' * 50}")
    print(f"Pubblicazioni scansionate: {total_pubs}")
    print(f"Skipped (già processate): {skipped}")
    print(f"Atti nuovi: {len(all_new)}")
    print(f"Atti totali: {len(merged)}")
    print(f"Gazzette processate: {len(processed)}")
    print(f"Salvato in: {output_file}")

    if failures:
        print(f"\n{len(failures)} errori durante lo scraping:")
        for serie, pub, err in failures:
            print(f"  [{serie}] {pub}: {err}")
        # Un errore parziale non deve buttare via gli atti raccolti: le
        # pubblicazioni fallite restano fuori da processed.json e vengono
        # ritentate al run successivo. Si esce non-zero solo se non c'è
        # nulla da salvare.
        if not merged:
            return 1
        print("  Run parziale: gli atti raccolti vengono salvati comunque.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
