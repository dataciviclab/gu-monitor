#!/usr/bin/env python3
"""GU Monitor — Analytics: query DuckDB sul dataset parquet."""

import sys
from pathlib import Path

import duckdb


def main():
    data_dir = Path(__file__).parent.parent / "data"
    parquet_file = data_dir / "gu_acts.parquet"

    if not parquet_file.exists():
        print("Esegui prima to_parquet.py", file=sys.stderr)
        return 1

    con = duckdb.connect(":memory:")
    con.execute(f"CREATE TABLE atti AS SELECT * FROM read_parquet('{parquet_file}')")

    # ── 1. Riepilogo per serie ──────────────────────────────────────
    print("=" * 60)
    print("ATTI PER SERIE (30 giorni)")
    print("=" * 60)
    r = con.execute("""
        SELECT serie, COUNT(*) as n,
               COUNT(DISTINCT ente) as enti,
               COUNT(DISTINCT data_pubblicazione) as giorni
        FROM atti
        GROUP BY serie
        ORDER BY n DESC
    """).fetchall()
    print(f"  {'Serie':<6} {'Atti':>5} {'Enti':>5} {'Giorni':>6}")
    for row in r:
        print(f"  {row[0]:<6} {row[1]:>5} {row[2]:>5} {row[3]:>6}")

    # ── 2. Tipo atto globale ───────────────────────────────────────
    print(f"\n{'=' * 60}")
    print("TIPI DI ATTO")
    print("=" * 60)
    r = con.execute("""
        SELECT tipo_atto, COUNT(*) as n
        FROM atti
        GROUP BY tipo_atto
        ORDER BY n DESC
        LIMIT 15
    """).fetchall()
    for row in r:
        bar = "█" * (row[1] // 20)
        print(f"  {row[0]:<25} {row[1]:>5}  {bar}")

    # ── 3. Top enti ────────────────────────────────────────────────
    print(f"\n{'=' * 60}")
    print("TOP 20 ENTI PER VOLUME")
    print("=" * 60)
    r = con.execute("""
        SELECT ente, COUNT(*) as n
        FROM atti
        WHERE ente IS NOT NULL
        GROUP BY ente
        ORDER BY n DESC
        LIMIT 20
    """).fetchall()
    for i, row in enumerate(r, 1):
        print(f"  {i:2d}. {row[0][:55]:<55} {row[1]:>4}")

    # ── 4. Topic distribution ──────────────────────────────────────
    print(f"\n{'=' * 60}")
    print("TOPIC")
    print("=" * 60)
    r = con.execute("""
        WITH split_topics AS (
            SELECT UNNEST(string_split(topic_str, ',')) as topic
            FROM atti
            WHERE topic_str IS NOT NULL AND topic_str != ''
        )
        SELECT topic, COUNT(*) as n
        FROM split_topics
        WHERE topic IS NOT NULL AND topic != ''
        GROUP BY topic
        ORDER BY n DESC
    """).fetchall()
    for row in r:
        bar = "█" * (row[1] // 20)
        print(f"  {row[0]:<15} {row[1]:>5}  {bar}")

    # ── 5. Volume per giorno ───────────────────────────────────────
    print(f"\n{'=' * 60}")
    print("MEDIA ATTI PER GIORNO SETTIMANA")
    print("=" * 60)
    r = con.execute("""
        SELECT DAYNAME(data_pubblicazione) as giorno,
               COUNT(*) as totale,
               COUNT(DISTINCT data_pubblicazione) as giorni,
               ROUND(COUNT(*) * 1.0 / COUNT(DISTINCT data_pubblicazione), 0) as media
        FROM atti
        GROUP BY giorno
        ORDER BY media DESC
    """).fetchall()
    for row in r:
        bar = "█" * int(row[3] / 5)
        print(f"  {row[0]:<12} {row[3]:>5} atti/giorno  (tot: {row[1]})")

    # ── 6. Trend settimanale ───────────────────────────────────────
    print(f"\n{'=' * 60}")
    print("TREND SETTIMANALE")
    print("=" * 60)
    r = con.execute("""
        SELECT DATE_TRUNC('week', data_pubblicazione) as settimana,
               COUNT(*) as n
        FROM atti
        GROUP BY settimana
        ORDER BY settimana
    """).fetchall()
    for row in r:
        bar = "█" * (row[1] // 20)
        print(f"  {str(row[0])[:10]}  {row[1]:>5}  {bar}")

    # ── 7. Media atti per gazzetta ─────────────────────────────────
    print(f"\n{'=' * 60}")
    print("MEDIA ATTI PER GAZZETTA")
    print("=" * 60)
    r = con.execute("""
        SELECT serie,
               COUNT(DISTINCT gazzetta_numero) as n_gazzette,
               COUNT(*) as n_atti,
               ROUND(COUNT(*) * 1.0 / COUNT(DISTINCT gazzetta_numero), 1) as media
        FROM atti
        GROUP BY serie
        ORDER BY media DESC
    """).fetchall()
    for row in r:
        print(f"  {row[0]:<5} {row[3]:>6} atti/gazzetta  ({row[1]} gazzette, {row[2]} atti)")

    # ── 8. Enti per serie ──────────────────────────────────────────
    print(f"\n{'=' * 60}")
    print("ENTI PRINCIPALI PER SERIE")
    print("=" * 60)
    for serie in ["SG", "S1", "S2", "S3", "S4", "S5", "P2"]:
        r = con.execute("""
            SELECT ente, COUNT(*) as n
            FROM atti
            WHERE serie = ? AND ente IS NOT NULL
            GROUP BY ente
            ORDER BY n DESC
            LIMIT 3
        """, [serie]).fetchall()
        if r:
            print(f"\n  [{serie}]")
            for row in r:
                print(f"    {row[0][:50]:<50} {row[1]:>4}")

    con.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
