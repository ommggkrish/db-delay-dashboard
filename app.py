"""
Phase 4: Deutsche Bahn Delay Dashboard (Streamlit).

The app only reads the small summary tables in app_data/ (built by scripts/build_aggregates.py)
and runs DuckDB SQL on them for whatever filters the user picks.

Run locally from the project folder:  streamlit run app.py
"""
from pathlib import Path

import altair as alt
import duckdb
import pandas as pd
import streamlit as st

APP_DIR = Path(__file__).parent
DATA_DIR = APP_DIR / "app_data"
FINDINGS_FILE = APP_DIR / "reports" / "key_findings.md"

CATEGORY_ORDER = ["ICE", "IC/EC", "Other long-distance", "RE", "RB", "Other regional", "S-Bahn"]
WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
ACCENT = "#C8102E"   # red for "bad" values (delay)
NEUTRAL = "#4C6A92"  # blue-grey for neutral values

st.set_page_config(page_title="DB Delay Dashboard", page_icon="🚆", layout="wide")


# ---------- Data access ----------
@st.cache_resource
def get_connection() -> duckdb.DuckDBPyConnection:
    """One DuckDB connection for the whole app, with a view per summary table."""
    con = duckdb.connect()
    for name in ("daily", "hourly", "routes", "stations"):
        path = (DATA_DIR / f"{name}.parquet").as_posix()
        con.sql(f"CREATE VIEW {name} AS SELECT * FROM '{path}'")
    return con


@st.cache_data(show_spinner=False)
def query(sql: str, params: tuple = ()) -> pd.DataFrame:
    """Run a SQL query with parameters. Cached, so the same filter is only computed once."""
    cursor = get_connection().cursor()  # a cursor per call is safe when several users are online
    return cursor.execute(sql, list(params)).df()


# Shared SQL snippet: turns summed counts into the measures we show.
# NULLIF avoids dividing by zero when a filter has no (non-cancelled) stops.
MEASURES = """
    SUM(stops)                                                      AS stops,
    SUM(delay_sum) / NULLIF(SUM(stops) - SUM(cancelled), 0)         AS avg_delay,
    100.0 * SUM(on_time) / NULLIF(SUM(stops) - SUM(cancelled), 0)   AS on_time_pct,
    100.0 * SUM(cancelled) / NULLIF(SUM(stops), 0)                  AS cancelled_pct
"""


# ---------- Sidebar filters ----------
bounds = query("SELECT MIN(date) AS first, MAX(date) AS last FROM daily").iloc[0]
first_day, last_day = bounds["first"].date(), bounds["last"].date()
stations = query("SELECT eva, station_name FROM stations ORDER BY stops DESC")
name_to_eva = dict(zip(stations.station_name, stations.eva))

st.sidebar.header("Filters")
date_range = st.sidebar.date_input(
    "Date range", value=(first_day, last_day), min_value=first_day, max_value=last_day
)
# While the user is still picking the second date, date_input returns only one date.
start, end = date_range if len(date_range) == 2 else (date_range[0], date_range[0])

categories = st.sidebar.multiselect(
    "Train category", CATEGORY_ORDER, default=CATEGORY_ORDER,
    help="ICE and IC/EC are long-distance trains, RE and RB regional trains, S-Bahn city rail.",
)
station_names = st.sidebar.multiselect(
    "Stations (empty = all)", list(name_to_eva), placeholder="All stations",
    help="Stations are sorted by number of stops, so the biggest stations come first.",
)
selected_evas = [name_to_eva[n] for n in station_names]

if not categories:
    st.warning("Select at least one train category.")
    st.stop()

# WHERE clause used by every query on the daily table.
# `len(?) = 0 OR list_contains(?, eva)` means: no stations picked -> all stations.
DAILY_WHERE = """
    date BETWEEN ? AND ?
    AND list_contains(?, category)
    AND (len(?) = 0 OR list_contains(?, eva))
"""
daily_params = (start, end, categories, selected_evas, selected_evas)

# The hourly and routes tables are monthly, so they use the months touched by the date range.
month_start = start.replace(day=1)
month_end = end.replace(day=1)


# ---------- Header and KPIs ----------
st.title("🚆 Deutsche Bahn Delay Dashboard")
st.caption(
    f"Train stops from **{start:%d %b %Y}** to **{end:%d %b %Y}** · "
    "On time = less than 6 minutes late (DB definition) · "
    "Data: [piebro/deutsche-bahn-data](https://huggingface.co/datasets/piebro/deutsche-bahn-data) (CC BY 4.0)"
)

kpi = query(f"""
    SELECT {MEASURES},
           100.0 * SUM(delayed_15) / NULLIF(SUM(stops) - SUM(cancelled), 0) AS delayed_15_pct
    FROM daily WHERE {DAILY_WHERE}
""", daily_params).iloc[0]

