-- One row per station (EVA number = DB's official station ID).
-- A station can appear with slightly different names, so we keep the most common one.
SELECT
    eva,
    mode(station_name) AS station_name,
    COUNT(*)           AS stops
FROM stops
GROUP BY eva
ORDER BY stops DESC
