"""
Phase 3: Run the SQL analysis queries and save small summary tables for the dashboard.

Each file in sql/ is one SELECT query over the cleaned data (exposed as a view called `stops`).
The result of sql/<name>.sql is saved as app_data/<name>.parquet.

Why: the cleaned data has ~100+ million rows (several GB) - far too big for free hosting.
The summary tables are a few MB and still let the dashboard answer every question.

Run from the project folder:  python scripts/build_aggregates.py
"""
from pathlib import Path

import duckdb

CLEAN_FILE = Path("data/clean/stops.parquet")
SQL_DIR = Path("sql")
OUT_DIR = Path("app_data")

OUT_DIR.mkdir(exist_ok=True)
con = duckdb.connect()
con.sql("SET memory_limit = '8GB'")
con.sql(f"CREATE VIEW stops AS SELECT * FROM '{CLEAN_FILE.as_posix()}'")

for sql_file in sorted(SQL_DIR.glob("*.sql")):
    out_file = OUT_DIR / f"{sql_file.stem}.parquet"
    query = sql_file.read_text(encoding="utf-8")
    con.sql(f"COPY ({query}) TO '{out_file.as_posix()}' (FORMAT parquet, COMPRESSION zstd)")
    rows = con.sql(f"SELECT COUNT(*) FROM '{out_file.as_posix()}'").fetchall()[0][0]
    size_mb = out_file.stat().st_size / 1_000_000
    print(f"{sql_file.name:<15} -> {out_file}  {rows:>10,} rows  {size_mb:6.1f} MB")