if pd.isna(kpi["stops"]) or kpi["stops"] == 0:
    st.info("No data for this filter combination.")
    st.stop()

c1, c2, c3, c4, c5 = st.columns(5)
c1.metric("Train stops analysed", f"{kpi['stops'] / 1e6:.1f} M" if kpi["stops"] >= 1e6 else f"{kpi['stops']:,.0f}")
c2.metric("Average delay", f"{kpi['avg_delay']:.1f} min")
c3.metric("On time (< 6 min)", f"{kpi['on_time_pct']:.1f} %")
c4.metric("15+ min late", f"{kpi['delayed_15_pct']:.1f} %")
c5.metric("Cancelled stops", f"{kpi['cancelled_pct']:.1f} %")


def bar_chart(df: pd.DataFrame, x: str, y: str, x_title: str, sort=None, color=ACCENT, fmt=".1f"):
    """Horizontal bar chart with values as tooltips."""
    return (
        alt.Chart(df)
        .mark_bar(color=color)
        .encode(
            x=alt.X(f"{x}:Q", title=x_title),
            y=alt.Y(f"{y}:N", title=None, sort=sort, axis=alt.Axis(labelLimit=400)),  # don't cut long names
            tooltip=[alt.Tooltip(f"{y}:N"), alt.Tooltip(f"{x}:Q", format=fmt), alt.Tooltip("stops:Q", format=",")],
        )
    )


tab_overview, tab_stations, tab_routes, tab_trends, tab_findings = st.tabs(
    ["Overview", "Worst stations", "Worst routes", "Trends", "Key findings"]
)

# ---------- Overview: by train category and hour of day ----------
with tab_overview:
    left, right = st.columns(2)

    by_category = query(f"""
        SELECT category, {MEASURES} FROM daily WHERE {DAILY_WHERE}
        GROUP BY category
    """, daily_params)
    with left:
        st.subheader("By train category")
        metric = st.radio("Measure", ["Average delay (min)", "On time (%)"], horizontal=True, key="cat_metric")
        col = "avg_delay" if metric.startswith("Average") else "on_time_pct"
        color = ACCENT if col == "avg_delay" else NEUTRAL
        order = [c for c in CATEGORY_ORDER if c in set(by_category.category)]
        st.altair_chart(bar_chart(by_category, col, "category", metric, sort=order, color=color),
                        width="stretch")

    by_hour = query(f"""
        SELECT hour, {MEASURES} FROM hourly
        WHERE month BETWEEN ? AND ?
          AND list_contains(?, category)
          AND (len(?) = 0 OR list_contains(?, eva))
        GROUP BY hour ORDER BY hour
    """, (month_start, month_end, categories, selected_evas, selected_evas))
    with right:
        st.subheader("By hour of day")
        st.caption("Planned departure hour. Uses whole months of the selected date range.")
        hour_chart = alt.Chart(by_hour).encode(x=alt.X("hour:O", title="Hour of day"))
        st.altair_chart(
            hour_chart.mark_bar(color=ACCENT, opacity=0.85).encode(
                y=alt.Y("avg_delay:Q", title="Average delay (min)"),
                tooltip=["hour", alt.Tooltip("avg_delay:Q", format=".1f"),
                         alt.Tooltip("on_time_pct:Q", format=".1f"), alt.Tooltip("stops:Q", format=",")],
            ),
            width="stretch",
        )

# ---------- Worst stations ----------
with tab_stations:
    st.subheader("Worst stations")
    a, b = st.columns(2)
    min_stops = a.number_input("Minimum train stops at a station", min_value=100, value=5000, step=500,
                               help="Small stations with few trains give unreliable averages.")
    rank_by = b.radio("Rank by", ["Average delay", "Lowest on-time %"], horizontal=True)
    order_sql = "avg_delay DESC" if rank_by == "Average delay" else "on_time_pct ASC"
    worst_stations = query(f"""
        SELECT s.station_name AS station, {MEASURES}
        FROM daily AS d
        JOIN (SELECT eva, station_name FROM stations) AS s USING (eva)  -- only the name, not its 'stops' column
        WHERE {DAILY_WHERE}
        GROUP BY s.station_name
        HAVING SUM(stops) >= ?
        ORDER BY {order_sql}
        LIMIT 15
    """, daily_params + (min_stops,))
    if worst_stations.empty:
        st.info("No station has that many stops for this filter. Lower the minimum.")
    else:
        col = "avg_delay" if rank_by == "Average delay" else "on_time_pct"
        title = "Average delay (min)" if col == "avg_delay" else "On time (%)"
        st.altair_chart(bar_chart(worst_stations, col, "station", title, sort=None,
                                  color=ACCENT if col == "avg_delay" else NEUTRAL),
                        width="stretch")
        st.dataframe(
            worst_stations.rename(columns={"station": "Station", "stops": "Stops", "avg_delay": "Avg delay (min)",
                                           "on_time_pct": "On time %", "cancelled_pct": "Cancelled %"}),
            hide_index=True, width="stretch",
            column_config={c: st.column_config.NumberColumn(format="%.1f")
                           for c in ("Avg delay (min)", "On time %", "Cancelled %")},
        )

