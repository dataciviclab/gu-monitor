#!/usr/bin/env python3
"""GU Monitor — Scraper archivio 30 giorni.

Scraarpa la pagina 30 giorni per ogni serie, poi il dettaglio di ogni pubblicazione.
Estrae tutti gli atti con: codice, ente, tipo, descrizione, pagina.
"""

import json
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
        self._current_act = {}
        self._buf = ""
        self._section = None  # current section header

    def handle_starttag(self, tag, attrs):
        d = dict(attrs)
        href = d.get("href", "")
        css_class = d.get("class", "")

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
            # Original SG logic
            if text.isupper() and len(text) > 10 and not text.startswith("n°"):
                if any(kw in text for kw in ["LEGGI", "DECRETI", "DELIBERE", "ORDINANZE",
                                              "COMUNICATI", "ESTRATTI", "SUPPLEMENTI",
                                              "TESTI COORDINATI", "AVVISI"]):
                    pass
                else:
                    self._current_ente = text

            if self._in_link:
                self._buf += text + " "

    def handle_endtag(self, tag):
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
                title = self._buf.strip()
                tipo = "ALTRO"
                for t in ["LEGGE", "DECRETO-LEGGE", "DECRETO", "DETERMINA", "COMUNICATO",
                          "ORDINANZA", "REGOLAMENTO", "DECISIONE", "RETTIFICA",
                          "TESTO COORDINATO", "AVVISO", "GRADUATORIA",
                          "AUTORIZZAZIONE", "LIQUIDAZIONE", "MODIFICA", "REVOCA",
                          "VOLTURA", "SOSTITUZIONE", "RINUNCIA", "CONFERIMENTO",
                          "CONVOCAZIONE", "NOMINA", "ISCRIZIONE", "NOTIFICA",
                          "SENTENZA", "DIARIO", "ANNULLAMENTO"]:
                    if t in title.upper():
                        tipo = t
                        break

                self._current_act["titolo"] = title
                self._current_act["tipo_atto"] = tipo
                self._current_act["ente"] = self._current_ente
                self.acts.append(self._current_act)

            self._current_act = {}
            self._buf = ""


# ── Fetch helpers ──────────────────────────────────────────────────────

def fetch(url: str, timeout: int = 20) -> str:
    req = Request(url, headers={"User-Agent": "GU-Monitor/0.1"})
    with urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", errors="replace")


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


def fetch_detail(pub: dict) -> list[dict]:
    """Fetch detail page for a publication, return list of acts."""
    html = fetch(pub["url"])
    parser = DetailParser(serie=pub["serie"])
    parser.feed(html)

    acts = []
    for a in parser.acts:
        link = a.get("url", "")
        if link and not link.startswith("http"):
            link = BASE + link
        acts.append({
            "id": a["codice"],
            "serie": pub["serie"],
            "gazzetta_numero": pub["numero"],
            "data_pubblicazione": pub["data"],
            "titolo": a.get("titolo", ""),
            "tipo_atto": a.get("tipo_atto", "ALTRO"),
            "ente": a.get("ente"),
            "link": link,
        })

    return acts


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

    for serie in SERIE_30GG:
        print(f"\n[{serie}] Fetching lista 30gg...")
        pubs = fetch_30gg_list(serie)
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

    return 0


if __name__ == "__main__":
    sys.exit(main())
