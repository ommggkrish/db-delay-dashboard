"""
Phase 2: Load and clean the raw Deutsche Bahn data.

Reads the monthly raw Parquet files for the analysis window (Nov 2025 - Oct 2026),
applies the cleaning rules below, and writes ONE cleaned Parquet file:

    data/clean/stops.parquet   (large, local only - ignored by Git)

It also writes reports/cleaning_report.md with how many rows each rule removed,
so every number in the README can be traced back to this script.

Cleaning rules (each row gets the FIRST rule it breaks):
  1. missing_delay       - no delay value (the stop had no planned record in the API data)
  2. outside_window      - planned time is not between 2025-11-01 and 2026-10-31
  3. bus_or_taxi         - rail replacement buses / taxis: this is a TRAIN dashboard
  4. impossible_early    - more than 5 minutes early (e.g. -1440 = a date error), not realistic

Duplicates: the script checks that every stop id is unique (within each month and between
neighbouring months) and stops with an error if not. Checking is much cheaper than
de-duplicating 170 million rows "just in case".

Run from the project folder:  python scripts/clean_data.py
"""
from pathlib import Path

import duckdb

RAW_FILES = sorted(Path("data").glob("data-*.parquet"))
WINDOW_START = "2025-11-01"
WINDOW_END = "2026-11-01"  # exclusive
OUT_FILE = Path("data/clean/stops.parquet")
REPORT_FILE = Path("reports/cleaning_report.md")

# Only files whose month is inside the window (data-2025-11 ... data-2026-10).
# Rows from neighbouring months are still filtered by planned time below.
files = [str(f) for f in RAW_FILES if "2025-11" <= f.stem.removeprefix("data-") <= "2026-10"]
print(f"Reading {len(files)} raw files: {files[0]} ... {files[-1]}")

# Road vehicles that appear in the train_type column (replacement buses, taxis).
BUS_TYPES = ("Bus", "SEV", "BSEV", "Bvs", "bvs", "RBUS", "RBBUs", "Taxi", "NWBEV", "EV")

# Group the ~100 raw train types into a few categories that people recognise.
# ICE / IC are DB long-distance; RE / RB are regional; S = S-Bahn (city rail).
# Private regional operators (e.g. HLB, VIA, MEX, metronom "ME") become "Other regional".
CATEGORY_SQL = """
    CASE
        WHEN train_type = 'ICE'                              THEN 'ICE'
        WHEN train_type IN ('IC', 'EC', 'ECE')               THEN 'IC/EC'
        WHEN train_type IN ('NJ', 'EN', 'FLX', 'TGV', 'RJ', 'RJX', 'EST', 'ES', 'D')
                                                             THEN 'Other long-distance'
        WHEN train_type = 'RE'                               THEN 'RE'
        WHEN train_type = 'RB'                               THEN 'RB'
        WHEN regexp_matches(train_type, '^S[0-9]*$')         THEN 'S-Bahn'  -- 'S', 'S8', 'S42'
        ELSE 'Other regional'
    END
"""

con = duckdb.connect()
con.sql("SET memory_limit = '8GB'")
con.sql("SET preserve_insertion_order = false")  # lets DuckDB stream big files with less memory

file_list = ", ".join(f"'{f}'" for f in files)

# One view with the cleaning decision for every raw row.
con.sql(f"""
    CREATE OR REPLACE TEMP VIEW labelled AS
    SELECT
        *,
        coalesce(departure_planned_time, arrival_planned_time) AS planned_time,
        CASE
            WHEN delay_in_min IS NULL                                         THEN 'missing_delay'
            WHEN coalesce(departure_planned_time, arrival_planned_time) IS NULL
              OR coalesce(departure_planned_time, arrival_planned_time) <  TIMESTAMP '{WINDOW_START}'
              OR coalesce(departure_planned_time, arrival_planned_time) >= TIMESTAMP '{WINDOW_END}'
                                                                              THEN 'outside_window'
            WHEN train_type IN {BUS_TYPES}                                    THEN 'bus_or_taxi'
            WHEN delay_in_min < -5                                            THEN 'impossible_early'
            ELSE 'kept'
        END AS cleaning_label
    FROM read_parquet([{file_list}])
""")

