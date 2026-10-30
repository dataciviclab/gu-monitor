-- Atti normativi con URN NIR: il ponte verso il corpus (italia-corpus,
-- legal-graph). Un record per atto, con estremi e oggetto.
SELECT
    id,
    data_pubblicazione,
    tipo_atto,
    estremi,
    titolo,
    ente,
    urn_normattiva
FROM clean_input
WHERE urn_normattiva IS NOT NULL AND urn_normattiva <> ''
ORDER BY data_pubblicazione DESC
