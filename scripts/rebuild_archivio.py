#!/usr/bin/env python3
"""GU Monitor — Ricostruzione da archivio per anno.

Il collector giornaliero legge solo gli ultimi 30 giorni. L'archivio della
Gazzetta espone invece l'elenco completo per serie e anno, senza login:

    /ricercaArchivioCompleto/{serie}/{anno}?anno={anno}
    /gazzetta/{serie}/caricaDettaglio?dataPubblicazioneGazzetta=...&numeroGazzetta=...

Questo script enumera l'anno, scarica le pubblicazioni e accumula gli atti in
un checkpoint JSONL (ripresa a caldo), poi scrive il JSON canonico letto da
to_parquet.py.

Uso:
    python scripts/rebuild_archivio.py --anno 2026
    python scripts/rebuild_archivio.py --anno 2026 --limit 2   # smoke test
"""

from __future__ import annotations

import argparse
import json
import random
import re
import sys
import time
from html.parser import HTMLParser
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from scrape_30gg import BASE, SERIE_30GG, atti_da_html, fetch  # noqa: E402


class ListArchivioParser(HTMLParser):
    """Estrae i link (data, numero) delle gazzette di un anno/serie."""

    def __init__(self):
        super().__init__()
        self.pubs: list[dict] = []
        self._seen: set[tuple[str, str]] = set()

    def handle_starttag(self, tag, attrs):
        href = dict(attrs).get("href", "")
        m = re.search(
            r"caricaDettaglio\?dataPubblicazioneGazzetta=([0-9]{4}-[0-9]{2}-[0-9]{2})"
            r"&numeroGazzetta=([0-9]+)",
            href,
        )
        if not m:
            return
        key = (m.group(1), m.group(2))
        if key in self._seen:
            return
        self._seen.add(key)
        self.pubs.append({"data": m.group(1), "numero": m.group(2)})


def slug_archivio(serie: str) -> str:
    """'SG' -> 'serie_generale' (riusa la mappa del collector 30gg)."""
    return SERIE_30GG[serie].rsplit("/", 1)[-1]


def elenco_pubblicazioni(serie: str, anno: int) -> list[dict]:
    slug = slug_archivio(serie)
    url = f"{BASE}/ricercaArchivioCompleto/{slug}/{anno}?anno={anno}"
    parser = ListArchivioParser()
    parser.feed(fetch(url))
    return parser.pubs


def url_dettaglio(serie: str, pub: dict) -> str:
    slug = slug_archivio(serie)
    return (
        f"{BASE}/gazzetta/{slug}/caricaDettaglio"
        f"?dataPubblicazioneGazzetta={pub['data']}&numeroGazzetta={pub['numero']}"
    )


def carica_checkpoint(path: Path) -> tuple[list[dict], set[tuple[str, str]]]:
    """Legge il JSONL di ripresa: righe per gazzetta già processata."""
    righe: list[dict] = []
    fatte: set[tuple[str, str]] = set()
    if not path.exists():
        return righe, fatte
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            riga = json.loads(line)
        except json.JSONDecodeError:
            continue
        righe.append(riga)
        fatte.add((riga["serie"], riga["numero"]))
    return righe, fatte


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--anno", type=int, required=True)
    ap.add_argument("--serie", nargs="*", default=None, help="default: tutte")
    ap.add_argument("--limit", type=int, default=0, help="max pubblicazioni per serie (0 = tutte)")
    ap.add_argument("--sleep", type=float, default=0.6, help="pausa tra richieste (secondi)")
    ap.add_argument("--out", default=None, help="JSON finale (default data/gu_acts_30gg.json)")
    args = ap.parse_args()

    data_dir = Path(__file__).parent.parent / "data"
    data_dir.mkdir(exist_ok=True)
    checkpoint = data_dir / f"_rebuild_{args.anno}.jsonl"
    out_file = Path(args.out) if args.out else data_dir / "gu_acts_30gg.json"

    serie = args.serie or list(SERIE_30GG)
    righe, fatte = carica_checkpoint(checkpoint)
    gia_fatte = len(fatte)

    with checkpoint.open("a", encoding="utf-8") as fh:
        for s in serie:
            try:
                pubs = elenco_pubblicazioni(s, args.anno)
            except Exception as e:  # noqa: BLE001
                print(f"[{s}] elenco non disponibile: {e}")
                continue
            if args.limit:
                print(f"[{s}] {len(pubs)} pubblicazioni nel {args.anno} (limito a {args.limit})")
                pubs = pubs[: args.limit]
            else:
                print(f"[{s}] {len(pubs)} pubblicazioni nel {args.anno}")

            for i, pub in enumerate(pubs, 1):
                key = (s, pub["numero"])
                if key in fatte:
                    continue
                try:
                    html = fetch(url_dettaglio(s, pub))
                    atti = atti_da_html(html, s, pub["numero"], pub["data"])
                except Exception as e:  # noqa: BLE001
                    print(f"  [{s} n°{pub['numero']}] ERRORE: {e}")
                    continue

                fh.write(json.dumps(
                    {"serie": s, "numero": pub["numero"], "data": pub["data"], "atti": atti},
                    ensure_ascii=False,
                ) + "\n")
                fh.flush()
                fatte.add(key)
                if i % 10 == 0 or i == len(pubs):
                    print(f"  [{s}] {i}/{len(pubs)} n°{pub['numero']} ({len(atti)} atti)")
                time.sleep(args.sleep + random.uniform(0, 0.2))

    # Aggrega il checkpoint (riletto: può essere cresciuto in questo run)
    righe, _ = carica_checkpoint(checkpoint)
    visti: set[tuple[str, str]] = set()
    atti_totali: list[dict] = []
    for riga in righe:
        for a in riga.get("atti", []):
            key = (a.get("id", ""), a.get("serie", ""))
            if not key[0] or key in visti:
                continue
            visti.add(key)
            atti_totali.append(a)

    atti_totali.sort(key=lambda a: (a.get("data_pubblicazione", ""), a.get("id", "")))
    out_file.write_text(json.dumps(atti_totali, ensure_ascii=False), encoding="utf-8")

    print("\n" + "=" * 50)
    print(f"Gazzette processate: {len(fatte)} (nuove in questo run: {len(fatte) - gia_fatte})")
    print(f"Atti unici: {len(atti_totali)}")
    for s in serie:
        n = sum(1 for a in atti_totali if a.get("serie") == s)
        print(f"  {s}: {n}")
    print(f"Salvato: {out_file}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
