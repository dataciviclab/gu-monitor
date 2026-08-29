#!/usr/bin/env python3
"""GU Monitor — Convert JSON → Parquet con append incrementale.

Legge gu_acts_30gg.json, arricchisce con topic, e scrive/appende in gu_acts.parquet.
Deduplica per (id, link) — la chiave naturale della Gazzetta.
"""

import json
import re
import sys
from pathlib import Path

import duckdb

# ── Topic keywords (espanso) ────────────────────────────────────────────────

TOPIC_KEYWORDS = {
    # settori
    "fisco": ["fiscale", "tributario", "tributi", "imposta", "irpef", "iva", "accisa",
              "bilancio", "rendicont"],
    "sanita": ["farmaco", "medicinale", "sanitario", "ospedaliero", "asl", "aifa",
               "medicin", "comirnaty", "linagliptin"],
    "lavoro": ["lavoro", "lavoratori", "impiego", "concors", "dipendente", "pubblico",
               "borsa di ricerca", "assegno di ricerca"],
    "ambiente": ["ambiente", "ecolog", "compost", "rifiuti", "inquinamento",
                 "bonifica", "sostenibilit"],
    "appalti": ["appalto", "contratto", "gara", "bandimento", "astante"],
    "pnrr": ["pnrr", "ripresa", "resilienza", "next generation"],
    "energia": ["energia", "elettric", "gas", "idrogeno", "carburante", "impianto fotovoltaico"],
    "giustizia": ["giustizia", "penale", "civile", "tribunale", "corte",
                  "notifica", "sentenza", "curatore", "falliment", "eredit"],
    "europa": ["europeo", "europea", "ue ", "regolamento (ue)", "decisione (ue)",
               "decisione pesc"],
    "agricoltura": ["agricoltura", "agricolo", "zootecnico", "alimentare", "pesca",
                    "viticolo", "denominazione di origine"],
    "istruzione": ["universit", "ricercat", "docente", "studente", "laurea",
                   "politecnico", "scuola"],
    "trasporti": ["trasport", "autostrad", "ferroviario", "aeronautico", "portuale"],
    "edilizia": ["edilizia", "casa", "immobiliare", "urbanistica", "catasto"],
    "sicurezza": ["sicurezza", "polizia", "carabinieri", "vigili del fuoco"],
    # nuovi topic per P2 e attività non-legislative
    "business": ["societa'", "società", "cooperativ", "assemblea", "consiglio di amministrazione",
                 "s.p.a.", "s.r.l.", "s.a.s.", "conferimento"],
    "governo_locale": ["regione", "regionale", "provincia", "comune di", "comunale",
                       "concessione", "demaniale"],
    "sanita_farmaci": ["autorizzazione all'immissione in commercio", "immissione in commercio"],
}


def extract_topics(titolo: str, content: str = "") -> list[str]:
    text = f"{titolo} {content}".lower()
    return sorted(set(t for t, kws in TOPIC_KEYWORDS.items() if any(kw in text for kw in kws)))


def main():
    data_dir = Path(__file__).parent.parent / "data"
    json_file = data_dir / "gu_acts_30gg.json"
    parquet_file = data_dir / "gu_acts.parquet"

    if not json_file.exists():
        print(f"Errore: {json_file} non trovato", file=sys.stderr)
        return 1

    # Load and enrich JSON
    data = json.loads(json_file.read_text())

    # Add topics and normalize date format
    for a in data:
        # Normalize date: "22-07-2026" → "2026-07-22"
        d = a.get("data_pubblicazione", "")
        if re.match(r"\d{2}-\d{2}-\d{4}", d):
            a["data_pubblicazione"] = f"{d[6:]}-{d[3:5]}-{d[:2]}"
        # Compute topic_str from title (always recompute for fresh keywords)
        titolo = a.get("titolo", "")
        content = a.get("content_snippet", "")
        topics = extract_topics(titolo, content)
        # Merge with any existing topic from scraper
        existing = a.get("topic", [])
        if isinstance(existing, str):
            existing = [t.strip() for t in existing.split(",") if t.strip()]
        if existing:
            topics = sorted(set(topics + existing))
        a["topic_str"] = ",".join(topics) if topics else ""
        # Remove topic list (keep only topic_str)
        a.pop("topic", None)
        a.pop("content_snippet", None)
        a.pop("timestamp_fetch", None)

    # Deduplicate on (id, link) — the natural key
    seen = set()
    deduped = []
    for a in data:
        key = (a.get("id", ""), a.get("link", ""))
        if key not in seen:
            seen.add(key)
            deduped.append(a)
    print(f"JSON caricati:   {len(data)}")
    print(f"Dopo dedup:      {len(deduped)} (rimossi {len(data) - len(deduped)} duplicati)")

    # Write temp enriched file
    tmp_file = data_dir / "_tmp_enriched.json"
    tmp_file.write_text(json.dumps(deduped, ensure_ascii=False))

    con = duckdb.connect(":memory:")

    # Always rebuild from scratch for a clean parquet
    con.execute(f"CREATE TABLE merged AS SELECT * FROM read_json_auto('{tmp_file}')")
    n_merged = con.execute("SELECT COUNT(*) FROM merged").fetchone()[0]

    # Write parquet
    con.execute(f"COPY merged TO '{parquet_file}' (FORMAT PARQUET, COMPRESSION 'zstd')")

    tmp_file.unlink(missing_ok=True)
    con.close()

    print(f"Salvato:         {n_merged} atti → {parquet_file}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