# ---------- Worst routes ----------
with tab_routes:
    st.subheader("Worst routes")
    st.caption("Route = first station → final destination of a train. "
               "Delay is measured on arrival at the final destination. Uses whole months of the date range.")
    min_trips = st.number_input("Minimum trips on a route", min_value=50, value=1000, step=100)
    worst_routes = query(f"""
        SELECT category, origin || ' → ' || destination AS route,
               SUM(trips) AS stops,
               SUM(delay_sum) / NULLIF(SUM(trips) - SUM(cancelled), 0)       AS avg_delay,
               100.0 * SUM(on_time) / NULLIF(SUM(trips) - SUM(cancelled), 0) AS on_time_pct,
               100.0 * SUM(cancelled) / NULLIF(SUM(trips), 0)                AS cancelled_pct
        FROM routes
        WHERE month BETWEEN ? AND ?
          AND list_contains(?, category)
          AND (len(?) = 0 OR list_contains(?, origin) OR list_contains(?, destination))
        GROUP BY ALL
        HAVING SUM(trips) >= ?
        ORDER BY avg_delay DESC
        LIMIT 15
    """, (month_start, month_end, categories, station_names, station_names, station_names, min_trips))
    if worst_routes.empty:
        st.info("No route has that many trips for this filter. Lower the minimum.")
    else:
        worst_routes["label"] = worst_routes["category"] + " · " + worst_routes["route"]
        st.altair_chart(bar_chart(worst_routes, "avg_delay", "label", "Average arrival delay at destination (min)"),
                        width="stretch")
        st.dataframe(
            worst_routes[["category", "route", "stops", "avg_delay", "on_time_pct", "cancelled_pct"]].rename(
                columns={"category": "Category", "route": "Route", "stops": "Trips", "avg_delay": "Avg delay (min)",
                         "on_time_pct": "On time %", "cancelled_pct": "Cancelled %"}),
            hide_index=True, width="stretch",
            column_config={c: st.column_config.NumberColumn(format="%.1f")
                           for c in ("Avg delay (min)", "On time %", "Cancelled %")},
        )

# ---------- Trends ----------
with tab_trends:
    left, right = st.columns(2)
    by_weekday = query(f"""
        SELECT isodow(date) AS dow, {MEASURES} FROM daily WHERE {DAILY_WHERE}
        GROUP BY dow ORDER BY dow
    """, daily_params)
    by_weekday["weekday"] = by_weekday["dow"].map(lambda d: WEEKDAYS[d - 1])
    with left:
        st.subheader("By day of week")
        st.altair_chart(bar_chart(by_weekday, "avg_delay", "weekday", "Average delay (min)", sort=WEEKDAYS),
                        width="stretch")

    by_month = query(f"""
        SELECT date_trunc('month', date) AS month, {MEASURES} FROM daily WHERE {DAILY_WHERE}
        GROUP BY month ORDER BY month
    """, daily_params)
    with right:
        st.subheader("By month")
        st.altair_chart(
            alt.Chart(by_month).mark_line(point=True, color=NEUTRAL).encode(
                x=alt.X("yearmonth(month):T", title=None),
                y=alt.Y("on_time_pct:Q", title="On time (%)", scale=alt.Scale(zero=False)),
                tooltip=[alt.Tooltip("yearmonth(month):T", title="Month"),
                         alt.Tooltip("on_time_pct:Q", format=".1f"), alt.Tooltip("avg_delay:Q", format=".1f")],
            ),
            width="stretch",
        )

    st.subheader("Day by day")
    by_day = query(f"""
        SELECT date, {MEASURES} FROM daily WHERE {DAILY_WHERE}
        GROUP BY date ORDER BY date
    """, daily_params)
    st.altair_chart(
        alt.Chart(by_day).mark_line(color=ACCENT).encode(
            x=alt.X("date:T", title=None),
            y=alt.Y("avg_delay:Q", title="Average delay (min)"),
            tooltip=[alt.Tooltip("date:T"), alt.Tooltip("avg_delay:Q", format=".1f"),
                     alt.Tooltip("on_time_pct:Q", format=".1f"), alt.Tooltip("stops:Q", format=",")],
        ),
        width="stretch",
    )

# ---------- Key findings ----------
with tab_findings:
    st.caption("Computed from the full dataset (all stations, all categories, Nov 2025 – Oct 2026) "
               "by scripts/key_findings.py; not affected by the filters.")
    if FINDINGS_FILE.exists():
        st.markdown(FINDINGS_FILE.read_text(encoding="utf-8"))
    else:
        st.info("Run `python scripts/key_findings.py` to generate the key findings.")
