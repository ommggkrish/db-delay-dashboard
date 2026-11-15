# Deutsche Bahn Delay Dashboard

An interactive dashboard that analyses German train delays using open data from Deutsche Bahn.

🚧 **Work in progress.** Built step by step; see the commit history.

## Planned features
- Average delay and on-time percentage by station, train type (ICE, IC, RE, S-Bahn, …) and hour of day
- Worst stations and worst routes
- Delay trends by day of week and month
- Filters for station, train type and date range
- Key findings based on the real data

## Tech stack
Python · pandas · DuckDB (SQL) · Streamlit

## Data source
[piebro/deutsche-bahn-data](https://huggingface.co/datasets/piebro/deutsche-bahn-data), licensed under
[CC BY 4.0](https://creativecommons.org/licenses/by/4.0/). The data was originally collected from the
Deutsche Bahn Timetables API.