# GU Monitor

**La Gazzetta Ufficiale italiana monitorata in tempo reale: cosa decide lo Stato, quando lo decide, chi lo decide.**

La Gazzetta Ufficiale è il diario ufficiale dello Stato italiano. Ogni legge, ogni decreto, ogni bando di concorso passa da qui. Ma nessuno la monitora sistematicamente.

Questo progetto lo fa: le **7 serie** della Gazzetta, un record per atto. La colonna `codice_genere` separa i **218 atti normativi** (codici `AAGG######`, gli unici che Normattiva indicizza) dal resto — avvisi, concorsi, sentenze, notifiche.

[![CI](https://github.com/dataciviclab/gu-monitor/actions/workflows/ci.yml/badge.svg)](https://github.com/dataciviclab/gu-monitor/actions/workflows/ci.yml)
[![Daily Update](https://github.com/dataciviclab/gu-monitor/actions/workflows/daily-update.yml/badge.svg)](https://github.com/dataciviclab/gu-monitor/actions/workflows/daily-update.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

---

---

## Numeri chiave

| Metrica | Valore |
|---|---|
| Serie monitorate | **7** |
| Granularità | 1 record per atto |
| Aggiornamento | giornaliero (watermark) |

I contatori (atti, enti, picchi) non sono hardcoded: cambiano a ogni run e si leggono dal dataset.

---

## Dashboard

Streamlit, deployata su Streamlit Cloud. La dashboard vive in `dashboard/`; l'`app.py` alla root è un redirect di 3 righe per il deploy esistente (main file path non modificabile dalla UI).

| Pagina | Cosa mostra |
|---|---|
| Panoramica | atti per serie, normativi vs resto, enti che pubblicano di più |
| Atti normativi | i 218 atti/anno con estremi, ente e link Normattiva |
| Sezioni | le rubriche della Gazzetta |
| Query SQL | SQL libero sul clean |

I dati arrivano dal **clean pubblicato su GCS** via `lab-connectors`: nessun file
locale, nessun URL hardcoded.

```bash
cd dashboard
pip install -r requirements.txt
streamlit run app.py
```

---

## Dataset

Il cuore è l'**event log**: un singolo Parquet con tutti gli atti unici, tenuto su
`gs://dataciviclab-clean/gu-monitor/_event_log/` (non in git). In locale lo scarichi
con `make store-pull`. Chiave: `id` (codice redazionale). Il dataset pubblicato è
invece `gs://dataciviclab-clean/gu-monitor/gu_atti/<anno>/`.

Lo store tiene anche due campi grezzi della pagina (`rubrica_raw`, `emittitore_raw`)
che **non** entrano nel clean: servono a correggere `sezione`/`ente` con un `UPDATE`
invece di ri-scaricare 755 pubblicazioni. Sono NULL sulle righe catturate prima
del rebuild che li ha introdotti.

| Colonna | Tipo | Descrizione |
|---|---|---|
| `id` | VARCHAR | Codice atto (es. `26G00165`) |
| `serie` | VARCHAR | SG / S1 / S2 / S3 / S4 / S5 / P2 |
| `gazzetta_numero` | VARCHAR | Numero della pubblicazione |
| `data_pubblicazione` | DATE | Data di pubblicazione |
| `titolo` | VARCHAR | Oggetto dell'atto (dal secondo anchor della pagina GU) |
| `estremi` | VARCHAR | Estremi come pubblicati (`DECRETO 5 agosto 2026, n. 198`) |
| `tipo_atto` | VARCHAR | Genere dell'atto (LEGGE, DECRETO-LEGGE, DECRETO LEGISLATIVO, CONCORSO…); tassonomia in `scripts/gu_source.py` |
| `ente` | VARCHAR | Ente emittente. NULL su P2/S5 (lì il campo della fonte è una rubrica) |
| `link` | VARCHAR | URL della pagina di dettaglio GU |
| `sezione` | VARCHAR | Rubrica della pagina (`Eredita'`, `Convocazioni di assemblea`) |
| `codice_genere` | VARCHAR | `G` = codice `AAGG######` (indicizzato da Normattiva), `A` = tutto il resto |
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

-- Atti normativi (gli unici che Normattiva indicizza)
SELECT tipo_atto, COUNT(*) AS n
FROM 'data/gu_acts.parquet'
WHERE codice_genere = 'G'
GROUP BY tipo_atto ORDER BY n DESC;

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
pip install -e .

# Cattura incrementale + URN + merge nello store
python scripts/collect.py

# Backfill di un anno (o intervallo)
python scripts/collect.py --anni 2025
```

Ricostruzione di un anno intero (manutenzione, non cron):

```bash
python scripts/collect.py --anni 2025
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

**`rebuild.yml`** — backfill di uno o più anni dall'archivio (manuale, in CI:
lo store su GCS lo scrive solo la pipeline). Dopo il backfill va aggiornato
`years` in `datasets/gu-atti/dataset.yml` per pubblicare i nuovi anni.

Comandi locali:

```bash
make store-pull   # scarica l'event log da GCS
make ingest       # cattura (rete) e aggiorna l'event log
make run          # build raw -> clean -> mart
make daily        # pull + ingest + build (non pubblica: il push lo fa la CI)
make check        # config toolkit
make rebuild ANNI=2026
```

---

## Struttura

```
gu-monitor/
├── dashboard/
│   ├── app.py                # entry point Streamlit
│   ├── sources.py            # data layer (clean su GCS)
│   ├── pages/                # Panoramica, Normativi, Sezioni, SQL
│   └── requirements.txt      # letto da Streamlit Cloud
├── .github/workflows/
│   ├── ci.yml                # lint + test + config check
│   ├── daily-update.yml      # cattura + build (GCS → clean/mart)
│   ├── pipeline.yml          # rebuild manuale / su modifica pipeline
│   └── rebuild.yml           # backfill storico (CI only)
├── datasets/gu-atti/
│   ├── dataset.yml           # contratto toolkit
│   └── sql/                  # clean + 3 mart
├── scripts/
│   ├── gu_source.py          # Fonte: URL, fetch, parser (unico punto)
│   ├── collect.py            # Store: incrementale e backfill + URN
│   └── verify_clean.py       # Guardia del build
├── tests/
│   └── test_*.py             # contratto store, parser, merge
├── data/
│   └── (event log scaricato da GCS, mai in git)
├── Makefile                  # ingest / run / daily / check / rebuild
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
