#!/usr/bin/env python3
"""Analisi completa del dataset GU Monitor."""

import duckdb

PARQUET = "data/gu_acts.parquet"
con = duckdb.connect(":memory:")
con.execute(f"CREATE TABLE a AS SELECT * FROM read_parquet('{PARQUET}')")


def q(sql, label=""):
    if label:
        print(f"\n{'=' * 60}")
        print(label)
        print("=" * 60)
    df = con.execute(sql).fetchdf()
    print(df.to_string(index=False))
    return df


# ── 1. Panoramica ────────────────────────────────────────────────────────────

q("""
    SELECT COUNT(*) AS righe_totali,
           COUNT(DISTINCT id || serie) AS atti_unici,
           COUNT(DISTINCT serie) AS n_serie,
           COUNT(DISTINCT ente) AS n_enti,
           COUNT(DISTINCT tipo_atto) AS n_tipi,
           COUNT(DISTINCT CAST(data_pubblicazione AS DATE)) AS n_giorni,
           COUNT(DISTINCT gazzetta_numero) AS n_gazzette,
           MIN(CAST(data_pubblicazione AS DATE)) AS prima_data,
           MAX(CAST(data_pubblicazione AS DATE)) AS ultima_data
    FROM a
""", "1. PANORAMICA GENERALE")

# ── 2. Distribuzione per serie ───────────────────────────────────────────────

q("""
    SELECT serie,
           COUNT(*) AS atti,
           COUNT(DISTINCT CAST(data_pubblicazione AS DATE)) AS giorni,
           COUNT(DISTINCT gazzetta_numero) AS gazzette,
           COUNT(DISTINCT ente) AS enti,
           COUNT(DISTINCT tipo_atto) AS tipi,
           ROUND(COUNT(*) * 100.0 / (SELECT COUNT(*) FROM a), 1) AS pct,
           ROUND(COUNT(*) * 1.0 / COUNT(DISTINCT CAST(data_pubblicazione AS DATE)), 1) AS atti_giorno,
           ROUND(COUNT(*) * 1.0 / COUNT(DISTINCT gazzetta_numero), 1) AS atti_gazzetta
    FROM a
    GROUP BY serie
    ORDER BY atti DESC
""", "2. DISTRIBUZIONE PER SERIE")

# ── 3. Top tipi di atto ─────────────────────────────────────────────────────

q("""
    SELECT tipo_atto,
           COUNT(*) AS atti,
           ROUND(COUNT(*) * 100.0 / (SELECT COUNT(*) FROM a), 1) AS pct,
           COUNT(DISTINCT serie) AS n_serie,
           COUNT(DISTINCT ente) AS n_enti
    FROM a
    GROUP BY tipo_atto
    ORDER BY atti DESC
""", "3. TIPI DI ATTO")

# ── 4. Top 25 enti ──────────────────────────────────────────────────────────

q("""
    SELECT ente,
           COUNT(*) AS atti,
           ROUND(COUNT(*) * 100.0 / (SELECT COUNT(*) FROM a), 1) AS pct,
           COUNT(DISTINCT serie) AS n_serie,
           COUNT(DISTINCT tipo_atto) AS n_tipi,
           STRING_AGG(DISTINCT serie, ', ' ORDER BY serie) AS serie_list
    FROM a
    WHERE ente IS NOT NULL
    GROUP BY ente
    ORDER BY atti DESC
    LIMIT 25
""", "4. TOP 25 ENTI")

# ── 5. Distribuzione topic ───────────────────────────────────────────────────

q("""
    WITH split_topics AS (
        SELECT UNNEST(string_split(topic_str, ',')) AS topic
        FROM a
        WHERE topic_str IS NOT NULL AND topic_str != ''
    )
    SELECT TRIM(topic) AS topic,
           COUNT(*) AS atti,
           ROUND(COUNT(*) * 100.0 / SUM(COUNT(*)) OVER(), 1) AS pct
    FROM split_topics
    WHERE TRIM(topic) != ''
    GROUP BY TRIM(topic)
    ORDER BY atti DESC
""", "5. DISTRIBUZIONE TOPIC")

# ── 6. Copertura topic per serie ─────────────────────────────────────────────

q("""
    WITH split_topics AS (
        SELECT serie, UNNEST(string_split(topic_str, ',')) AS topic
        FROM a
        WHERE topic_str IS NOT NULL AND topic_str != ''
    ),
    ranked AS (
        SELECT serie, TRIM(topic) AS topic, COUNT(*) AS atti,
               ROW_NUMBER() OVER (PARTITION BY serie ORDER BY COUNT(*) DESC) AS rk
        FROM split_topics
        WHERE TRIM(topic) != ''
        GROUP BY serie, TRIM(topic)
    )
    SELECT serie, topic, atti
    FROM ranked
    WHERE rk <= 3
    ORDER BY serie, atti DESC
""", "6. TOP 3 TOPIC PER SERIE")

# ── 7. Volume per giorno ────────────────────────────────────────────────────

q("""
    SELECT CAST(data_pubblicazione AS DATE) AS giorno,
           COUNT(*) AS atti,
           COUNT(DISTINCT serie) AS n_serie,
           COUNT(DISTINCT gazzetta_numero) AS gazzette
    FROM a
    GROUP BY giorno
    ORDER BY giorno
""", "7. VOLUME GIORNALIERO")

# ── 8. Media per giorno settimana ────────────────────────────────────────────

q("""
    SELECT DAYNAME(CAST(data_pubblicazione AS DATE)) AS giorno_sett,
           COUNT(*) AS totale,
           COUNT(DISTINCT CAST(data_pubblicazione AS DATE)) AS n_giorni,
           ROUND(COUNT(*) * 1.0 / COUNT(DISTINCT CAST(data_pubblicazione AS DATE)), 0) AS media
    FROM a
    GROUP BY giorno_sett
    ORDER BY media DESC
""", "8. MEDIA ATTI PER GIORNO SETTIMANA")

