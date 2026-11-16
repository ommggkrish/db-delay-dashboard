-- Totals per month, hour of day (planned time), station and train category.
-- Grouped by month instead of day to keep the file small enough for free hosting,
-- so the hour-of-day chart filters by whole months.
SELECT
    CAST(date_trunc('month', planned_time) AS DATE)              AS month,
    CAST(hour(planned_time) AS TINYINT)                          AS hour,
    eva,
    category,
    COUNT(*)                                                     AS stops,
    COUNT(*) FILTER (WHERE is_cancelled)                         AS cancelled,
    SUM(delay_min) FILTER (WHERE NOT is_cancelled)               AS delay_sum,
    COUNT(*) FILTER (WHERE NOT is_cancelled AND delay_min <= 5)  AS on_time,
    COUNT(*) FILTER (WHERE NOT is_cancelled AND delay_min >= 15) AS delayed_15
FROM stops
GROUP BY ALL
