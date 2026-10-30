# GU Monitor

**La Gazzetta Ufficiale italiana monitorata in tempo reale: cosa decide lo Stato, quando lo decide, chi lo decide.**

La Gazzetta Ufficiale è il diario ufficiale dello Stato italiano. Ogni legge, ogni decreto, ogni bando di concorso passa da qui. Ma nessuno la monitora sistematicamente.

Questo progetto lo fa: **25.711 atti unici**, 7 serie, 648 enti, 21 tipi di atto, 16 topic, tutto interrogabile.

[![CI](https://github.com/dataciviclab/gu-monitor/actions/workflows/ci.yml/badge.svg)](https://github.com/dataciviclab/gu-monitor/actions/workflows/ci.yml)
[![Daily Update](https://github.com/dataciviclab/gu-monitor/actions/workflows/daily-update.yml/badge.svg)](https://github.com/dataciviclab/gu-monitor/actions/workflows/daily-update.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

---

## Dashboard

La dashboard Streamlit mostra in tempo reale cosa pubblica lo Stato italiano.

```bash
# Avvio locale
pip install -r requirements.txt
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
| Atti totali | **25.711** |
| Serie monitorate | **7** |
| Enti rilevati | **648** |
| Tipi di atto | **21** |
| Topic classificati | **16** |
| Copertura topic | **79%** |
| Peak day | **275 atti (28 aprile 2026)** |

---

## Dataset

Il cuore è `data/gu_acts.parquet`: un singolo file Parquet con tutti gli atti unici. Il dataset è cumulativo e cresce con il daily update. Chiave: `id` (codice redazionale).

| Colonna | Tipo | Descrizione |
|---|---|---|
| `id` | VARCHAR | Codice atto (es. `26G00165`) |
| `serie` | VARCHAR | SG / S1 / S2 / S3 / S4 / S5 / P2 |
| `gazzetta_numero` | VARCHAR | Numero della pubblicazione |
| `data_pubblicazione` | DATE | Data di pubblicazione |
| `titolo` | VARCHAR | Oggetto dell'atto (dal secondo anchor della pagina GU) |
| `estremi` | VARCHAR | Estremi come pubblicati (`DECRETO 5 agosto 2026, n. 198`) |
| `tipo_atto` | VARCHAR | LEGGE / DECRETO-LEGGE / CONCORSO / etc (21 tipi) |
| `ente` | VARCHAR | Ente emittente (`span.emettitore`) |
| `link` | VARCHAR | URL della pagina di dettaglio GU |
| `topic_str` | VARCHAR | Topic classificati (16 topic) |
| `urn_normattiva` | VARCHAR | URN NIR per gli atti normativi (crossref API Normattiva) |

---

## Fonte e riuso

Fonte: **Gazzetta Ufficiale della Repubblica Italiana** — [gazzettaufficiale.it](https://www.gazzettaufficiale.it).

La fonte dichiara che la riproduzione dei testi elettronici è consentita **purché venga menzionata la fonte e il carattere non autentico e gratuito**. I testi riprodotti non sono autentici: **l'unico testo definitivo è quello pubblicato sulla Gazzetta a mezzo stampa**, che prevale in caso di discordanza. Il codice del repo è MIT.

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

# Cattura incrementale (watermark → archivio)
python scripts/capture.py

# Applica il delta all'event log (dedup su id)
python scripts/to_parquet.py --input data/gu_atti_delta.json

# Cross-reference Normattiva (URN) e riapplica
python scripts/crossref.py
python scripts/to_parquet.py --input data/gu_atti_delta.json

# Analytics
python scripts/analytics.py
```

Ricostruzione di un anno intero (manutenzione, non cron):

```bash
python scripts/rebuild_archivio.py --anno 2026
python scripts/to_parquet.py --rebuild --input data/gu_atti_rebuild.json
```

---

## Automazione

Il workflow `daily-update.yml` esegue ogni giorno alle 06:00 UTC:

1. **Cattura incrementale** — dal watermark dell'event log all'archivio annuale.
   Dopo un fermo recupera da sola l'intero buco, senza job di riparazione.
2. Applica il delta all'event log (upsert per `id`).
3. Cross-reference Normattiva e riapplica gli URN.
4. Commit automatico se ci sono novità.

Costo tipico: ~3 richieste HTTP per un giorno normale, ~14 per la finestra di
sovrapposizione (3 giorni). Un fallimento parziale salva comunque gli atti
raccolti e rende il run rosso alla fine.

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
│   ├── gu_source.py          # Fonte: URL, fetch, parser (unico punto)
│   ├── capture.py            # Cattura incrementale a watermark
│   ├── rebuild_archivio.py   # Ricostruzione per anno
│   ├── to_parquet.py         # JSON → Parquet (event log)
│   ├── crossref.py           # URN Normattiva
│   └── analytics.py          # Report DuckDB
├── tests/
│   └── test_basic.py         # 10 test
├── data/
│   └── gu_acts.parquet       # Dataset cumulativo
├── app.py                    # Dashboard Streamlit
├── Dockerfile                # Container deploy
├── requirements.txt          # Dipendenze
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
