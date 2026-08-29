# GU Monitor

**La Gazzetta Ufficiale italiana monitorata in tempo reale: cosa decide lo Stato, quando lo decide, chi lo decide.**

La Gazzetta Ufficiale è il diario ufficiale dello Stato italiano. Ogni legge, ogni decreto, ogni bando di concorso passa da qui. Ma nessuno la monitora sistematicamente.

Questo progetto lo fa: **2.784 atti unici**, 7 serie, 832 enti, 21 tipi di atto, 16 topic, tutto interrogabile.

[![CI](https://github.com/dataciviclab/gu-monitor/actions/workflows/ci.yml/badge.svg)](https://github.com/dataciviclab/gu-monitor/actions/workflows/ci.yml)
[![Daily Update](https://github.com/dataciviclab/gu-monitor/actions/workflows/daily-update.yml/badge.svg)](https://github.com/dataciviclab/gu-monitor/actions/workflows/daily-update.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

---

## Dashboard

La dashboard Streamlit mostra in tempo reale cosa pubblica lo Stato italiano.

```bash
# Avvio locale
pip install -r requirements-dashboard.txt
streamlit run app.py
```

Oppure con Docker:

```bash
docker build -t gu-monitor .
docker run -p 8501:8501 gu-monitor
```

---

## Numeri chiave

| Metrica | Valore |
|---|---|
| Atti totali | **2.784** |
| Serie monitorate | **7** |
| Enti rilevati | **832** |
| Tipi di atto | **21** |
| Topic classificati | **16** |
| Copertura topic | **64%** |
| Peak day | **Martedì (141 atti/giorno)** |

---

## Dataset

Il cuore è `data/gu_acts.parquet`: un singolo file Parquet con tutti gli atti unici degli ultimi 30 giorni. Chiave: `(id, link)`.

| Colonna | Tipo | Descrizione |
|---|---|---|
| `id` | VARCHAR | Codice atto (es. `26G00165`) |
| `serie` | VARCHAR | SG / S1 / S2 / S3 / S4 / S5 / P2 |
| `gazzetta_numero` | VARCHAR | Numero della pubblicazione |
| `data_pubblicazione` | DATE | Data di pubblicazione |
| `titolo` | VARCHAR | Titolo/descrizione dell'atto |
| `tipo_atto` | VARCHAR | LEGGE / DECRETO / CONCORSO / etc (19 tipi) |
| `ente` | VARCHAR | Ente emittente |
| `link` | VARCHAR | URL permanente (ELI o PDF) |
| `topic_str` | VARCHAR | Topic classificati (17 topic) |

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

# Converti in Parquet (dedup su id+link)
python scripts/to_parquet.py

# Analytics
python scripts/analytics.py

# Analisi completa
python scripts/analyze.py
```

---

## Automazione

Il workflow GitHub Actions `daily-update.yml` esegue ogni giorno alle 06:00 UTC:

1. Scraping archivio 30gg (tutte le 7 serie)
2. Conversione in Parquet (dedup su id+link)
3. Commit automatico se ci sono novità

---

## Struttura

```
gu-monitor/
├── .github/workflows/
│   ├── ci.yml                # CI: lint + test
│   └── daily-update.yml      # Cron giornaliero
├── .streamlit/
│   └── config.toml           # Tema dashboard
├── scripts/
│   ├── fetch_rss.py          # RSS → JSON
│   ├── classify.py           # Enrich: ente, tipo, topic
│   ├── scrape_30gg.py        # Scraper archivio 30gg
│   ├── to_parquet.py         # JSON → Parquet
│   ├── analytics.py          # Report DuckDB
│   └── analyze.py            # Analisi completa
├── tests/
│   └── test_basic.py         # 10 test
├── data/
│   └── gu_acts.parquet       # Dataset (2.296 atti unici)
├── app.py                    # Dashboard Streamlit
├── Dockerfile                # Container deploy
├── requirements.txt          # Core deps
├── requirements-dashboard.txt # Dashboard deps
├── pyproject.toml            # Project config
├── dataset.yml               # Schema
├── schema.md                 # Documentazione schema
└── README.md
```

---

## Topic

| Topic | Descrizione |
|---|---|
| giustizia | Tribunali, notifiche, sentenze, eredità |
| lavoro | Concorsi, borse di ricerca, impiego |
| business | Società, assemblee, cooperative |
| europa | Regolamenti UE, decisioni PESC |
| fisco | Fiscale, tributario, bilancio |
| governo_locale | Regioni, province, comuni, concessioni |
| sanita | Farmaci, sanitario, ospedaliero |
| istruzione | Università, ricerca, scuola |
| sicurezza | Polizia, carabinieri |
| ambiente | Ecologia, rifiuti, bonifica |
| energia | Elettricità, gas, fotovoltaico |
| agricoltura | Agricoltura, pesca, alimentare |
| edilizia | Edilizia, immobiliare, catasto |
| trasporti | Autostrade, ferrovie, porti |
| appalti | Gare, contratti pubblici |
| pnrr | PNRR, Next Generation EU |
| sanita_farmaci | Autorizzazioni immissione commercio |

---

## Fonte dati

- **RSS**: `https://www.gazzettaufficiale.it/rss/{serie}` (snapshot attuale)
- **Archivio 30gg**: `https://www.gazzettaufficiale.it/30giorni/{slug}` (storico mese)
- **Serie**: SG (Serie Generale), S1 (Corte Cost.), S2 (UE), S3 (Regioni), S4 (Concorsi), S5 (Contratti), P2 (Parte II)

---

## License

MIT
