"""
Compute the "Key findings" from the summary tables and write them to reports/key_findings.md.

Every number in the findings comes from a SQL query below - nothing is typed in by hand.
The dashboard's "Key findings" tab and the README both use this file.

Run from the project folder (after build_aggregates.py):  python scripts/key_findings.py
"""
from pathlib import Path

import duckdb

DATA_DIR = Path("app_data")
OUT_FILE = Path("reports/key_findings.md")
BIG_STATION_RANK = 100   # "big stations" = the 100 stations with the most train stops
MIN_ROUTE_TRIPS = 1000   # ignore rare run patterns (e.g. diversions during construction)

con = duckdb.connect()
for name in ("daily", "hourly", "routes", "stations"):
    con.sql(f"CREATE VIEW {name} AS SELECT * FROM '{(DATA_DIR / f'{name}.parquet').as_posix()}'")

MEASURES = """
    SUM(stops)                                                    AS stops,
    SUM(delay_sum) / NULLIF(SUM(stops) - SUM(cancelled), 0)       AS avg_delay,
    100.0 * SUM(on_time) / NULLIF(SUM(stops) - SUM(cancelled), 0) AS on_time_pct,
    100.0 * SUM(cancelled) / NULLIF(SUM(stops), 0)                AS cancelled_pct,
    100.0 * SUM(delayed_15) / NULLIF(SUM(stops) - SUM(cancelled), 0) AS delayed_15_pct
"""


def one(sql: str) -> dict:
    """Run a query and return its first row as a dict."""
    return con.sql(sql).df().iloc[0].to_dict()


overall = one(f"SELECT {MEASURES}, MIN(date) AS first, MAX(date) AS last, COUNT(DISTINCT eva) AS stations FROM daily")

by_cat = con.sql(f"SELECT category, {MEASURES} FROM daily GROUP BY category ORDER BY on_time_pct").df()
worst_cat, best_cat = by_cat.iloc[0], by_cat.iloc[-1]

by_hour = con.sql(f"SELECT hour, {MEASURES} FROM hourly GROUP BY hour HAVING SUM(stops) >= 100000 ORDER BY avg_delay").df()
best_hour, worst_hour = by_hour.iloc[0], by_hour.iloc[-1]

weekday_names = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
by_dow = con.sql(f"SELECT isodow(date) AS dow, {MEASURES} FROM daily GROUP BY dow ORDER BY avg_delay").df()
best_dow, worst_dow = by_dow.iloc[0], by_dow.iloc[-1]

by_month = con.sql(f"SELECT strftime(date, '%B %Y') AS month, {MEASURES} FROM daily GROUP BY month ORDER BY on_time_pct").df()
worst_month, best_month = by_month.iloc[0], by_month.iloc[-1]

big_stations = con.sql(f"""
    WITH big AS (SELECT eva, station_name FROM stations ORDER BY stops DESC LIMIT {BIG_STATION_RANK})
    SELECT big.station_name, {MEASURES}
    FROM daily JOIN big USING (eva)
    GROUP BY big.station_name
    ORDER BY avg_delay
""").df()
best_station, worst_station = big_stations.iloc[0], big_stations.iloc[-1]

worst_route = one(f"""
    SELECT category, origin, destination, SUM(trips) AS trips,
           SUM(delay_sum) / NULLIF(SUM(trips) - SUM(cancelled), 0) AS avg_delay
    FROM routes GROUP BY ALL HAVING SUM(trips) >= {MIN_ROUTE_TRIPS}
    ORDER BY avg_delay DESC LIMIT 1
""")

lines = [
    "## Key findings",
    "",
    f"Based on **{overall['stops'] / 1e6:.1f} million train stops** at **{overall['stations']:,} stations** "
    f"from {overall['first']:%d %b %Y} to {overall['last']:%d %b %Y}.",
    "",
    f"1. **Overall:** the average delay was **{overall['avg_delay']:.1f} minutes**; "
    f"**{overall['on_time_pct']:.1f}%** of stops were on time (less than 6 minutes late), "
    f"{overall['delayed_15_pct']:.1f}% were 15+ minutes late and {overall['cancelled_pct']:.1f}% were cancelled.",
    f"2. **Train category:** {best_cat['category']} was the most punctual ({best_cat['on_time_pct']:.1f}% on time), "
    f"{worst_cat['category']} the least ({worst_cat['on_time_pct']:.1f}% on time, "
    f"average delay {worst_cat['avg_delay']:.1f} min).",
    f"3. **Time of day:** trains planned at {int(worst_hour['hour']):02d}:00-{int(worst_hour['hour']):02d}:59 had the "
    f"highest average delay ({worst_hour['avg_delay']:.1f} min); {int(best_hour['hour']):02d}:00-"
    f"{int(best_hour['hour']):02d}:59 the lowest ({best_hour['avg_delay']:.1f} min).",
    f"4. **Day of week:** {weekday_names[int(worst_dow['dow']) - 1]} had the highest average delay "
    f"({worst_dow['avg_delay']:.1f} min), {weekday_names[int(best_dow['dow']) - 1]} the lowest "
    f"({best_dow['avg_delay']:.1f} min).",
    f"5. **Month:** {best_month['month']} was the most punctual month ({best_month['on_time_pct']:.1f}% on time), "
    f"{worst_month['month']} the least ({worst_month['on_time_pct']:.1f}%).",
    f"6. **Big stations** (the {BIG_STATION_RANK} busiest): {worst_station['station_name']} had the highest average "
    f"delay ({worst_station['avg_delay']:.1f} min, {worst_station['on_time_pct']:.1f}% on time); "
    f"{best_station['station_name']} the lowest ({best_station['avg_delay']:.1f} min).",
    f"7. **Worst route** (at least {MIN_ROUTE_TRIPS:,} trips): {worst_route['origin']} → "
    f"{worst_route['destination']} ({worst_route['category']} trains), arriving on average {worst_route['avg_delay']:.1f} min late "
    f"({int(worst_route['trips']):,} trips).",
    "",
    "_Caveat: the data comes from snapshots of DB's Timetables API, not DB's official punctuality statistics, "
    "so numbers can differ from published figures._",
]

OUT_FILE.parent.mkdir(exist_ok=True)
OUT_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")
print("\n".join(lines))
