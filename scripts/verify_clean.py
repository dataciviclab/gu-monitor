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
STORE = ROOT / "data/gu_acts.parquet"
MART_DIR = ROOT / "out/data/mart/gu_atti"

MIN_RIGHE = 1_000
MAX_GIORNI_STANTII = 14

# Latenza Normattiva: un atto appena pubblicato non è indicizzato subito.
# Oltre questa età, un atto `G` senza URN è un buco, non un ritardo.
ETA_URN_GIORNI = 7
MIN_URN_PCT_TOTALE = 95.0


def _conta(con, f: Path, sql: str) -> int:
    return con.execute(sql.format(f=f)).fetchone()[0]


def anno_da_partizione(f: Path) -> int | None:
    """L'anno nella directory della partizione (`.../gu_atti/2024/...`)."""
    try:
        return int(f.parent.name)
    except ValueError:
        return None


def anno_da_richiedere(ultima_nello_store: date | None, oggi: date) -> int | None:
    """L'anno della partizione che oggi deve esistere, se c'è una ragione.

    Al rollover di gennaio lo store può non avere ancora nessun atto del nuovo
    anno: in quel caso non si pretende la partizione. Appena arriva il primo
    atto dell'anno nuovo, la partizione è dovuta — è il segnale che `years`
    non è stato aggiornato e il dataset ha smesso di crescere in silenzio.
    """
    if ultima_nello_store is None or ultima_nello_store.year < oggi.year:
        return None
    return oggi.year


def errore_partizione_mancante(
    partizioni: list[int], ultima_nello_store: date | None, oggi: date
) -> str | None:
    attesa = anno_da_richiedere(ultima_nello_store, oggi)
    if attesa is None or attesa in partizioni:
        return None
    return (
        f"partizione {attesa} assente: lo store ha già atti del {attesa} "
        f"(ultimo {ultima_nello_store}) — aggiornare `years` in dataset.yml"
    )


def minimo_righe(anno: int, oggi: date) -> int:
    """Un anno chiuso deve essere corposo; l'anno aperto, solo non vuoto.

    Con la soglia piena anche sull'anno aperto, i primi giorni di gennaio
    (poche decine di atti) farebbero fallire il build per una decina di giorni,
    e con lui la pubblicazione degli anni chiusi.
    """
    return MIN_RIGHE if anno < oggi.year else 1


MART_VOLUMI = ("mart_atti_per_serie_giorno", "mart_atti_per_tipo")
MART_URN = "mart_normativi_urn"

# Colonne che definiscono il gruppo di ogni mart di volume: una riga per
# combinazione distinta nel clean.
GRUPPI = {
    "mart_atti_per_serie_giorno": "serie, data_pubblicazione",
    "mart_atti_per_tipo": "tipo_atto",
}


def controlla_mart(
    con, clean: Path, marts: Path, anno: int, righe: int, righe_urn: int
) -> list[str]:
    """I mart sono derivazioni del clean: il loro volume e i loro gruppi devono
    tornare esatti.

    Sostituisce i floor di riga che stavano in `dataset.yml`, dove valevano per
    ogni partizione e avrebbero bocciato una partizione di gennaio (due giorni
    di Gazzetta non fanno 100 righe di serie×giorno, né 10 tipi). Un invariante
    esatto vale per qualunque giorno:

    - la somma degli atti dei due mart di volume è il numero di atti del clean;
    - il numero di righe è il numero di gruppi distinti nel clean — la somma
      resta giusta anche se un `GROUP BY` perde una colonna e collassa i gruppi,
      il conteggio no;
    - il mart URN ha una riga per ogni atto con URN.
    """
    errori: list[str] = []
    for nome in MART_VOLUMI:
        f = marts / f"{nome}.parquet"
        if not f.exists():
            errori.append(f"{nome}: mart assente per il {anno}")
            continue
        tot = con.execute(
            f"select coalesce(sum(atti), 0) from read_parquet('{f}')"
        ).fetchone()[0]
        if tot != righe:
            errori.append(f"{nome}: somma atti {tot}, clean {righe} (anno {anno})")

    # Granularità: una riga per gruppo. Un GROUP BY che perde una colonna
    # mantiene la somma e dimezza le righe — questo confronto lo vede.
    for nome, chiavi in GRUPPI.items():
        f = marts / f"{nome}.parquet"
        if not f.exists():
            continue  # già segnalato sopra
        attese = con.execute(
            f"select count(*) from (select distinct {chiavi} from read_parquet('{clean}'))"
        ).fetchone()[0]
        got = con.execute(f"select count(*) from read_parquet('{f}')").fetchone()[0]
        if got != attese:
            errori.append(f"{nome}: {got} righe, {attese} gruppi nel clean (anno {anno})")

    f = marts / f"{MART_URN}.parquet"
    if not f.exists():
        errori.append(f"{MART_URN}: mart assente per il {anno}")
    else:
        tot = con.execute(f"select count(*) from read_parquet('{f}')").fetchone()[0]
        if tot != righe_urn:
            errori.append(f"{MART_URN}: {tot} righe, atti con URN {righe_urn} (anno {anno})")
    return errori


