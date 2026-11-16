-- Daily totals per station and train category.
-- The dashboard sums these rows for any filter (station, category, date range),
-- so we store SUMS and COUNTS, never averages (averages of averages would be wrong).
--
-- On time = less than 6 minutes late (DB's official definition), i.e. delay_min <= 5.
-- Cancelled stops have no real delay, so they are excluded from delay measures.
SELECT
    CAST(planned_time AS DATE)                                   AS date,
    eva,
    category,
    COUNT(*)                                                     AS stops,
    COUNT(*) FILTER (WHERE is_cancelled)                         AS cancelled,
    SUM(delay_min) FILTER (WHERE NOT is_cancelled)               AS delay_sum,
    COUNT(*) FILTER (WHERE NOT is_cancelled AND delay_min <= 5)  AS on_time,
    COUNT(*) FILTER (WHERE NOT is_cancelled AND delay_min >= 15) AS delayed_15
FROM stops
GROUP BY ALL
