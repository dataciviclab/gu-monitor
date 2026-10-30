#!/usr/bin/env python3
"""GU Monitor — Cattura incrementale guidata dal watermark.

Non esiste più uno stato per pubblicazione (`processed.json`): l'unica cosa che
serve sapere è **fin dove siamo arrivati**, cioè la data di pubblicazione più
recente nell'event log. Da lì si chiede all'archivio annuale tutto ciò che manca.

Proprietà:
- idempotente: rieseguirla non cambia nulla (l'upsert è per `id` in to_parquet);
- auto-riparante: dopo un fermo recupera l'intero buco, senza job dedicati;
- verificabile: confronta le pubblicazioni attese con quelle scaricate.

Uso:
    python scripts/capture.py                       # incrementale
    python scripts/capture.py --dry-run             # cosa scaricherebbe
    python scripts/capture.py --lookback-days 400   # primo caricamento
"""

from __future__ import annotations

import argparse
import json
import random
import sys
import time
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from gu_source import (  # noqa: E402
    SERIE,
    atti_da_html,
    elenco_30gg,
    elenco_archivio,
    fetch,
    url_dettaglio,
)

MAX_RICHIESTE = 400  # guardia: un bug non deve diventare un blocco IP


def watermark(store: Path) -> date | None:
    """Data di pubblicazione più recente già nell'event log."""
    if not store.exists():
        return None
    import duckdb

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


def inizio_finestra(
    wm: date | None, oggi: date, overlap: int = 3, lookback: int = 30
) -> date:
    """Da dove ripartire la cattura.

    Con watermark: si torna indietro di `overlap` giorni, perché una
    pubblicazione può arrivare in ritardo o essere corretta.
    Senza event log: si parte da `lookback` giorni fa.
    """
    if wm is None:
        return oggi - timedelta(days=lookback)
    return wm - timedelta(days=overlap)


def anni_da_scandire(da: date, a: date) -> list[int]:
    return list(range(da.year, a.year + 1))


def seleziona_pubblicazioni(pubs: list[dict], da: date) -> list[dict]:
    """Tiene solo le pubblicazioni da `da` in poi, dedup per (data, numero)."""
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


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--store", default=None, help="event log (default data/gu_acts.parquet)")
    ap.add_argument("--output", default=None, help="delta JSON (default data/gu_atti_delta.json)")
    ap.add_argument("--overlap", type=int, default=3, help="giorni di sovrapposizione sul watermark")
    ap.add_argument("--lookback-days", type=int, default=30, help="finestra se l'event log non esiste")
    ap.add_argument("--sleep", type=float, default=0.5)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    data_dir = Path(__file__).parent.parent / "data"
    data_dir.mkdir(exist_ok=True)
    store = Path(args.store) if args.store else data_dir / "gu_acts.parquet"
    output = Path(args.output) if args.output else data_dir / "gu_atti_delta.json"

    oggi = date.today()
    wm = watermark(store)
    da = inizio_finestra(wm, oggi, args.overlap, args.lookback_days)
    anni = anni_da_scandire(da, oggi)

    print(f"Watermark: {wm or 'nessuno (primo caricamento)'}")
    print(f"Finestra:  dal {da} a oggi ({oggi}) · anni {anni}")

    delta: list[dict] = []
    visti_id: set[str] = set()
    attese = 0
    scaricate = 0
    fallite: list[tuple[str, str, str]] = []
    richieste = 0

    for serie in SERIE:
        if richieste >= MAX_RICHIESTE:
            print(f"  guardia raggiunta ({MAX_RICHIESTE} richieste): stop")
            break

        try:
            pubs = []
            for anno in anni:
                pubs.extend(elenco_archivio(serie, anno))
                richieste += 1
            # La finestra 30gg copre il caso in cui l'archivio annuale sia
            # aggiornato con qualche ora di ritardo.
            pubs.extend(elenco_30gg(serie))
            richieste += 1
        except Exception as e:  # noqa: BLE001
            print(f"[{serie}] elenco non disponibile: {e}")
            fallite.append((serie, "elenco", str(e)))
            continue

        da_fare = seleziona_pubblicazioni(pubs, da)
        attese += len(da_fare)
        print(f"[{serie}] {len(da_fare)} pubblicazioni da scaricare")

        if args.dry_run:
            continue

        for i, pub in enumerate(da_fare, 1):
            if richieste >= MAX_RICHIESTE:
                fallite.append((serie, pub["numero"], "guardia richieste"))
                break
            try:
                atti = atti_da_html(fetch(url_dettaglio(serie, pub)), serie, pub["numero"], pub["data"])
                richieste += 1
                scaricate += 1
                for a in atti:
                    if a["id"] not in visti_id:
                        visti_id.add(a["id"])
                        delta.append(a)
                print(f"  [{i}/{len(da_fare)}] n°{pub['numero']} del {pub['data']}: {len(atti)} atti")
                time.sleep(args.sleep + random.uniform(0, 0.2))
            except Exception as e:  # noqa: BLE001
                print(f"  [{i}/{len(da_fare)}] n°{pub['numero']} ERRORE: {e}")
                fallite.append((serie, pub["numero"], str(e)))

    print("\n" + "=" * 50)
    print(f"Pubblicazioni attese:     {attese}")
    print(f"Pubblicazioni scaricate:  {scaricate}")
    print(f"Atti nel delta:           {len(delta)}")
    print(f"Richieste HTTP:           {richieste}")

    if args.dry_run:
        return 0

    output.write_text(json.dumps(delta, ensure_ascii=False), encoding="utf-8")
    print(f"Salvato: {output}")

    if fallite:
        print(f"\n{len(fallite)} errori:")
        for serie, numero, err in fallite[:20]:
            print(f"  [{serie}] {numero}: {err}")
        # Un errore parziale è un guasto della fonte: il run deve essere rosso,
        # ma il delta raccolto viene comunque scritto e applicato.
        return 1

    if attese != scaricate:
        print(f"\nERRORE: attese {attese}, scaricate {scaricate} — buco nella cattura")
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
