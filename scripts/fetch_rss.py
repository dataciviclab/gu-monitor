#!/usr/bin/env python3
"""GU Monitor — Fetch e parsing feed RSS della Gazzetta Ufficiale."""

import json
import re
import sys
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import urlopen, Request

FEEDS = {
    "SG": "https://www.gazzettaufficiale.it/rss/SG",
    "S1": "https://www.gazzettaufficiale.it/rss/S1",
    "S2": "https://www.gazzettaufficiale.it/rss/S2",
    "S3": "https://www.gazzettaufficiale.it/rss/S3",
    "S4": "https://www.gazzettaufficiale.it/rss/S4",
    "S5": "https://www.gazzettaufficiale.it/rss/S5",
    "P2": "https://www.gazzettaufficiale.it/rss/P2",
}

NS = {"content": "http://purl.org/rss/1.0/modules/content/"}

ELI_ID_RE = re.compile(r"/eli/id/\d{4}/\d{2}/\d{2}/([^/]+)/")
TIPO_ATTO_RE = re.compile(r"(LEGGE(?:\s+PROVINCIALE)?|DECRETO-LEGGE|DECRETO(?:\s+DEL\s+PRESIDENTE(?:\s+DELLA\s+GIUNTA)?(?:\s+REGIONALE)?)?|"
                           r"DETERMINA|COMUNICATO|ORDINANZA|"
                           r"REGOLAMENTO(?:\s+REGIONALE)?|DECISIONE(?:\s+PESC)?|RETTIFICA|"
                           r"GRADUATORIA|CONCORSO|AVVISO|ANNULLAMENTO|"
                           r"TESTO COORDINATO|DIARIO)")
ENTE_RE = re.compile(r"^(.+?)\s*-\s*(?:DECRETO|DETERMINA|COMUNICATO|ORDINANZA|"
                     r"REGOLAMENTO|DECISIONE|RETTIFICA|GRADUATORIA|CONCORSO|AVVISO|"
                     r"TESTO COORDINATO|DIARIO)", re.IGNORECASE)


@dataclass
class Atto:
    id: str
    serie: str
    titolo: str
    tipo_atto: str
    link: str
    data_pubblicazione: str
    content_snippet: str
    timestamp_fetch: str


def fetch_feed(url: str, timeout: int = 20) -> bytes:
    req = Request(url, headers={"User-Agent": "GU-Monitor/0.1"})
    with urlopen(req, timeout=timeout) as resp:
        return resp.read()


def parse_date_rss(date_str: str) -> str:
    """Parse RSS pubDate → YYYY-MM-DD."""
    try:
        dt = datetime.strptime(date_str.strip(), "%a, %d %b %Y %H:%M:%S %Z")
        return dt.strftime("%Y-%m-%d")
    except ValueError:
        return date_str[:10]


def extract_id(link: str) -> str:
    m = ELI_ID_RE.search(link)
    return m.group(1) if m else link.split("/")[-2]


def classify_tipo(titolo: str) -> str:
    m = TIPO_ATTO_RE.search(titolo.upper().strip())
    return m.group(1).strip() if m else "ALTRO"


def extract_ente(titolo: str) -> str | None:
    m = ENTE_RE.match(titolo)
    return m.group(1).strip() if m else None


def parse_feed(xml_bytes: bytes, serie: str) -> list[Atto]:
    root = ET.fromstring(xml_bytes)
    atti = []
    now = datetime.now(timezone.utc).isoformat()

    for item in root.findall(".//item"):
        title = (item.findtext("title") or "").strip()
        link = (item.findtext("link") or "").strip()
        content = (item.findtext("content:encoded", namespaces=NS) or "").strip()
        pub_date = (item.findtext("pubDate") or "").strip()

        snippet = " ".join(content.split())[:200] if content else ""

        atti.append(Atto(
            id=extract_id(link),
            serie=serie,
            titolo=title,
            tipo_atto=classify_tipo(title),
            link=link,
            data_pubblicazione=parse_date_rss(pub_date),
            content_snippet=snippet,
            timestamp_fetch=now,
        ))

    return atti


def main():
    output_dir = Path(__file__).parent.parent / "data"
    output_dir.mkdir(exist_ok=True)
    output_file = output_dir / "gu_acts.json"

    all_atti = []
    errors = []

    for serie, url in FEEDS.items():
        try:
            xml = fetch_feed(url)
            atti = parse_feed(xml, serie)
            all_atti.extend(atti)
            print(f"  {serie}: {len(atti)} atti")
        except Exception as e:
            errors.append({"serie": serie, "error": str(e)})
            print(f"  {serie}: ERRORE — {e}", file=sys.stderr)

    # Append o sovrascrivi
    existing = []
    if output_file.exists():
        existing = json.loads(output_file.read_text())

    # Deduplica per id + serie
    seen = {(a["id"], a["serie"]) for a in existing}
    new = [asdict(a) for a in all_atti if (a.id, a.serie) not in seen]
    merged = existing + new

    output_file.write_text(json.dumps(merged, indent=2, ensure_ascii=False))

    print(f"\nTotale: {len(all_atti)} atti fetchati, {len(new)} nuovi, {len(merged)} totali")
    if errors:
        print(f"Errori: {errors}")

    return 0 if not errors else 1


if __name__ == "__main__":
    sys.exit(main())
