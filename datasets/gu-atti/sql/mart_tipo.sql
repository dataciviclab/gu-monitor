-- Composizione per tipo di atto: quanto è "normativo" ciò che lo Stato pubblica.
SELECT
    tipo_atto,
    COUNT(*) AS atti,
    COUNT(DISTINCT serie) AS serie,
    COUNT(DISTINCT ente) AS enti
FROM clean_input
GROUP BY tipo_atto
ORDER BY atti DESC
