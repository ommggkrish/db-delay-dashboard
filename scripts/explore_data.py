"""
Explore the raw Deutsche Bahn data files before cleaning them.
Compares October 2025 with November 2025 to see what changed between the two months.

Run from the project folder:  python scripts/explore_data.py
"""
import duckdb

FILES = {
    "2025-10": "data/data-2025-10.parquet",
    "2025-11": "data/data-2025-11.parquet",
}

# An in-memory DuckDB database: nothing is saved to disk.
con = duckdb.connect()

for month, path in FILES.items():
    print(f"\n========== {month}: {path} ==========")

    # 1) Size and coverage of the file
    summary = con.sql(f"""
        SELECT
            COUNT(*)                   AS rows,
            COUNT(DISTINCT eva)        AS stations,
            COUNT(DISTINCT train_type) AS train_types,
            MIN(time)                  AS first_time,
            MAX(time)                  AS last_time,
            ROUND(100 * AVG(CASE WHEN delay_in_min IS NULL THEN 1 ELSE 0 END), 1) AS pct_delay_missing
        FROM '{path}'
    """).df()
    print(summary.to_string(index=False))

    # 2) Most common train types
    print("\nTop 10 train types by number of stops:")
    top_types = con.sql(f"""
        SELECT train_type, COUNT(*) AS stops
        FROM '{path}'
        GROUP BY train_type
        ORDER BY stops DESC
        LIMIT 10
    """).df()
    print(top_types.to_string(index=False))

# 3) How many stations appear in BOTH months?
common = con.sql(f"""
    SELECT COUNT(*) FROM (
        SELECT DISTINCT eva FROM '{FILES["2025-10"]}'
        INTERSECT
        SELECT DISTINCT eva FROM '{FILES["2025-11"]}'
    )
""").fetchall()[0][0]
print(f"\nStations present in both months: {common}")

# 4) A few real rows, so we can see what one record looks like
print("\nSample rows (October):")
sample = con.sql(f"""
    SELECT station_name, train_type, train_number, time,
           delay_in_min, arrival_is_canceled, departure_is_canceled
    FROM '{FILES["2025-10"]}'
    LIMIT 5
""").df()
print(sample.to_string(index=False))
