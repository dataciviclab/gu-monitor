#!/usr/bin/env python3
"""GU Monitor — Cross-reference GU ↔ Normattiva.

Cerca gli atti normativi GU (pattern 26G*) su Normattiva API
e arricchisce il dataset con URN e testo vigente.
"""

import json
import sys
import time
from pathlib import Path
from urllib.request import Request, urlopen

BASE_URL = "https://api.normattiva.it/t/normattiva.api/bff-opendata/v1/api/v1"

# Codice redazionale normativo = AAGG###### (es. 26G00151): il prefisso è
# l'anno. Niente LIKE '26G%' hardcoded, altrimenti il crossref si spegne
# il 1° gennaio.
SQL_NORMATIVI = """
    SELECT id, serie, data_pubblicazione, titolo, tipo_atto
    FROM atti
    WHERE serie = 'SG' AND regexp_matches(id, '^[0-9]{2}G')
    ORDER BY data_pubblicazione
"""


def build_urn(tipo: str, anno: int, mese: int, giorno: int, numero: int) -> str:
    """Costruisce URN NIR da tipo, data, numero (formato Normattiva)."""
    tipo_map = {
        "LEGGE": "legge",
        "DECRETO-LEGGE": "decreto.legge",
        "DECRETO LEGISLATIVO": "decreto.legislativo",
        "DECRETO": "decreto",
        "DECRETO DEL PRESIDENTE DEL CONSIGLIO DEI MINISTRI": "decreto",
        "DECRETO DEL PRESIDENTE DELLA REPUBBLICA": "decreto",
        "REGOLAMENTO": "regolamento",
    }
    tipo_nir = tipo_map.get(tipo.upper(), "atto")
    return f"urn:nir:stato:{tipo_nir}:{anno:04d}-{mese:02d}-{giorno:02d};{numero}"


def normattiva_search(codice_redazionale: str, data_gu: str) -> dict | None:
    """Cerca un atto su Normattiva per codice redazionale GU."""
    url = f"{BASE_URL}/atto/dettaglio-atto"
    payload = json.dumps({
        "dataGU": data_gu,
        "codiceRedazionale": codice_redazionale,
        "formatoRichiesta": "V"
    }).encode()

    req = Request(url, data=payload, headers={
        "Content-Type": "application/json",
        "Accept": "application/json",
        "User-Agent": "GU-Monitor/0.1"
    })

    try:
        with urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read())
            payload_data = data.get("data") or {}
            atto = payload_data.get("atto")
            if not atto:
                # Alcuni atti (ripubblicazioni) tornano in data.lista
                lista = payload_data.get("lista") or []
                if isinstance(lista, list) and lista:
                    atto = lista[0]
            if atto:
                # Build URN from data
                tipo = atto.get("tipoProvvedimentoDescrizione", "")
                anno = atto.get("annoProvvedimento")
                mese = atto.get("meseProvvedimento")
                giorno = atto.get("giornoProvvedimento")
                numero = atto.get("numeroProvvedimento")
                # numero 0/None = atto non numerato: l'URN ";0" non esiste
                if anno and mese and giorno and numero:
                    atto["urn"] = build_urn(tipo, anno, mese, giorno, numero)
                return atto
    except Exception as e:
        print(f"  ERRORE: {e}", file=sys.stderr)
    return None


def main():
    import duckdb

    data_dir = Path(__file__).parent.parent / "data"
    parquet_file = data_dir / "gu_acts.parquet"
    output_file = data_dir / "gu_crossref.json"

    if not parquet_file.exists():
        print("Dataset non trovato", file=sys.stderr)
        return 1

    con = duckdb.connect(":memory:")
    con.execute(f"CREATE TABLE atti AS SELECT * FROM read_parquet('{parquet_file}')")

    # Get normativi: codice redazionale nella forma AAGG###### (26G00151).
    # Il prefisso è l'anno, quindi il filtro non va hardcoded sull'anno corrente
    # (la vecchia condizione `id LIKE '26G%'` spegneva il crossref a gennaio).
    atti = con.execute(SQL_NORMATIVI).fetchall()

    print(f"Trovati {len(atti)} atti normativi da incrociare")

    # Load existing crossref — skip only successful lookups, allow retry for failures
    existing = {}
    if output_file.exists():
        existing = {r["id_gu"]: r for r in json.loads(output_file.read_text())}

    results = []
    found = 0
    skipped = 0
    retried = 0

    for i, (id_, serie, data_pub, titolo, tipo) in enumerate(atti):
        if id_ in existing and existing[id_].get("urn"):
            skipped += 1
            continue

        # Mark as retry if previously failed
        if id_ in existing and not existing[id_].get("urn"):
            retried += 1

        data_gu = str(data_pub)
        print(f"  [{i+1}/{len(atti)}] {id_} ({data_gu})...", end=" ", flush=True)

        atto = normattiva_search(id_, data_gu)
        if atto:
            result = {
                "id_gu": id_,
                "data_gu": data_gu,
                "titolo_gu": titolo,
                "tipo_atto": tipo,
                "urn": atto.get("urn", ""),
                "titolo_normattiva": atto.get("titolo", ""),
                "sottotitolo": (atto.get("sottoTitolo") or "").strip()[:200],
                "articolo_html": bool(atto.get("articoloHtml")),
            }
            results.append(result)
            existing[id_] = result
            found += 1
            print(f"✅ URN: {result['urn'][:50]}")
        else:
            results.append({
                "id_gu": id_,
                "data_gu": data_gu,
                "titolo_gu": titolo,
                "tipo_atto": tipo,
                "urn": None,
                "titolo_normattiva": None,
                "sottotitolo": None,
                "articolo_html": False,
            })
            print("❌ non trovato")

        time.sleep(0.3)  # Be polite

    # Save
    output_file.write_text(json.dumps(list(existing.values()), indent=2, ensure_ascii=False))

    print(f"\n{'=' * 50}")
    print(f"Atti processati: {len(atti)}")
    print(f"Skipped (già fatti): {skipped}")
    print(f"Retry (precedentemente falliti): {retried}")
    print(f"Trovati su Normattiva: {found}")
    print(f"Non trovati: {len(atti) - skipped - found}")
    print(f"Salvato in: {output_file}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
