#!/usr/bin/env python3
"""GU Monitor — collector unico.

Due modalità, un solo script:

    python scripts/collect.py                  # incrementale (watermark)
    python scripts/collect.py --anni 2025      # backfill di un anno
    python scripts/collect.py --anni 2019-2025 # backfill di un intervallo

Fa tutto quello che serve per aggiornare l'event log: enumera le pubblicazioni
che mancano (archivio annuale + finestra 30 giorni), le scarica, unisce il
risultato allo store e risolve gli URN Normattiva. Lo store è l'unico stato:
non ci sono JSON intermedi né cache separate.
"""

from __future__ import annotations

import argparse
import json
import random
import re
import sys
import time
from datetime import date, timedelta
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from urllib.request import Request, urlopen

import duckdb

sys.path.insert(0, str(Path(__file__).parent))

from gu_source import (  # noqa: E402
    SERIE,
    atti_da_html,
    elenco_30gg,
    elenco_archivio,
    fetch,
    url_dettaglio,
)

MAX_RICHIESTE = 5000  # guardia: un bug non deve diventare un blocco IP
NORMATTIVA_LINK = "https://www.normattiva.it/uri-res/N2Ls?"
NORMATTIVA_API = "https://api.normattiva.it/t/normattiva.api/bff-opendata/v1/api/v1"

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
    "business": ["societa'", "cooperativ", "assemblea", "s.p.a.", "s.r.l.", "s.a.s.",
                 "conferimento"],
    "governo_locale": ["regione", "regionale", "provincia", "comune di", "comunale",
                       "concessione", "demaniale"],
    "sanita_farmaci": ["autorizzazione all'immissione in commercio",
                       "immissione in commercio"],
}

# Riclassifica degli ALTRO (il tipo non è negli estremi ma nel titolo).
TIPO_TITLE_KEYWORDS = [
    "CONCORSO", "SENTENZA", "NOTIFICA", "CONFERIMENTO", "CONVOCAZIONE",
    "NOMINA", "LIQUIDAZIONE", "SOSTITUZIONE", "AUTORIZZAZIONE",
    "REVOC", "PROROGA", "ISCRIZIONE", "RINUNCIA",
]


# ── Finestra di cattura ────────────────────────────────────────────────


def watermark(store: Path) -> date | None:
    """Data di pubblicazione più recente già nello store."""
    if not store.exists():
        return None
    con = duckdb.connect()
    try:
        row = con.execute(
            f"select max(data_pubblicazione) from read_parquet('{store}')"
        ).fetchone()
    finally:
        con.close()
    if not row or not row[0]:
        return None
    return date.fromisoformat(str(row[0])[:10])


def inizio_finestra(wm: date | None, oggi: date, overlap: int = 3, lookback: int = 30) -> date:
    """Da dove ripartire: `overlap` giorni prima del watermark, o `lookback`."""
    if wm is None:
        return oggi - timedelta(days=lookback)
    return wm - timedelta(days=overlap)


def anni_da_scandire(da: date, a: date) -> list[int]:
    return list(range(da.year, a.year + 1))


def seleziona_pubblicazioni(pubs: list[dict], da: date) -> list[dict]:
    """Tiene le pubblicazioni da `da` in poi, dedup per (data, numero)."""
    visti: set[tuple[str, str]] = set()
    out: list[dict] = []
    for p in pubs:
        if date.fromisoformat(p["data"]) < da:
            continue
        key = (p["data"], p["numero"])
        if key in visti:
            continue
        visti.add(key)
        out.append(p)
    return out


# ── Arricchimento record ───────────────────────────────────────────────


def link_canonico(url: str) -> str:
    """Toglie i parametri di navigazione: `elenco30giorni` non identifica l'atto."""
    if not url:
        return url
    parti = urlsplit(url)
    params = [(k, v) for k, v in parse_qsl(parti.query, keep_blank_values=True)
              if k != "elenco30giorni"]
    return urlunsplit((parti.scheme, parti.netloc, parti.path, urlencode(params), parti.fragment))


