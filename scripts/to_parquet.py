#!/usr/bin/env python3
"""GU Monitor — Convert JSON → Parquet con append incrementale.

Legge gu_acts_30gg.json, arricchisce con topic, e scrive/appende in gu_acts.parquet.
Deduplica per (id, serie) prima di scrivere.
"""

import json
import re
import sys
from pathlib import Path

import duckdb

TOPIC_KEYWORDS = {
    "fisco": ["fiscale", "tributario", "tributi", "imposta", "irpef", "iva", "accisa"],
    "sanita": ["farmaco", "medicinale", "sanitario", "ospedaliero", "asl", "aifa", "medicin"],
    "lavoro": ["lavoro", "lavoratori", "impiego", "concors", "dipendente", "pubblico"],
    "ambiente": ["ambiente", "ecolog", "compost", "rifiuti", "inquinamento"],
    "appalti": ["appalto", "contratto", "gara", "bandimento"],
    "pnrr": ["pnrr", "ripresa", "resilienza", "next generation"],
    "energia": ["energia", "elettric", "gas", "idrogeno", "carburante"],
    "giustizia": ["giustizia", "penale", "civile", "tribunale", "corte"],
    "europa": ["europeo", "europea", "ue", "regolamento (ue)", "decisione (ue)"],
    "agricoltura": ["agricoltura", "agricolo", "zootecnico", "alimentare", "pesca"],
    "istruzione": ["universit", "ricercat", "docente", "studente", "laurea"],
    "trasporti": ["trasport", "autostrad", "ferroviario", "aeronautico"],
    "edilizia": ["edilizia", "casa", "immobiliare", "urbanistica"],
    "sicurezza": ["sicurezza", "polizia", "carabinieri"],
}


def extract_topics(titolo: str, content: str = "") -> list[str]:
    text = f"{titolo} {content}".lower()
    return [t for t, kws in TOPIC_KEYWORDS.items() if any(kw in text for kw in kws)]


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
        # Add topics if missing
        if "topic" not in a or not a["topic"]:
            a["topic"] = extract_topics(a.get("titolo", ""), a.get("content_snippet", ""))
        # Ensure topic is a list
        if isinstance(a["topic"], str):
            a["topic"] = [t.strip() for t in a["topic"].split(",") if t.strip()]
        a["topic_str"] = ",".join(a["topic"]) if isinstance(a["topic"], list) else ""

    # Write temp enriched file
    tmp_file = data_dir / "_tmp_enriched.json"
    tmp_file.write_text(json.dumps(data, ensure_ascii=False))

    con = duckdb.connect(":memory:")

    if parquet_file.exists():
        # Load existing parquet
        con.execute(f"CREATE TABLE existing AS SELECT * FROM read_parquet('{parquet_file}')")
        # Load new data
        con.execute(f"CREATE TABLE new_data AS SELECT * FROM read_json_auto('{tmp_file}')")
        # Add missing columns to new_data
        existing_cols = {r[0] for r in con.execute("DESCRIBE existing").fetchall()}
        new_cols = {r[0] for r in con.execute("DESCRIBE new_data").fetchall()}
        for col in existing_cols - new_cols:
            con.execute(f"ALTER TABLE new_data ADD COLUMN {col} VARCHAR")
        # Merge: append new, skip duplicates
        con.execute("""
            CREATE TABLE merged AS
            SELECT * FROM existing
            UNION ALL
            SELECT nd.* FROM new_data nd
            LEFT JOIN existing e ON nd.id = e.id AND nd.serie = e.serie
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

    # Write parquet
    con.execute(f"COPY merged TO '{parquet_file}' (FORMAT PARQUET, COMPRESSION 'zstd')")

    tmp_file.unlink(missing_ok=True)
    con.close()

    print(f"Esisto: {n_existing} atti")
    print(f"Nuovi:  {n_added} atti")
    print(f"Totale: {n_merged} atti")
    print(f"Salvato: {parquet_file}")

    return 0


if __name__ == "__main__":
    import re
    sys.exit(main())
