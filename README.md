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

Il cuore è l'**event log**: un singolo Parquet con tutti gli atti unici, tenuto su
`gs://dataciviclab-clean/gu-monitor/_event_log/` (non in git). In locale lo scarichi
con `make store-pull`. Chiave: `id` (codice redazionale). Il dataset pubblicato è
invece `gs://dataciviclab-clean/gu-monitor/gu_atti/<anno>/`.

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

**L'event log vive su GCS, non in git**:
`gs://dataciviclab-clean/gu-monitor/_event_log/`. La lettura è pubblica (HTTPS),
la scrittura richiede auth. Così la storia del repo non cresce di ~1 MB al giorno.

**`daily-update.yml`** (ogni giorno alle 06:00 UTC), due job:

1. `ingest` — scarica l'event log, cattura il delta dal watermark, cross-reference
   Normattiva, ricarica l'event log su GCS.
2. `build` — `toolkit run` → clean → mart, `verify_clean.py`, sync su
   `gs://dataciviclab-{clean,mart}/gu-monitor/gu_atti/<anno>/`, registry via PR draft.

Un terzo job `esito` rende il run rosso se la cattura ha avuto errori — dopo aver
salvato e pubblicato quello che si è riusciti a prendere.

Costo tipico: ~3 richieste HTTP per un giorno normale, ~14 per la finestra di
sovrapposizione (3 giorni).

**`pipeline.yml`** — solo per ricostruire a mano o quando cambia `datasets/**` o
`sql/**`. Il build quotidiano è dentro `daily-update.yml`.

Comandi locali:

```bash
make store-pull   # scarica event log + cache URN da GCS
make ingest       # cattura (rete) e aggiorna l'event log
make run          # build raw -> clean -> mart
make daily        # pull + ingest + push + build
make check        # config toolkit
make rebuild ANNO=2026
```

---

## Struttura

```
gu-monitor/
├── .github/workflows/
│   ├── ci.yml                # lint + test + config check
│   ├── daily-update.yml      # cattura + build (GCS → clean/mart)
│   └── pipeline.yml          # rebuild manuale / su modifica pipeline
├── .streamlit/
│   └── config.toml           # Tema dashboard
├── datasets/gu-atti/
│   ├── dataset.yml           # contratto toolkit
│   └── sql/                  # clean + 3 mart
├── scripts/
│   ├── gu_source.py          # Fonte: URL, fetch, parser (unico punto)
│   ├── capture.py            # Cattura incrementale a watermark
│   ├── rebuild_archivio.py   # Ricostruzione per anno
│   ├── to_parquet.py         # JSON → Parquet (event log)
│   ├── crossref.py           # URN Normattiva
│   ├── verify_clean.py       # Guardia del build
│   └── analytics.py          # Report DuckDB
├── tests/
│   └── test_*.py             # 44 test
├── data/
│   └── (event log e cache URN: scaricati da GCS, mai in git)
├── Makefile                  # ingest / run / daily / check / rebuild
├── app.py                    # Dashboard Streamlit
├── Dockerfile                # Container deploy
├── requirements.txt          # Dipendenze
├── pyproject.toml            # Project config
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