def extract_topics(titolo: str, content: str = "") -> list[str]:
    text = f"{titolo} {content}".lower()
    return sorted({t for t, kws in TOPIC_KEYWORDS.items() if any(kw in text for kw in kws)})


def enrich(righe: list[dict]) -> list[dict]:
    """Normalizza date e link, calcola topic e riclassifica gli ALTRO."""
    for a in righe:
        d = a.get("data_pubblicazione", "")
        if re.match(r"\d{2}-\d{2}-\d{4}", d):
            a["data_pubblicazione"] = f"{d[6:]}-{d[3:5]}-{d[:2]}"
        a["link"] = link_canonico(a.get("link", ""))
        a["topic_str"] = ",".join(extract_topics(a.get("titolo", "")))
        if a.get("tipo_atto") == "ALTRO":
            upper = a.get("titolo", "").upper()
            for keyword in TIPO_TITLE_KEYWORDS:
                if keyword in upper:
                    a["tipo_atto"] = "REVOCA" if keyword == "REVOC" else keyword
                    break
    return righe


# ── URN Normattiva ─────────────────────────────────────────────────────


def build_urn(tipo: str, anno: int, mese: int, giorno: int, numero: int) -> str:
    tipo_map = {
        "LEGGE": "legge",
        "DECRETO-LEGGE": "decreto.legge",
        "DECRETO LEGISLATIVO": "decreto.legislativo",
        "DECRETO": "decreto",
        "DECRETO DEL PRESIDENTE DEL CONSIGLIO DEI MINISTRI": "decreto",
        "DECRETO DEL PRESIDENTE DELLA REPUBBLICA": "decreto",
        "REGOLAMENTO": "regolamento",
    }
    return f"urn:nir:stato:{tipo_map.get(tipo.upper(), 'atto')}:{anno:04d}-{mese:02d}-{giorno:02d};{numero}"


def normattiva_search(codice: str, data_gu: str) -> str | None:
    """URN dell'atto su Normattiva, o None se non c'è/ non è numerato."""
    payload = {"dataGU": data_gu, "codiceRedazionale": codice, "formatoRichiesta": "V"}
    req = Request(
        f"{NORMATTIVA_API}/atto/dettaglio-atto",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json", "Accept": "application/json",
                 "User-Agent": "GU-Monitor/0.1"},
    )
    try:
        with urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read())
    except Exception as e:  # noqa: BLE001
        print(f"  ERRORE Normattiva {codice}: {e}", file=sys.stderr)
        return None

    payload_data = data.get("data") or {}
    atto = payload_data.get("atto")
    if not atto:
        # Alcuni atti (ripubblicazioni) tornano in data.lista
        lista = payload_data.get("lista") or []
        atto = lista[0] if lista else None
    if not atto:
        return None

    anno, mese = atto.get("annoProvvedimento"), atto.get("meseProvvedimento")
    giorno, numero = atto.get("giornoProvvedimento"), atto.get("numeroProvvedimento")
    # numero 0/None = atto non numerato: l'URN ";0" non esiste
    if not (anno and mese and giorno and numero):
        return None
    return build_urn(atto.get("tipoProvvedimentoDescrizione", ""), anno, mese, giorno, numero)


def urn_pendenti(con, table: str) -> list[tuple[str, str]]:
    """Atti normativi senza URN: (id, data di pubblicazione)."""
    return con.execute(
        f"""SELECT id, CAST(data_pubblicazione AS VARCHAR) FROM {table}
            WHERE serie = 'SG' AND regexp_matches(id, '^[0-9]{{2}}G')
              AND COALESCE(urn_normattiva, '') = ''
            ORDER BY data_pubblicazione"""
    ).fetchall()


