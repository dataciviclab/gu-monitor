# GU Monitor

Sistema di intelligence sulla Gazzetta Ufficiale Italiana.

## Cosa fa

Monitora i 7 feed RSS della Gazzetta Ufficiale e l'archivio 30 giorni, producendo un dataset Parquet con tutti gli atti pubblicati.

## Quick start

```bash
# Installa dipendenze
pip install -r requirements.txt

# Fetch storico 30gg
python scripts/scrape_30gg.py

# Converti in Parquet
python scripts/to_parquet.py

# Analytics
python scripts/analytics.py

# Test
pytest tests/
```

## Output

- `data/gu_acts.parquet` — dataset finale (~4.300 atti, 30 giorni, 7 serie)

## Serie monitorate

| Codice | Serie | Atti/30gg | Media/giorno |
|---|---|---|---|
| P2 | Parte II | ~1.700 | ~58 |
| SG | Serie Generale | ~1.100 | ~38 |
| S4 | Concorsi ed Esami | ~1.000 | ~34 |
| S2 | Unione Europea | ~260 | ~9 |
| S1 | Corte Costituzionale | ~75 | ~2 |
| S5 | Contratti Pubblici | ~60 | ~2 |
| S3 | Regioni | ~45 | ~2 |

## Schema Parquet

| Colonna | Tipo | Descrizione |
|---|---|---|
| `id` | VARCHAR | Codice atto |
| `serie` | VARCHAR | SG/S1/S2/S3/S4/S5/P2 |
| `gazzetta_numero` | VARCHAR | Numero pubblicazione |
| `data_pubblicazione` | DATE | Data |
| `titolo` | VARCHAR | Titolo/descrizione |
| `tipo_atto` | VARCHAR | LEGGE/DECRETO/REGOLAMENTO/etc |
| `ente` | VARCHAR | Ente emittente |
| `link` | VARCHAR | URL ELI o PDF |
| `topic_str` | VARCHAR | Topic classificati |

## Automazione

Il workflow GitHub Actions `daily-update.yml` esegue:
1. Scraping archivio 30gg
2. Conversione in Parquet
3. Commit automatico

## License

MIT
