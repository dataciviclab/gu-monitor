#!/usr/bin/env python3
"""GU Monitor — Convert JSON → Parquet con append incrementale.

Legge gu_acts_30gg.json, arricchisce con topic, e appende in gu_acts.parquet.
Deduplica per id (codice redazionale), univoco per atto.
"""

import json
import re
import sys
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import duckdb

NORMATTIVA_LINK = "https://www.normattiva.it/uri-res/N2Ls?"

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


def link_canonico(url: str) -> str:
    """Toglie i parametri di navigazione dal link della pagina di dettaglio.

    `elenco30giorni` vale true o false a seconda di come ci si arriva: non
    identifica l'atto e rompeva la chiave di merge (2.077 duplicati sul
    rebuild 2026).
    """
    if not url:
        return url
    parti = urlsplit(url)
    params = [
        (k, v) for k, v in parse_qsl(parti.query, keep_blank_values=True)
        if k != "elenco30giorni"
    ]
    return urlunsplit((parti.scheme, parti.netloc, parti.path, urlencode(params), parti.fragment))


def enrich(data: list[dict]) -> list[dict]:
    for a in data:
        d = a.get("data_pubblicazione", "")
        if re.match(r"\d{2}-\d{2}-\d{4}", d):
            a["data_pubblicazione"] = f"{d[6:]}-{d[3:5]}-{d[:2]}"
        a["link"] = link_canonico(a.get("link", ""))
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


def apply_crossref(con, table: str, crossref_file: Path) -> int:
    """Applica gli URN di gu_crossref.json a TUTTE le righe di `table`.

    Deve girare dopo il merge con il parquet esistente: un URN scoperto
    dopo il giorno di pubblicazione di un atto non arriverebbe mai al
    dataset se l'update toccasse solo il JSON del run corrente (era il
    caso: 71 lookup riusciti, 28 URN salvati).
    """
    cols = {r[0] for r in con.execute(f"DESCRIBE {table}").fetchall()}
    for col in ("urn_normattiva", "link_normattiva"):
        if col not in cols:
            con.execute(f"ALTER TABLE {table} ADD COLUMN {col} VARCHAR")

    con.execute(
        f"UPDATE {table} SET "
        f"urn_normattiva = COALESCE(urn_normattiva, ''), "
        f"link_normattiva = COALESCE(link_normattiva, '')"
    )

    if not crossref_file.exists():
        print("gu_crossref.json non trovato — URN Normattiva non popolato")
        return 0

    con.execute(
        "CREATE OR REPLACE TABLE _crossref AS "
        f"SELECT id_gu, urn FROM read_json_auto('{crossref_file}') "
        "WHERE urn IS NOT NULL AND urn <> ''"
    )
    con.execute(
        f"UPDATE {table} SET "
        f"urn_normattiva = _crossref.urn, "
        f"link_normattiva = '{NORMATTIVA_LINK}' || _crossref.urn "
        f"FROM _crossref WHERE {table}.id = _crossref.id_gu"
    )
    return con.execute(f"SELECT count(*) FROM {table} WHERE urn_normattiva <> ''").fetchone()[0]


def merge_esistente_nuovo(con, rebuild: bool = False) -> None:
    """Crea `merged` da `existing` e `new_data` (tabelle già presenti).

    Incrementale: la riga esistente vince, il nuovo aggiunge solo gli assenti.
    Rebuild: la riga ricostruita sostituisce quella esistente con la stessa
    chiave id — serve a correggere i campi già salvati.
    """
    existing_cols = {r[0] for r in con.execute("DESCRIBE existing").fetchall()}
    new_cols = {r[0] for r in con.execute("DESCRIBE new_data").fetchall()}
    for col in existing_cols - new_cols:
        con.execute(f"ALTER TABLE new_data ADD COLUMN {col} VARCHAR")
    for col in new_cols - existing_cols:
        con.execute(f"ALTER TABLE existing ADD COLUMN {col} VARCHAR")

    cols = sorted(existing_cols | new_cols)
    col_e = ", ".join([f"e.{c}" for c in cols])
    col_n = ", ".join([f"n.{c}" for c in cols])
    if rebuild:
        con.execute(f"""
            CREATE TABLE merged AS
            SELECT {col_n} FROM new_data n
            UNION ALL
            SELECT {col_e} FROM existing e
            LEFT JOIN new_data n ON n.id = e.id
            WHERE n.id IS NULL
        """)
    else:
        con.execute(f"""
            CREATE TABLE merged AS
            SELECT {col_e} FROM existing e
            UNION ALL
            SELECT {col_n} FROM new_data n
            LEFT JOIN existing e ON n.id = e.id
            WHERE e.id IS NULL
        """)


def main(argv: list[str] | None = None):
    import argparse

    ap = argparse.ArgumentParser(description="JSON GU -> parquet (append o rebuild)")
    ap.add_argument(
        "--rebuild",
        action="store_true",
        help="le righe del JSON sostituiscono quelle esistenti con lo stesso id",
    )
    ap.add_argument(
        "--input",
        default=None,
        help="JSON di input (default data/gu_atti_delta.json)",
    )
    ap.add_argument("--store", default=None, help="parquet di output (default data/gu_acts.parquet)")
    args = ap.parse_args(argv)

    data_dir = Path(__file__).parent.parent / "data"
    json_file = Path(args.input) if args.input else data_dir / "gu_atti_delta.json"
    parquet_file = Path(args.store) if args.store else data_dir / "gu_acts.parquet"

    if not json_file.exists():
        print(f"Errore: {json_file} non trovato", file=sys.stderr)
        return 1

    data = json.loads(json_file.read_text())
    data = enrich(data)

    # Reclassify ALTRO based on title keywords
    TIPO_TITLE_KEYWORDS = [
        "CONCORSO", "SENTENZA", "NOTIFICA", "CONFERIMENTO", "CONVOCAZIONE",
        "NOMINA", "LIQUIDAZIONE", "SOSTITUZIONE", "AUTORIZZAZIONE",
        "REVOC", "PROROGA", "ISCRIZIONE", "RINUNCIA",
    ]
    reclassified = 0
    for a in data:
        if a.get("tipo_atto") == "ALTRO":
            title_upper = a.get("titolo", "").upper()
            for keyword in TIPO_TITLE_KEYWORDS:
                if keyword in title_upper:
                    a["tipo_atto"] = "REVOCA" if keyword == "REVOC" else keyword
                    reclassified += 1
                    break
    if reclassified:
        print(f"Riclassificati:  {reclassified} atti da ALTRO")

    # Deduplicate sull'id (codice redazionale), univoco per atto.
    # Il link non è una chiave: porta il flag di navigazione elenco30giorni.
    seen = set()
    deduped = []
    for a in data:
        key = a.get("id", "")
        if key and key not in seen:
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
        merge_esistente_nuovo(con, rebuild=args.rebuild)
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

    matched = apply_crossref(con, "merged", data_dir / "gu_crossref.json")
    print(f"Normattiva URN:  {matched}/{n_merged} atti collegati")

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
