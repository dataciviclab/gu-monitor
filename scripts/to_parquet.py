#!/usr/bin/env python3
"""GU Monitor — Convert JSON → Parquet con append incrementale.

Legge gu_acts_30gg.json, arricchisce con topic, e appende in gu_acts.parquet.
Deduplica per (id, link) — la chiave naturale della Gazzetta.
"""

import json
import re
import sys
from pathlib import Path

import duckdb

TOPIC_KEYWORDS = {
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
    "business": ["societa'", "societa\'", "cooperativ", "assemblea",
                 "s.p.a.", "s.r.l.", "s.a.s.", "conferimento"],
    "governo_locale": ["regione", "regionale", "provincia", "comune di", "comunale",
                       "concessione", "demaniale"],
    "sanita_farmaci": ["autorizzazione all'immissione in commercio", "immissione in commercio"],
}


def extract_topics(titolo: str, content: str = "") -> list[str]:
    text = f"{titolo} {content}".lower()
    return sorted(set(
        t for t, kws in TOPIC_KEYWORDS.items() if any(kw in text for kw in kws)
    ))


def enrich(data: list[dict]) -> list[dict]:
    for a in data:
        d = a.get("data_pubblicazione", "")
        if re.match(r"\d{2}-\d{2}-\d{4}", d):
            a["data_pubblicazione"] = f"{d[6:]}-{d[3:5]}-{d[:2]}"
        topics = extract_topics(a.get("titolo", ""), a.get("content_snippet", ""))
        existing = a.get("topic", [])
        if isinstance(existing, str):
            existing = [t.strip() for t in existing.split(",") if t.strip()]
        if existing:
            topics = sorted(set(topics + existing))
        a["topic_str"] = ",".join(topics) if topics else ""
        a.pop("topic", None)
        a.pop("content_snippet", None)
        a.pop("timestamp_fetch", None)
    return data


def main():
    data_dir = Path(__file__).parent.parent / "data"
    json_file = data_dir / "gu_acts_30gg.json"
    parquet_file = data_dir / "gu_acts.parquet"

    if not json_file.exists():
        print(f"Errore: {json_file} non trovato", file=sys.stderr)
        return 1

    data = json.loads(json_file.read_text())
    data = enrich(data)

    # Deduplicate on (id, link)
    seen = set()
    deduped = []
    for a in data:
        key = (a.get("id", ""), a.get("link", ""))
        if key not in seen:
            seen.add(key)
            deduped.append(a)
    print(f"JSON caricati:   {len(data)}")
    print(f"Dopo dedup:      {len(deduped)} (rimossi {len(data) - len(deduped)} duplicati)")

    tmp_file = data_dir / "_tmp_enriched.json"
    tmp_file.write_text(json.dumps(deduped, ensure_ascii=False))

    con = duckdb.connect(":memory:")

    if parquet_file.exists():
        con.execute(f"CREATE TABLE existing AS SELECT * FROM read_parquet('{parquet_file}')")
        con.execute(f"CREATE TABLE new_data AS SELECT * FROM read_json_auto('{tmp_file}')")
        existing_cols = {r[0] for r in con.execute("DESCRIBE existing").fetchall()}
        new_cols = {r[0] for r in con.execute("DESCRIBE new_data").fetchall()}
        for col in existing_cols - new_cols:
            con.execute(f"ALTER TABLE new_data ADD COLUMN {col} VARCHAR")
        for col in new_cols - existing_cols:
            con.execute(f"ALTER TABLE existing ADD COLUMN {col} VARCHAR")
        cols = sorted(existing_cols | new_cols)
        col_e = ", ".join([f"e.{c}" for c in cols])
        col_n = ", ".join([f"n.{c}" for c in cols])
        con.execute(f"""
            CREATE TABLE merged AS
            SELECT {col_e} FROM existing e
            UNION ALL
            SELECT {col_n} FROM new_data n
            LEFT JOIN existing e ON n.id = e.id AND n.link = e.link
            WHERE e.id IS NULL
        """)
        n_existing = con.execute("SELECT COUNT(*) FROM existing").fetchone()[0]
        n_new = con.execute("SELECT COUNT(*) FROM new_data").fetchone()[0]
        n_merged = con.execute("SELECT COUNT(*) FROM merged").fetchone()[0]
        n_added = n_merged - n_existing
    else:
        con.execute(f"CREATE TABLE merged AS SELECT * FROM read_json_auto('{tmp_file}')")
        n_existing = 0
        n_new = con.execute("SELECT COUNT(*) FROM merged").fetchone()[0]
        n_merged = n_new
        n_added = n_new

    con.execute(f"COPY merged TO '{parquet_file}' (FORMAT PARQUET, COMPRESSION 'zstd')")
    tmp_file.unlink(missing_ok=True)
    con.close()

    print(f"Esisto:  {n_existing} atti")
    print(f"Aggiunti: {n_added} atti")
    print(f"Totale:  {n_merged} atti")
    print(f"Salvato: {parquet_file}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
