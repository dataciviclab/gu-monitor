# Schema colonne — gu_acts

## Campi estratti dal feed RSS

| Campo | Tipo | Descrizione | Esempio |
|---|---|---|---|
| `id` | string | Codice atto dal link ELI | `26G00165` |
| `serie` | string | Serie della GU | `SG` |
| `titolo` | string | Titolo completo dell'atto | `LEGGE 7 agosto 2026, n.152` |
| `tipo_atto` | string | Tipo classificato | `LEGGE` |
| `link` | string | URL permanente ELI | `http://www.gazzettaufficiale.it/eli/id/2026/08/20/26G00165/SG` |
| `data_pubblicazione` | date | Data di pubblicazione | `2026-08-20` |
| `content_snippet` | string | Primi ~200 char del contenuto | Conversione in legge... |

## Campi Fase 2 (arricchimento)

| Campo | Tipo | Descrizione |
|---|---|---|
| `ente` | string | Ente emittente (estratto da titolo) |
| `numero_atto` | string | Numero dell'atto |
| `topic` | list[string] | Keyword estratte |
| `has_reference` | bool | Se referenzia altri atti |

## Note

- `id` estratto dal pattern `/eli/id/YYYY/MM/DD/{ID}/SERIE`
- `tipo_atto` classificato con regex sul primo token del titolo
- `ente` estratto prima del trattino nel titolo (se presente)
