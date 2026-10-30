# Schema colonne — gu_acts

## Colonne del dataset

| Campo | Tipo | Descrizione | Esempio |
|---|---|---|---|
| `id` | string | Codice atto (codice redazionale GU) | `26G00165` |
| `serie` | string | Serie della GU | `SG` |
| `gazzetta_numero` | string | Numero della pubblicazione | `192` |
| `data_pubblicazione` | date | Data di pubblicazione | `2026-08-20` |
| `titolo` | string | Oggetto dell'atto (dal secondo anchor della pagina) | `Regolamento in attuazione dell'articolo 12 ...` |
| `estremi` | string | Estremi come pubblicati (o soggetto per le inserzioni P2) | `DECRETO 5 agosto 2026, n. 198` |
| `tipo_atto` | string | Tipo classificato (21 valori, match a token intero) | `DECRETO-LEGGE` |
| `ente` | string | Ente emittente (`span.emettitore`) | `AGENZIA ITALIANA DEL FARMACO` |
| `link` | string | URL della pagina di dettaglio GU | `http://www.gazzettaufficiale.it/atto/...` |
| `topic_str` | string | Topic classificati (separati da virgola) | `sanita,fisco` |
| `link_normattiva` | string | Link a Normattiva (dal crossref per URN) | `https://www.normattiva.it/uri-res/N2Ls?...` |
| `urn_normattiva` | string | URN NIR (identificativo permanente) | `urn:nir:stato:legge:2026-08-07;152` |

## Note

- `id` = codice redazionale della GU (es. `26G00165`), preso da `atto.codiceRedazionale` nel link di dettaglio.
- `tipo_atto` classificato con match a token intero sugli **estremi**: `LEGGE` non intercetta `DECRETO-LEGGE`.
- `ente` da `span.emettitore`; l'euristica "testo maiuscolo" resta solo come fallback.
- `urn_normattiva` è popolato dal crossref con l'API Normattiva per i codici `AAGG######` (atti normativi). Il filtro è sull'anno dinamico, non hardcoded.
- `topic_str` vuoto per atti senza topic riconoscibili (es. inserzioni P2).