def applica_urn(con, table: str, risultati: list[tuple[str, str]]) -> int:
    """Scrive gli URN trovati. `risultati` = [(id, urn)]."""
    if not risultati:
        return 0
    con.execute("CREATE OR REPLACE TEMP TABLE _urn (id VARCHAR, urn VARCHAR)")
    con.executemany("INSERT INTO _urn VALUES (?, ?)", risultati)
    con.execute(
        f"""UPDATE {table} SET
              urn_normattiva = _urn.urn,
              link_normattiva = '{NORMATTIVA_LINK}' || _urn.urn
            FROM _urn WHERE {table}.id = _urn.id"""
    )
    return len(risultati)


def crossref(con, table: str, sleep: float = 0.3) -> int:
    """Risolve gli URN mancanti interrogando l'API Normattiva."""
    pendenti = urn_pendenti(con, table)
    if not pendenti:
        return 0
    print(f"[urn] {len(pendenti)} atti normativi da risolvere")
    trovati = []
    for codice, data_gu in pendenti:
        urn = normattiva_search(codice, data_gu)
        if urn:
            trovati.append((codice, urn))
        time.sleep(sleep)
    print(f"[urn] risolti {len(trovati)}/{len(pendenti)}")
    return applica_urn(con, table, trovati)


# ── Store ──────────────────────────────────────────────────────────────

COLONNE = {
    "id": "VARCHAR",
    "serie": "VARCHAR",
    "gazzetta_numero": "VARCHAR",
    "data_pubblicazione": "VARCHAR",
    "titolo": "VARCHAR",
    "estremi": "VARCHAR",
    "tipo_atto": "VARCHAR",
    "ente": "VARCHAR",
    "topic_str": "VARCHAR",
    "link": "VARCHAR",
    "urn_normattiva": "VARCHAR",
    "link_normattiva": "VARCHAR",
}


def _tabella_nuovi(con, righe: list[dict]) -> None:
    """Record nuovi in una tabella temporanea (niente file intermedi)."""
    colonne = ", ".join(f"{c} {t}" for c, t in COLONNE.items())
    segnaposto = ", ".join("?" * len(COLONNE))
    con.execute(f"CREATE OR REPLACE TEMP TABLE new_data ({colonne})")
    if righe:
        con.executemany(
            f"INSERT INTO new_data VALUES ({segnaposto})",
            [[r.get(c) for c in COLONNE] for r in righe],
        )


def merge(con, store: Path, righe: list[dict], rebuild: bool) -> int:
    """Unisce i nuovi record allo store. Ritorna il totale.

    Incrementale: la riga esistente vince (nessuna riscrittura del passato).
    Backfill: la riga ricostruita vince (serve a correggere i campi già salvati).
    """
    _tabella_nuovi(con, righe)

    if not store.exists():
        con.execute("CREATE OR REPLACE TABLE merged AS SELECT * FROM new_data")
        return con.execute("SELECT count(*) FROM merged").fetchone()[0]

    con.execute(f"CREATE OR REPLACE TABLE existing AS SELECT * FROM read_parquet('{store}')")
    esistenti = {r[0] for r in con.execute("DESCRIBE existing").fetchall()}
    nuovi = {r[0] for r in con.execute("DESCRIBE new_data").fetchall()}
    for col in esistenti - nuovi:
        con.execute(f"ALTER TABLE new_data ADD COLUMN {col} VARCHAR")
    for col in nuovi - esistenti:
        con.execute(f"ALTER TABLE existing ADD COLUMN {col} VARCHAR")

    cols = sorted(esistenti | nuovi)
    sel_e = ", ".join(f"e.{c}" for c in cols)
    sel_n = ", ".join(f"n.{c}" for c in cols)
    if rebuild:
        con.execute(f"""
            CREATE OR REPLACE TABLE merged AS
            SELECT {sel_n} FROM new_data n
            UNION ALL
            SELECT {sel_e} FROM existing e
            LEFT JOIN new_data n ON n.id = e.id WHERE n.id IS NULL
        """)
    else:
        con.execute(f"""
            CREATE OR REPLACE TABLE merged AS
            SELECT {sel_e} FROM existing e
            UNION ALL
            SELECT {sel_n} FROM new_data n
            LEFT JOIN existing e ON n.id = e.id WHERE e.id IS NULL
        """)
    return con.execute("SELECT count(*) FROM merged").fetchone()[0]


