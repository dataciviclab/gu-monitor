-- Volume di pubblicazione: quanti atti per serie e per giorno.
SELECT
    serie,
    data_pubblicazione,
    COUNT(*) AS atti,
    COUNT(DISTINCT ente) AS enti
FROM clean_input
GROUP BY serie, data_pubblicazione
ORDER BY data_pubblicazione DESC, serie
