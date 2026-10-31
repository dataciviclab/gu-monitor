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
| `tipo_atto` | string | Genere dell'atto, match a token intero sugli estremi (tassonomia in `gu_source.TIPI_ATTO`) | `DECRETO-LEGGE` |
| `ente` | string | Ente emittente (`span.emettitore`) | `AGENZIA ITALIANA DEL FARMACO` |
| `link` | string | URL della pagina di dettaglio GU | `http://www.gazzettaufficiale.it/atto/...` |
| `sezione` | string | Rubrica della pagina (titolo di sezione, non un ente) | `Convocazioni di assemblea` |
| `link_normattiva` | string | Link a Normattiva (dal crossref per URN) | `https://www.normattiva.it/uri-res/N2Ls?...` |
| `urn_normattiva` | string | URN NIR (identificativo permanente) | `urn:nir:stato:legge:2026-08-07;152` |

## Note

- `id` = codice redazionale della GU (es. `26G00165`), preso da `atto.codiceRedazionale` nel link di dettaglio.
- `tipo_atto` classificato con match a token intero sugli **estremi**: `LEGGE` non intercetta `DECRETO-LEGGE`.
- `ente` da `span.emettitore`, mai da euristiche sul testo.
- `urn_normattiva` è popolato dal crossref con l'API Normattiva per i codici `AAGG######` (atti normativi). Il filtro è sull'anno dinamico, non hardcoded.
- `codice_genere`: `G` = codice `AAGG######` (l'unico indicizzato da Normattiva); `A` = tutto il resto. Non significa "numerato": molti atti `A` hanno numero (S3, S1) e non hanno URN.
- `ente` è NULL su P2 e S5: in quelle serie il campo `emettitore` della fonte contiene una rubrica, non l'emittente. Su S1 e S2 è una costante (`CORTE COSTITUZIONALE`, `UNIONE EUROPEA`).
- `sezione` ha due granularità: su P2/S5 è la rubrica di secondo livello (`Convocazioni di assemblea`), sulle altre serie quella di primo livello (`LEGGI ED ALTRI ATTI NORMATIVI`). Un `GROUP BY sezione` misto tra serie confronta livelli diversi.
- `link_normattiva` esiste nello store ma non è nel clean (che espone `urn_normattiva`, da cui si ricostruisce).