# ── Main ───────────────────────────────────────────────────────────────


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--anni", default=None, help="backfill: 2025 oppure 2019-2025")
    ap.add_argument("--overlap", type=int, default=3, help="giorni di sovrapposizione")
    ap.add_argument("--lookback-days", type=int, default=30, help="finestra se lo store è vuoto")
    ap.add_argument("--sleep", type=float, default=0.5)
    ap.add_argument("--store", default=None, help="default data/gu_acts.parquet")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)

    data_dir = Path(__file__).parent.parent / "data"
    data_dir.mkdir(exist_ok=True)
    store = Path(args.store) if args.store else data_dir / "gu_acts.parquet"

    oggi = date.today()
    if args.anni:
        estremi = args.anni.split("-")
        anni = list(range(int(estremi[0]), int(estremi[-1]) + 1))
        inizio = date(anni[0], 1, 1)
        rebuild = True
        print(f"[backfill] anni {anni}")
    else:
        wm = watermark(store)
        inizio = inizio_finestra(wm, oggi, args.overlap, args.lookback_days)
        anni = anni_da_scandire(inizio, oggi)
        rebuild = False
        print(f"[incrementale] watermark {wm or 'nessuno'} · finestra dal {inizio}")

    righe: list[dict] = []
    attese = scaricate = 0
    fallite: list[tuple[str, str, str]] = []
    richieste = 0

    for serie in SERIE:
        try:
            pubs: list[dict] = []
            for anno in anni:
                pubs += elenco_archivio(serie, anno)
                richieste += 1
            if not rebuild:
                # La finestra 30gg copre un eventuale ritardo dell'archivio.
                pubs += elenco_30gg(serie)
                richieste += 1
        except Exception as e:  # noqa: BLE001
            print(f"[{serie}] elenco non disponibile: {e}")
            fallite.append((serie, "elenco", str(e)))
            continue

        da_fare = seleziona_pubblicazioni(pubs, inizio)
        attese += len(da_fare)
        print(f"[{serie}] {len(da_fare)} pubblicazioni")

        if args.dry_run:
            continue

        for i, pub in enumerate(da_fare, 1):
            if richieste >= MAX_RICHIESTE:
                fallite.append((serie, pub["numero"], "guardia richieste"))
                break
            try:
                righe += atti_da_html(
                    fetch(url_dettaglio(serie, pub)), serie, pub["numero"], pub["data"]
                )
                richieste += 1
                scaricate += 1
                if i % 25 == 0 or i == len(da_fare):
                    print(f"  [{serie}] {i}/{len(da_fare)}")
                time.sleep(args.sleep + random.uniform(0, 0.2))
            except Exception as e:  # noqa: BLE001
                print(f"  [{serie} n°{pub['numero']}] ERRORE: {e}")
                fallite.append((serie, pub["numero"], str(e)))

    print(f"\n[fetch] attese {attese} · scaricate {scaricate} · atti {len(righe)} · richieste {richieste}")
    if args.dry_run:
        return 0
    if attese != scaricate:
        print(f"ERRORE: attese {attese}, scaricate {scaricate}")

    con = duckdb.connect()
    totale = merge(con, store, enrich(righe), rebuild)
    print(f"[store] {totale} atti")

    risolti = crossref(con, "merged", args.sleep)
    if risolti:
        print(f"[urn] {risolti} URN scritti")

    # Lo store ha esattamente le colonne del contratto: eventuali residui
    # (es. la vecchia colonna `json`) vengono scartati qui.
    con.execute(f"CREATE OR REPLACE TABLE finale AS SELECT {', '.join(COLONNE)} FROM merged")
    con.execute(f"COPY finale TO '{store}' (FORMAT PARQUET, COMPRESSION 'zstd')")
    con.close()
    print(f"Salvato: {store}")

    if fallite:
        print(f"\n{len(fallite)} errori:")
        for serie, numero, err in fallite[:20]:
            print(f"  [{serie}] {numero}: {err}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
