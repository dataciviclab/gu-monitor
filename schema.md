# Schema colonne — gu_acts

## Colonne del dataset

| Campo | Tipo | Descrizione | Esempio |
|---|---|---|---|
| `id` | string | Codice atto (codice redazionale GU) | `26G00165` |
| `serie` | string | Serie della GU | `SG` |
| `gazzetta_numero` | string | Numero della pubblicazione | `192` |
| `data_pubblicazione` | date | Data di pubblicazione | `2026-08-20` |
| `titolo` | string | Titolo/descrizione dell'atto | `LEGGE 7 agosto 2026, n.152` |
| `tipo_atto` | string | Tipo classificato (21 valori) | `LEGGE` |
| `ente` | string | Ente emittente | `AGENZIA ITALIANA DEL FARMACO` |
| `link` | string | URL permanente GU | `http://www.gazzettaufficiale.it/eli/id/...` |
| `topic_str` | string | Topic classificati (separati da virgola) | `sanita,fisco` |
| `link_normattiva` | string | Link a Normattiva (testo vigente) | `https://www.normattiva.it/uri-res/N2Ls?...` |
| `urn_normattiva` | string | URN NIR (identificativo permanente) | `urn:nir:stato:legge:2026-08-07;152` |

## Note

- `id` estratto dal pattern `/eli/id/YYYY/MM/DD/{ID}/SERIE`
- `tipo_atto` classificato con regex + post-processing (21 tipi: LEGGE, DECRETO, CONCORSO, NOMINA, etc.)
- `ente` estratto prima del trattino nel titolo (se presente)
- `link_normattiva` e `urn_normattiva` disponibili solo per atti SG con pattern `26G*` (normativi)
- `topic_str` vuoto per atti senza topic riconoscibili (es. inserzioni P2)