print("Counting rows per cleaning rule (one pass over all files)...")
label_counts = con.sql("""
    SELECT cleaning_label, COUNT(*) AS rows
    FROM labelled
    GROUP BY cleaning_label
    ORDER BY rows DESC
""").df()
print(label_counts.to_string(index=False))

print("Checking that stop ids are unique...")
duplicates = 0
for i, f in enumerate(files):
    duplicates += con.sql(f"SELECT COUNT(*) - COUNT(DISTINCT id) FROM '{f}'").fetchall()[0][0]
    if i > 0:  # a train running over midnight at month end could appear in both files
        duplicates += con.sql(f"""
            SELECT COUNT(*) FROM (SELECT id FROM '{files[i - 1]}' INTERSECT SELECT id FROM '{f}')
        """).fetchall()[0][0]
if duplicates:
    raise SystemExit(f"Found {duplicates:,} duplicate stop ids - de-duplication needed before continuing.")
print("No duplicate stop ids found.")

print("Writing cleaned file...")
OUT_FILE.parent.mkdir(parents=True, exist_ok=True)
con.sql(f"""
    COPY (
        SELECT
            id                              AS stop_id,
            eva,
            station_name,
            train_type,
            {CATEGORY_SQL}                  AS category,
            train_number,
            line_number,
            train_line_ride_id              AS ride_id,
            train_line_station_num          AS stop_number,
            final_destination_station,
            planned_time,
            delay_in_min                    AS delay_min,
            coalesce(arrival_is_canceled, false)
              OR coalesce(departure_is_canceled, false) AS is_cancelled
        FROM labelled
        WHERE cleaning_label = 'kept'
    ) TO '{OUT_FILE.as_posix()}' (FORMAT parquet, COMPRESSION zstd)
""")

summary = con.sql(f"""
    SELECT
        COUNT(*)                                   AS rows,
        COUNT(DISTINCT eva)                        AS stations,
        SUM(is_cancelled::INT)                     AS cancelled_stops,
        MIN(planned_time)                          AS first_planned,
        MAX(planned_time)                          AS last_planned
    FROM '{OUT_FILE.as_posix()}'
""").df()
rows_out = int(summary.loc[0, "rows"])
total_in = int(label_counts["rows"].sum())
print(summary.to_string(index=False))

# ---- Write a small Markdown report that is committed to Git ----
REPORT_FILE.parent.mkdir(parents=True, exist_ok=True)
descriptions = {
    "missing_delay": "No delay value (stop had no planned record)",
    "outside_window": "Planned time outside Nov 2025 - Oct 2026",
    "bus_or_taxi": "Rail replacement bus / taxi, not a train",
    "impossible_early": "More than 5 minutes early (data error)",
}
lines = [
    "# Cleaning report",
    "",
    "Generated by `scripts/clean_data.py`.",
    "",
    f"- Raw files: {len(files)} (`{Path(files[0]).name}` to `{Path(files[-1]).name}`)",
    f"- Raw rows read: **{total_in:,}**",
    f"- Rows kept after cleaning: **{rows_out:,}** ({100 * rows_out / total_in:.1f}%)",
    f"- Stations: {int(summary.loc[0, 'stations']):,}",
    f"- Cancelled stops (kept, but excluded from delay averages): {int(summary.loc[0, 'cancelled_stops']):,}",
    f"- Planned times from {summary.loc[0, 'first_planned']} to {summary.loc[0, 'last_planned']}",
    "",
    "| Rule | Rows removed | Share of raw rows |",
    "|---|---:|---:|",
]
for label, desc in descriptions.items():
    n = int(label_counts.loc[label_counts.cleaning_label == label, "rows"].sum())
    lines.append(f"| {desc} | {n:,} | {100 * n / total_in:.2f}% |")
lines.append("")
lines.append("Duplicate stop ids: none found (checked within each month and between neighbouring months).")
REPORT_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")
print(f"Report written to {REPORT_FILE}")
