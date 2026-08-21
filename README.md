# GU Monitor

**La Gazzetta Ufficiale italiana monitorata in tempo reale: cosa decide lo Stato, quando lo decide, chi lo decide.**

La Gazzetta Ufficiale è il diario ufficiale dello Stato italiano. Ogni legge, ogni decreto, ogni bando di concorso passa da qui. Ma nessuno la monitora sistematicamente.

Questo progetto lo fa: **4.330 atti in 30 giorni**, 7 serie, ~500 enti, tutto interrogabile.

[![Daily Update](https://github.com/dataciviclab/gu-monitor/actions/workflows/daily-update.yml/badge.svg)](https://github.com/dataciviclab/gu-monitor/actions/workflows/daily-update.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

---

## Cosa puoi scoprire

### 🏥 Quali farmaci entra (o esce) dal SSN

L'AIFA pubblica ogni giorno nella Gazzetta: **338 atti in 30 giorni**, di cui 128 comunicati su medicinali. Monitorare la serie SG significa sapere in tempo reale quali farmaci ottengono l'autorizzazione all'immissione in commercio.

### ⚖️ Quali bandi pubblici sono attivi

La serie Concorsi (S4) pubblica **1.026 atti in 30 giorni**: bandi di selezione, concorsi pubblici, graduatorie. Ogni università, ogni ASL, ogni comune italiano pubblica qui.

### 🇪🇺 Cosa decide l'Unione Europea

La serie UE (S2) contiene regolamenti, decisioni PESC (sanzioni), dazi antidumping. **262 atti in 30 giorni**, quasi tutti misure che impattano l'Italia.

### ⚖️ Quali tribunali sono più attivi

La Parte II (P2) è un database giudiziario pubblico: **1.734 atti in 30 giorni**, di cui 49% notifiche da tribunali italiani. Milano (28), Firenze (24), Bologna (22) sono i più produttivi.

---

## Numeri chiave

| Metrica | Valore |
|---|---|
| Atti totali (30gg) | **4.330** |
| Serie monitorate | **7** |
| Enti rilevati | **~500** |
| Tipi di atto | **20** |
| Topic classificati | **14** |
| Media atti/giorno | **177** |
| Peak day | **Martedì (283 atti)** |

---

## Dataset

Il cuore è `data/gu_acts.parquet`: un singolo file Parquet con tutti gli atti degli ultimi 30 giorni.

| Colonna | Tipo | Descrizione |
|---|---|---|
| `id` | VARCHAR | Codice atto (es. `26G00165`) |
| `serie` | VARCHAR | SG / S1 / S2 / S3 / S4 / S5 / P2 |
| `gazzetta_numero` | VARCHAR | Numero della pubblicazione |
| `data_pubblicazione` | DATE | Data di pubblicazione |
| `titolo` | VARCHAR | Titolo/descrizione dell'atto |
| `tipo_atto` | VARCHAR | LEGGE / DECRETO / REGOLAMENTO / etc |
| `ente` | VARCHAR | Ente emittente |
| `link` | VARCHAR | URL permanente (ELI o PDF) |
| `topic_str` | VARCHAR | Topic classificati |

---

## Come si usa

### Via DuckDB

```sql
-- Quali enti pubblicano più decreti?
SELECT ente, COUNT(*) AS n
FROM 'data/gu_acts.parquet'
WHERE tipo_atto = 'DECRETO' AND ente IS NOT NULL
GROUP BY ente ORDER BY n DESC;

-- Atti per topic
SELECT UNNEST(string_split(topic_str, ',')) AS topic, COUNT(*) AS n
FROM 'data/gu_acts.parquet'
WHERE topic_str != ''
GROUP BY topic ORDER BY n DESC;

-- Media atti per gazzetta
SELECT serie,
       COUNT(DISTINCT gazzetta_numero) AS n_gazzette,
       COUNT(*) AS n_atti,
       ROUND(COUNT(*) * 1.0 / COUNT(DISTINCT gazzetta_numero), 1) AS media
FROM 'data/gu_acts.parquet'
GROUP BY serie ORDER BY media DESC;
```

### Via script

```bash
pip install -r requirements.txt

# Fetch storico 30gg
python scripts/scrape_30gg.py

# Converti in Parquet
python scripts/to_parquet.py

# Analytics
python scripts/analytics.py
```

---

## Automazione

Il workflow GitHub Actions `daily-update.yml` esegue ogni giorno alle 06:00 UTC:

1. Scraping archivio 30gg (tutte le 7 serie)
2. Conversione in Parquet
3. Commit automatico se ci sono novità

---

## Struttura

```
gu-monitor/
├── .github/workflows/
│   └── daily-update.yml      # Cron giornaliero
├── scripts/
│   ├── fetch_rss.py          # RSS → JSON
│   ├── classify.py           # Enrich: ente, tipo, topic
│   ├── scrape_30gg.py        # Scraper archivio 30gg
│   ├── to_parquet.py         # JSON → Parquet
│   └── analytics.py          # Report DuckDB
├── tests/
│   └── test_basic.py         # 10 test
├── data/
│   └── gu_acts.parquet       # Dataset finale
└── _local/
    └── PLAN.md               # Piano sperimentale
```

---

## Fonte dati

- **RSS**: `https://www.gazzettaufficiale.it/rss/{serie}` (snapshot attuale)
- **Archivio 30gg**: `https://www.gazzettaufficiale.it/30giorni/{slug}` (storico mese)
- **Serie**: SG (Serie Generale), S1 (Corte Cost.), S2 (UE), S3 (Regioni), S4 (Concorsi), S5 (Contratti), P2 (Parte II)

---

## License

MIT
