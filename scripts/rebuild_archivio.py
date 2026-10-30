#!/usr/bin/env python3
"""GU Monitor — Ricostruzione da archivio per anno.

Il collector giornaliero (capture.py) recupera solo le pubblicazioni che mancano.
Questo script rifà un anno intero: serve per lo storico e per correggere gli atti
già salvati con un parser vecchio.

Uso:
    python scripts/rebuild_archivio.py --anno 2026
    python scripts/rebuild_archivio.py --anno 2026 --limit 2   # smoke test
    python scripts/rebuild_archivio.py --anno 2026 --serie SG S4
"""

from __future__ import annotations

import argparse
import json
import random
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from gu_source import SERIE, atti_da_html, elenco_archivio, fetch, url_dettaglio  # noqa: E402


def carica_checkpoint(path: Path) -> list[dict]:
    """Legge il JSONL di ripresa: una riga per gazzetta già processata."""
    righe: list[dict] = []
    if not path.exists():
        return righe
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            righe.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return righe


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--anno", type=int, default=None, help="un anno (es. 2026)")
    ap.add_argument("--anni", default=None, help="intervallo, es. 2019-2025")
    ap.add_argument("--serie", nargs="*", default=None, help="default: tutte")
    ap.add_argument("--limit", type=int, default=0, help="max pubblicazioni per serie (0 = tutte)")
    ap.add_argument("--sleep", type=float, default=0.6, help="pausa tra richieste (secondi)")
    ap.add_argument("--out", default=None, help="JSON finale (default data/gu_atti_rebuild_<anno>.json)")
    args = ap.parse_args()

    anni: list[int]
    if args.anni:
        da, a = args.anni.split("-")
        anni = list(range(int(da), int(a) + 1))
    elif args.anno:
        anni = [args.anno]
    else:
        ap.error("serve --anno oppure --anni")

    for anno in anni:
        codice = run_anno(anno, args)
        if codice != 0:
            return codice
    return 0


def run_anno(anno: int, args) -> int:
    data_dir = Path(__file__).parent.parent / "data"
    data_dir.mkdir(exist_ok=True)
    checkpoint = data_dir / f"_rebuild_{anno}.jsonl"
    out_file = (
        Path(args.out) if args.out and len(getattr(args, "anni", None) or "") == 0
        else data_dir / f"gu_atti_rebuild_{anno}.json"
    )

    serie = args.serie or list(SERIE)
    righe = carica_checkpoint(checkpoint)
    fatte = {(r["serie"], r["numero"]) for r in righe}
    gia_fatte = len(fatte)

    with checkpoint.open("a", encoding="utf-8") as fh:
        for s in serie:
            try:
                pubs = elenco_archivio(s, anno)
            except Exception as e:  # noqa: BLE001
                print(f"[{anno}][{s}] elenco non disponibile: {e}")
                continue
            if args.limit:
                print(f"[{anno}][{s}] {len(pubs)} pubblicazioni (limito a {args.limit})")
                pubs = pubs[: args.limit]
            else:
                print(f"[{anno}][{s}] {len(pubs)} pubblicazioni")

            for i, pub in enumerate(pubs, 1):
                key = (s, pub["numero"])
                if key in fatte:
                    continue
                try:
                    atti = atti_da_html(fetch(url_dettaglio(s, pub)), s, pub["numero"], pub["data"])
                except Exception as e:  # noqa: BLE001
                    print(f"  [{anno}][{s} n°{pub['numero']}] ERRORE: {e}")
                    continue

                fh.write(json.dumps(
                    {"serie": s, "numero": pub["numero"], "data": pub["data"], "atti": atti},
                    ensure_ascii=False,
                ) + "\n")
                fh.flush()
                fatte.add(key)
                if i % 20 == 0 or i == len(pubs):
                    print(f"  [{anno}][{s}] {i}/{len(pubs)} n°{pub['numero']} ({len(atti)} atti)")
                time.sleep(args.sleep + random.uniform(0, 0.2))

    # Aggrega il checkpoint (riletto: può essere cresciuto in questo run)
    visti: set[str] = set()
    atti_totali: list[dict] = []
    for riga in carica_checkpoint(checkpoint):
        for a in riga.get("atti", []):
            act_id = a.get("id", "")
            if not act_id or act_id in visti:
                continue
            visti.add(act_id)
            atti_totali.append(a)

    atti_totali.sort(key=lambda a: (a.get("data_pubblicazione", ""), a.get("id", "")))
    out_file.write_text(json.dumps(atti_totali, ensure_ascii=False), encoding="utf-8")

    print("\n" + "=" * 50)
    print(f"[{anno}] gazzette: {len(fatte)} (nuove: {len(fatte) - gia_fatte}) · atti: {len(atti_totali)}")
    for s in serie:
        n = sum(1 for a in atti_totali if a.get("serie") == s)
        print(f"  {s}: {n}")
    print(f"Salvato: {out_file}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