def _ultima_nello_store(con) -> date | None:
    if not STORE.exists():
        return None
    return con.execute(
        f"select max(try_cast(data_pubblicazione as date)) from read_parquet('{STORE}')"
    ).fetchone()[0]


def main() -> int:
    files = sorted(ROOT.glob(CLEAN_GLOB))
    if not files:
        print(f"Nessun clean trovato in {CLEAN_GLOB}")
        return 1

    con = duckdb.connect()
    errori: list[str] = []
    oggi = date.today()
    soglia = oggi - timedelta(days=ETA_URN_GIORNI)
    anno_corrente = oggi.year

    # Le partizioni si leggono dai nomi delle directory: sono l'etichetta del
    # dataset pubblicato, non un'inferenza sui dati.
    partizioni: list[int] = []
    for f in files:
        anno_f = anno_da_partizione(f)
        if anno_f is None:
            errori.append(f"{f.parent.name}: partizione non-anno ({f})")
        else:
            partizioni.append(anno_f)

    ultima_store = _ultima_nello_store(con)
    if ultima_store is None:
        print(f"store assente ({STORE}): partizione dell'anno corrente non verificata")
    mancante = errore_partizione_mancante(partizioni, ultima_store, oggi)
    if mancante:
        errori.append(mancante)

    for f in files:
        anno = anno_da_partizione(f) or anno_corrente

        righe = _conta(con, f, "select count(*) from read_parquet('{f}')")
        minimo = minimo_righe(anno, oggi)
        if righe < minimo:
            errori.append(f"{f.name}: {righe} righe (minimo {minimo})")

        ultima = con.execute(
            f"select max(data_pubblicazione) from read_parquet('{f}')"
        ).fetchone()[0]
        if ultima is None:
            errori.append(f"{f.name}: nessuna data di pubblicazione")
        elif anno == anno_corrente:
            # Solo l'anno aperto può essere "stantio": un anno chiuso finisce
            # per definizione al 31/12, e pretenderlo fresco vorrebbe dire non
            # poter pubblicare la storia.
            giorni = (oggi - ultima).days
            if giorni > MAX_GIORNI_STANTII:
                errori.append(f"{f.name}: ultima pubblicazione {ultima} ({giorni} giorni fa)")
        elif ultima.year != anno:
            # Invariante sull'etichetta: la partizione `2024` contiene solo il
            # 2024. Oggi è garantita dal filtro in clean.sql; se quel filtro
            # sparisse, il build resterebbe verde e questo lo direbbe.
            errori.append(
                f"{f.name}: anno chiuso ma ultima pubblicazione {ultima} fuori dal {anno}"
            )

        # ── Mart: derivazione esatta del clean ───────────────────────────
        righe_urn = _conta(
            con,
            f,
            "select count(*) filter (where urn_normattiva <> '') from read_parquet('{f}')",
        )
        errori.extend(
            controlla_mart(con, f, MART_DIR / str(anno), anno, righe, righe_urn)
        )

        # ── Ponte URN ───────────────────────────────────────────────────
        # È ciò che rende la serie G uno stream verso legal-graph. La
        # copertura è per età: i nuovi possono essere in ritardo su
        # Normattiva, i vecchi no.
        tot, con_urn = con.execute(
            f"""select count(*), count(*) filter (where urn_normattiva <> '')
                from read_parquet('{f}') where codice_genere = 'G'"""
        ).fetchone()
        if not tot:
            # In un anno chiuso zero normativi è implausibile (226 · 219 · 230):
            # è un buco. Nell'anno aperto i primi giorni possono non averne.
            if anno < oggi.year:
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
