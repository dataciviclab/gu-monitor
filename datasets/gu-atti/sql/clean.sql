-- Clean: tipizza e valida l'event log della Gazzetta Ufficiale.
-- Un record per atto (PK = id, codice redazionale). Il filtro sull'anno
-- rende il dataset partizionabile lasciando il raw cumulativo.
--
-- codice_genere separa i due universi del dataset:
--   G = codice AAGG######, l'unico che Normattiva indicizza (ha URN)
--   A = tutto il resto: avvisi, concorsi, sentenze, notifiche
-- "A" non significa "senza numero": molti atti A sono numerati (S3, S1).
-- Non è substr(id, 3, 1): i codici P2 iniziano con TX, non con l'anno.
SELECT
    normalize_string(id) AS id,
    CASE WHEN regexp_matches(id, '^[0-9]{2}G') THEN 'G' ELSE 'A' END AS codice_genere,
    normalize_string(serie) AS serie,
    CAST(gazzetta_numero AS VARCHAR) AS gazzetta_numero,
    TRY_CAST(data_pubblicazione AS DATE) AS data_pubblicazione,
    CAST(year(TRY_CAST(data_pubblicazione AS DATE)) AS INTEGER) AS anno,
    normalize_string(titolo) AS titolo,
    normalize_string(estremi) AS estremi,
    normalize_string(tipo_atto) AS tipo_atto,
    normalize_string(ente) AS ente,
    normalize_string(sezione) AS sezione,
    normalize_string(urn_normattiva) AS urn_normattiva,
    normalize_string(link) AS link
FROM raw_input
WHERE TRY_CAST(data_pubblicazione AS DATE) IS NOT NULL
  AND year(TRY_CAST(data_pubblicazione AS DATE)) = {year}
