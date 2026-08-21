#!/usr/bin/env python3
"""GU Monitor — Cross-reference GU ↔ Normattiva.

Cerca gli atti normativi GU (pattern 26G*) su Normattiva API
e arricchisce il dataset con URN e testo vigente.
"""

import json
import sys
import time
from pathlib import Path
from urllib.request import urlopen, Request

BASE_URL = "https://api.normattiva.it/t/normattiva.api/bff-opendata/v1/api/v1"


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
            if data.get("data", {}).get("atto"):
                atto = data["data"]["atto"]
                # Build URN from data
                tipo = atto.get("tipoProvvedimentoDescrizione", "")
                anno = atto.get("annoProvvedimento")
                mese = atto.get("meseProvvedimento")
                giorno = atto.get("giornoProvvedimento")
                numero = atto.get("numeroProvvedimento")
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

    # Get normativi (26G pattern)
    atti = con.execute("""
        SELECT id, serie, data_pubblicazione, titolo, tipo_atto
        FROM atti
        WHERE serie = 'SG' AND id LIKE '26G%'
        ORDER BY data_pubblicazione
    """).fetchall()

    print(f"Trovati {len(atti)} atti normativi da incrociare")

    # Load existing crossref
    existing = {}
    if output_file.exists():
        existing = {r["id"]: r for r in json.loads(output_file.read_text())}

    results = []
    found = 0
    skipped = 0

    for i, (id_, serie, data_pub, titolo, tipo) in enumerate(atti):
        if id_ in existing:
            skipped += 1
            continue

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
                "sottotitolo": atto.get("sottoTitolo", "").strip()[:200],
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
    print(f"Attj processati: {len(atti)}")
    print(f"Skipped (già fatti): {skipped}")
    print(f"Trovati su Normattiva: {found}")
    print(f"Non trovati: {len(atti) - skipped - found}")
    print(f"Salvato in: {output_file}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
