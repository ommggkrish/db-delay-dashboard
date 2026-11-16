-- Routes = origin station -> final destination of a train run.
--
-- ride_id identifies a train's run pattern; stop_number is the position of the stop in it.
-- Origin      = the station at the lowest stop_number of the ride_id.
-- Destination = the last stop (highest stop_number). We measure the delay THERE,
--               because arrival delay at the destination is what passengers feel.
WITH ride_ends AS (
    SELECT
        ride_id,
        arg_min(station_name, stop_number) AS origin,
        max(stop_number)                   AS last_stop_number
    FROM stops
    GROUP BY ride_id
)
SELECT
    CAST(date_trunc('month', s.planned_time) AS DATE)                AS month,
    s.category,
    r.origin,
    s.station_name                                                   AS destination,
    COUNT(*)                                                         AS trips,
    COUNT(*) FILTER (WHERE s.is_cancelled)                           AS cancelled,
    SUM(s.delay_min) FILTER (WHERE NOT s.is_cancelled)               AS delay_sum,
    COUNT(*) FILTER (WHERE NOT s.is_cancelled AND s.delay_min <= 5)  AS on_time
FROM stops AS s
JOIN ride_ends AS r
  ON s.ride_id = r.ride_id
 AND s.stop_number = r.last_stop_number
WHERE r.last_stop_number > 1          -- a "route" needs at least two stops
  AND r.origin <> s.station_name
GROUP BY ALL
