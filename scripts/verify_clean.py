#!/usr/bin/env python3
"""Verifica del clean pubblicato (guardia del build).

La cattura può fallire: quella è una condizione della fonte, e il job lo dice.
Il build invece non deve mai produrre "zero righe" restando verde. Questo
script è la guardia che il reusable esegue dopo `make run`.
"""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

import duckdb

ROOT = Path(__file__).parent.parent
CLEAN_GLOB = "out/data/clean/gu_atti/*/gu_atti_*_clean.parquet"

MIN_RIGHE = 1_000
MAX_GIORNI_STANTII = 14
MIN_URN_PCT = 80.0  # copertura URN sugli atti normativi SG-*-G dell'anno


def main() -> int:
    files = sorted(ROOT.glob(CLEAN_GLOB))
    if not files:
        print(f"Nessun clean trovato in {CLEAN_GLOB}")
        return 1

    con = duckdb.connect()
    errori: list[str] = []

    for f in files:
        righe = con.execute(f"select count(*) from read_parquet('{f}')").fetchone()[0]
        if righe < MIN_RIGHE:
            errori.append(f"{f.name}: {righe} righe (minimo {MIN_RIGHE})")

        ultima = con.execute(
            f"select max(data_pubblicazione) from read_parquet('{f}')"
        ).fetchone()[0]
        if ultima is None:
            errori.append(f"{f.name}: nessuna data di pubblicazione")
        else:
            giorni = (date.today() - ultima).days
            if giorni > MAX_GIORNI_STANTII:
                errori.append(f"{f.name}: ultima pubblicazione {ultima} ({giorni} giorni fa)")

        normative, con_urn = con.execute(
            f"""select count(*), count(*) filter (where urn_normattiva <> '')
                from read_parquet('{f}')
                where serie = 'SG' and regexp_matches(id, '^[0-9]{{2}}G')"""
        ).fetchone()
        if normative:
            pct = 100.0 * con_urn / normative
            if pct < MIN_URN_PCT:
                errori.append(
                    f"{f.name}: URN {con_urn}/{normative} ({pct:.1f}%) sotto {MIN_URN_PCT}%"
                )
            print(f"{f.name}: {righe} righe · ultima {ultima} · URN {con_urn}/{normative}")
        else:
            errori.append(f"{f.name}: nessun atto normativo SG")

    con.close()

    if errori:
        for e in errori:
            print(f"ERRORE: {e}")
        return 1

    print("clean ok")
    return 0


if __name__ == "__main__":
    sys.exit(main())