# ── 9. Top 10 enti per serie ────────────────────────────────────────────────

print(f"\n{'=' * 60}")
print("9. TOP 10 ENTI PER SERIE")
print("=" * 60)
for serie in ["SG", "S1", "S2", "S3", "S4", "S5", "P2"]:
    df = con.execute("""
        SELECT ente, COUNT(*) AS atti,
               STRING_AGG(DISTINCT tipo_atto, ', ' ORDER BY tipo_atto) AS tipi
        FROM a
        WHERE serie = ? AND ente IS NOT NULL
        GROUP BY ente
        ORDER BY atti DESC
        LIMIT 10
    """, [serie]).fetchdf()
    if not df.empty:
        print(f"\n  [{serie}]")
        for _, row in df.iterrows():
            print(f"    {row['atti']:>4}  {str(row['ente'])[:50]:<50}  [{row['tipi']}]")

# ── 10. Qualità dati ────────────────────────────────────────────────────────

q("""
    SELECT 'Righe totali' AS metrica, COUNT(*) AS valore FROM a
    UNION ALL
    SELECT 'Atti unici (id+serie)', COUNT(DISTINCT id || '||' || serie) FROM a
    UNION ALL
    SELECT 'ID duplicati', COUNT(*) - COUNT(DISTINCT id || '||' || serie) FROM a
    UNION ALL
    SELECT 'Con ente', COUNT(*) FROM a WHERE ente IS NOT NULL
    UNION ALL
    SELECT 'Senza ente', COUNT(*) FROM a WHERE ente IS NULL
    UNION ALL
    SELECT 'Con topic', COUNT(*) FROM a WHERE topic_str IS NOT NULL AND topic_str != ''
    UNION ALL
    SELECT 'Senza topic', COUNT(*) FROM a WHERE topic_str IS NULL OR topic_str = ''
    UNION ALL
    SELECT 'Con link', COUNT(*) FROM a WHERE link IS NOT NULL AND link != ''
""", "10. QUALITÀ DATI")

# ── 11. Gazzette voluminose ──────────────────────────────────────────────────

q("""
    SELECT gazzetta_numero AS n_gazz, serie,
           CAST(data_pubblicazione AS DATE) AS data,
           COUNT(*) AS atti,
           ROUND(COUNT(*) * 100.0 / (SELECT COUNT(*) FROM a), 2) AS pct_dataset
    FROM a
    WHERE gazzetta_numero IS NOT NULL
    GROUP BY gazzetta_numero, serie, data_pubblicazione
    HAVING COUNT(*) > 200
    ORDER BY atti DESC
""", "11. GAZZETTE CON PIÙ DI 200 ATTI (outlier)")

# ── 12. Diffusione enti tra serie ───────────────────────────────────────────

q("""
    WITH ente_stats AS (
        SELECT ente,
               COUNT(*) AS atti,
               COUNT(DISTINCT tipo_atto) AS n_tipi,
               COUNT(DISTINCT serie) AS n_serie,
               STRING_AGG(DISTINCT serie, ', ' ORDER BY serie) AS serie_list
        FROM a WHERE ente IS NOT NULL
        GROUP BY ente
    )
    SELECT
        CASE WHEN n_serie = 1 THEN '1 sola serie'
             WHEN n_serie BETWEEN 2 AND 3 THEN '2-3 serie'
             ELSE '4+ serie'
        END AS diffusione,
        COUNT(*) AS n_enti,
        SUM(atti) AS tot_atti,
        ROUND(AVG(n_tipi), 1) AS media_tipi
    FROM ente_stats
    GROUP BY diffusione
    ORDER BY diffusione
""", "12. ENTI: DIFFUSIONE TRA LE SERIE")

# ── 13. Trend settimanale ───────────────────────────────────────────────────

q("""
    SELECT DATE_TRUNC('week', CAST(data_pubblicazione AS DATE)) AS settimana,
           COUNT(*) AS atti,
           COUNT(DISTINCT CAST(data_pubblicazione AS DATE)) AS giorni,
           ROUND(COUNT(*) * 1.0 / COUNT(DISTINCT CAST(data_pubblicazione AS DATE)), 0) AS media_giorno
    FROM a
    GROUP BY settimana
    ORDER BY settimana
""", "13. TREND SETTIMANALE")

# ── 14. Heatmap serie x tipo (top 10) ───────────────────────────────────────

q("""
    WITH top_tipi AS (
        SELECT tipo_atto FROM a GROUP BY tipo_atto ORDER BY COUNT(*) DESC LIMIT 10
    )
    SELECT serie, tipo_atto, COUNT(*) AS atti
    FROM a
    WHERE tipo_atto IN (SELECT tipo_atto FROM top_tipi)
    GROUP BY serie, tipo_atto
    ORDER BY serie, atti DESC
""", "14. HEATMAP SERIE × TIPO ATTO (top 10)")

# ── 15. Enti monospecifici ──────────────────────────────────────────────────

q("""
    SELECT ente, COUNT(*) AS n_decreti
    FROM a
    WHERE tipo_atto = 'DECRETO' AND ente IS NOT NULL
    GROUP BY ente
    HAVING COUNT(DISTINCT tipo_atto) = 1
    ORDER BY n_decreti DESC
    LIMIT 15
""", "15. ENTI CHE PUBBLICANO SOLO DECRETI (top 15)")

con.close()
print(f"\n{'=' * 60}")
print("FINE ANALISI")
print("=" * 60)
