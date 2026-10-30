-- Clean: tipizza e valida l'event log della Gazzetta Ufficiale.
-- Un record per atto (PK = id, codice redazionale). Il filtro sull'anno
-- rende il dataset partizionabile lasciando il raw cumulativo.
SELECT
    normalize_string(id) AS id,
    normalize_string(serie) AS serie,
    CAST(gazzetta_numero AS VARCHAR) AS gazzetta_numero,
    TRY_CAST(data_pubblicazione AS DATE) AS data_pubblicazione,
    CAST(year(TRY_CAST(data_pubblicazione AS DATE)) AS INTEGER) AS anno,
    normalize_string(titolo) AS titolo,
    normalize_string(estremi) AS estremi,
    normalize_string(tipo_atto) AS tipo_atto,
    normalize_string(ente) AS ente,
    normalize_string(topic_str) AS topic_str,
    normalize_string(urn_normattiva) AS urn_normattiva,
    normalize_string(link) AS link
FROM raw_input
WHERE TRY_CAST(data_pubblicazione AS DATE) IS NOT NULL
  AND year(TRY_CAST(data_pubblicazione AS DATE)) = {year}
