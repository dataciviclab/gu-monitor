#!/usr/bin/env python3
"""Verifica del clean pubblicato (guardia del build).

La cattura può fallire: quella è una condizione della fonte, e il job lo dice.
Il build invece non deve mai pubblicare un clean vuoto o incoerente restando
verde. Questo script è la guardia che il reusable esegue dopo `make run`.
"""

from __future__ import annotations

import sys
from datetime import date, timedelta
from pathlib import Path

import duckdb

ROOT = Path(__file__).parent.parent
CLEAN_GLOB = "out/data/clean/gu_atti/*/gu_atti_*_clean.parquet"

MIN_RIGHE = 1_000
MAX_GIORNI_STANTII = 14

# Latenza Normattiva: un atto appena pubblicato non è indicizzato subito.
# Oltre questa età, un atto `G` senza URN è un buco, non un ritardo.
ETA_URN_GIORNI = 7
MIN_URN_PCT_TOTALE = 95.0


def _conta(con, f: Path, sql: str) -> int:
    return con.execute(sql.format(f=f)).fetchone()[0]


def main() -> int:
    files = sorted(ROOT.glob(CLEAN_GLOB))
    if not files:
        print(f"Nessun clean trovato in {CLEAN_GLOB}")
        return 1

    con = duckdb.connect()
    errori: list[str] = []
    soglia = date.today() - timedelta(days=ETA_URN_GIORNI)

    for f in files:
        righe = _conta(con, f, "select count(*) from read_parquet('{f}')")
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

        # ── Ponte URN ───────────────────────────────────────────────────
        # È ciò che rende la serie G uno stream verso legal-graph. La
        # copertura è per età: i nuovi possono essere in ritardo su
        # Normattiva, i vecchi no.
        tot, con_urn = con.execute(
            f"""select count(*), count(*) filter (where urn_normattiva <> '')
                from read_parquet('{f}') where codice_genere = 'G'"""
        ).fetchone()
        if not tot:
            errori.append(f"{f.name}: nessun atto normativo (codice_genere = 'G')")
        else:
            pct = 100.0 * con_urn / tot
            if pct < MIN_URN_PCT_TOTALE:
                errori.append(
                    f"{f.name}: URN {con_urn}/{tot} ({pct:.1f}%) sotto {MIN_URN_PCT_TOTALE}%"
                )

            vecchi, vecchi_urn = con.execute(
                f"""select count(*), count(*) filter (where urn_normattiva <> '')
                    from read_parquet('{f}')
                    where codice_genere = 'G' and data_pubblicazione < DATE '{soglia}'"""
            ).fetchone()
            if vecchi and vecchi_urn != vecchi:
                errori.append(
                    f"{f.name}: {vecchi - vecchi_urn}/{vecchi} atti G più vecchi di "
                    f"{ETA_URN_GIORNI} giorni senza URN"
                )

            print(
                f"{f.name}: {righe} righe · ultima {ultima} · "
                f"URN {con_urn}/{tot} · vecchi {vecchi_urn}/{vecchi}"
            )

        # ── Invarianti di schema ────────────────────────────────────────
        # Impediscono di pubblicare una finestra "mista" (righe vecchie +
        # parser nuovo): senza, il rebuild dopo un cambio di schema resta
        # una buona intenzione.
        ente_p2 = _conta(
            con,
            f,
            """select count(*) from read_parquet('{f}')
               where serie in ('P2', 'S5') and ente is not null""",
        )
        if ente_p2:
            errori.append(f"{f.name}: {ente_p2} atti P2/S5 con ente valorizzato (è una rubrica)")

        senza_sezione = _conta(
            con,
            f,
            """select count(*) from read_parquet('{f}')
               where sezione is null and serie <> 'S3'""",
        )
        if senza_sezione:
            esempi = con.execute(
                f"""select id, serie from read_parquet('{f}')
                    where sezione is null and serie <> 'S3' limit 5"""
            ).fetchall()
            errori.append(
                f"{f.name}: {senza_sezione} atti senza sezione (rebuild mancante?) "
                f"— es. {esempi}"
            )

        # S3 scritto in positivo: oggi non ha rubrica nel markup. Se un giorno
        # ne avesse una, questa guardia diventa rossa e chiede di rileggerlo.
        s3_con_sezione = _conta(
            con,
            f,
            """select count(*) from read_parquet('{f}')
               where serie = 'S3' and sezione is not null""",
        )
        if s3_con_sezione:
            errori.append(
                f"{f.name}: {s3_con_sezione} atti S3 con sezione — il markup è cambiato, "
                "aggiornare parser e questa guardia"
            )

    con.close()

    if errori:
        for e in errori:
            print(f"ERRORE: {e}")
        return 1

    print("clean ok")
    return 0


if __name__ == "__main__":
    sys.exit(main())
