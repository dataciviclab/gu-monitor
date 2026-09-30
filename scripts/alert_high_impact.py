#!/usr/bin/env python3
"""GU Monitor — Alert atti ad alto impatto (ultime 24 ore).

Filtra gli atti pubblicati nelle ultime 24 ore e notifica:
1. Riepilogo in $GITHUB_STEP_SUMMARY
2. GitHub Issue se ci sono atti priorità ALTO

Usage:
    python scripts/alert_high_impact.py
"""

import argparse
import os
import subprocess
import sys
from datetime import date
from pathlib import Path

import duckdb

QUERY = """
WITH base AS (
  SELECT 
    CAST(data_pubblicazione AS DATE) as data_pub,
    data_pubblicazione as data_raw,
    tipo_atto,
    COALESCE(ente, 'N/D') as ente,
    REGEXP_REPLACE(titolo, '\\s+', ' ') as titolo,
    COALESCE(topic_str, '') as topic_str,
    link,
    CASE 
      WHEN tipo_atto = 'DECRETO-LEGGE' THEN 10
      WHEN tipo_atto = 'LEGGE' THEN 9
      ELSE 0
    END + 
    CASE 
      WHEN ente LIKE '%PRESIDENZA DEL CONSIGLIO%' THEN 4
      WHEN ente LIKE '%ECONOMIA%' OR ente LIKE '%FINANZE%' THEN 3
      WHEN ente LIKE '%INNOVAZIONE%' OR ente LIKE '%AGID%' THEN 3
      WHEN ente LIKE '%MINISTERO%' AND tipo_atto IN ('LEGGE', 'DECRETO-LEGGE') THEN 2
      WHEN ente = 'N/D' AND tipo_atto IN ('LEGGE', 'DECRETO-LEGGE') THEN 1
      ELSE 0
    END +
    CASE 
      WHEN topic_str LIKE '%pnrr%' THEN 3
      WHEN topic_str LIKE '%fisco%' THEN 2
      ELSE 0
    END AS score
  FROM read_parquet('{parquet}')
  WHERE CAST(data_pubblicazione AS DATE) = CURRENT_DATE
    AND titolo IS NOT NULL AND titolo != ''
    AND tipo_atto IN ('LEGGE', 'DECRETO-LEGGE')
    AND COALESCE(ente, '') NOT LIKE '%REGIONE%'
    AND COALESCE(ente, '') NOT LIKE '%PROVINCIA%'
    AND titolo NOT LIKE '%REGIONALE%'
)
SELECT 
  CASE WHEN score >= 13 THEN 'ALTO' WHEN score >= 10 THEN 'MEDIO' ELSE 'BASSO' END as priorita,
  score, data_raw, tipo_atto, ente, titolo, topic_str, link
FROM base
WHERE score >= {threshold}
ORDER BY score DESC
"""


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--threshold", type=int, default=9)
    args = parser.parse_args()

    repo = Path(__file__).parent.parent
    parquet = repo / "data" / "gu_acts.parquet"
    if not parquet.exists():
        print("Esegui prima to_parquet.py", file=sys.stderr)
        return 1

    con = duckdb.connect(":memory:")
    rows = con.execute(
        QUERY.format(parquet=str(parquet.resolve()), threshold=args.threshold)
    ).fetchall()
    con.close()

    if not rows:
        print("Nessun nuovo atto ad alto impatto oggi.")
        # Step summary comunque
        if path := os.environ.get("GITHUB_STEP_SUMMARY"):
            with open(path, "a") as f:
                f.write("## GU Alert — Nessun nuovo atto ad alto impatto oggi\n")
        return 0

    stats = {}
    for r in rows:
        stats[r[0]] = stats.get(r[0], 0) + 1
    alto = stats.get("ALTO", 0)

    # Step Summary
    if path := os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(path, "a") as f:
            f.write(f"## GU Alert — {len(rows)} nuovi atti oggi\n\n")
            f.write("| Priorità | N |\n|---|---|\n")
            for p in ["ALTO", "MEDIO", "BASSO"]:
                if p in stats:
                    f.write(f"| {p} | {stats[p]} |\n")
            f.write("\n")
            for priorita, score, data, tipo, ente, titolo, topic, link in rows:
                if priorita == "ALTO":
                    f.write(f"- 🔴 **{titolo[:80]}** (score={score})\n")
                    f.write(f"  - {ente[:60]}\n")

    # GitHub Issue solo se ALTO
    if alto > 0 and os.environ.get("GH_TOKEN"):
        atti_alto = [r for r in rows if r[0] == "ALTO"]
        today = date.today().isoformat()
        body = [f"## Nuovi atti ad alto impatto — {today}", ""]
        for _, score, data, tipo, ente, titolo, topic, link in atti_alto:
            body.append(f"### {titolo[:100]}")
            body.append(f"- **Score**: {score} | **Ente**: {ente[:70]}")
            if link:
                body.append(f"- [Link GU]({link})")
            body.append("")
        body.append("*Generato automaticamente da gu-monitor*")
        
        r = subprocess.run(
            ["gh", "issue", "create",
             "--title", f"[GU Alert] {alto} nuovi atti ad alto impatto - {today}",
             "--body", "\n".join(body),
             "--label", "gu-alert"],
            capture_output=True, text=True
        )
        if r.returncode == 0:
            print(f"Issue creata: {r.stdout.strip()}")
        else:
            print(f"Errore issue: {r.stderr}", file=sys.stderr)

    print(f"Nuovi atti oggi: {stats}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
