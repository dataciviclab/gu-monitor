#!/usr/bin/env python3
"""GU Monitor — Dashboard Streamlit.

Avvio:  streamlit run app.py
"""

from pathlib import Path

import duckdb
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

# ── Config ───────────────────────────────────────────────────────────────────

st.set_page_config(page_title="GU Monitor", page_icon="🏛️", layout="wide")

PARQUET = Path(__file__).parent / "data" / "gu_acts.parquet"


@st.cache_resource
def get_connection():
    con = duckdb.connect(":memory:")
    con.execute(f"CREATE TABLE atti AS SELECT * FROM read_parquet('{PARQUET}')")
    return con


def q(sql: str):
    return get_connection().execute(sql).fetchdf()


# ── Sidebar: filtri ──────────────────────────────────────────────────────────

st.sidebar.title("🏛️ GU Monitor")
st.sidebar.caption("Gazzetta Ufficiale — intelligence in tempo reale")

df_enti = q("SELECT DISTINCT ente FROM atti WHERE ente IS NOT NULL ORDER BY ente")
df_tipi = q("SELECT DISTINCT tipo_atto FROM atti ORDER BY tipo_atto")
df_serie = q("SELECT DISTINCT serie FROM atti ORDER BY serie")
df_date = q(
    "SELECT MIN(CAST(data_pubblicazione AS DATE)) AS min_d, "
    "MAX(CAST(data_pubblicazione AS DATE)) AS max_d FROM atti"
)

filter_serie = st.sidebar.multiselect(
    "Serie", options=df_serie["serie"].tolist(), default=df_serie["serie"].tolist(),
)
filter_tipo = st.sidebar.multiselect(
    "Tipo atto", options=df_tipi["tipo_atto"].tolist(), default=df_tipi["tipo_atto"].tolist(),
)
filter_ente = st.sidebar.multiselect(
    "Ente", options=df_enti["ente"].tolist(), default=[], placeholder="Tutti gli enti",
)

min_date, max_date = df_date["min_d"].iloc[0], df_date["max_d"].iloc[0]
filter_date = st.sidebar.date_input(
    "Periodo", value=(min_date, max_date), min_value=min_date, max_value=max_date,
)
search = st.sidebar.text_input("🔍 Cerca nel titolo")

# ── Costruisci WHERE ────────────────────────────────────────────────────────

def esc(v: str) -> str:
    """Escape single quotes for SQL."""
    return v.replace("'", "''")


where_parts = []
if filter_serie:
    in_list = ", ".join("'" + esc(s) + "'" for s in filter_serie)
    where_parts.append("serie IN (" + in_list + ")")
if filter_tipo:
    in_list = ", ".join("'" + esc(t) + "'" for t in filter_tipo)
    where_parts.append("tipo_atto IN (" + in_list + ")")
if filter_ente:
    in_list = ", ".join("'" + esc(e) + "'" for e in filter_ente)
    where_parts.append("ente IN (" + in_list + ")")
if len(filter_date) == 2:
    d0, d1 = filter_date
    where_parts.append(f"CAST(data_pubblicazione AS DATE) BETWEEN '{d0}' AND '{d1}'")
if search:
    where_parts.append(f"titolo ILIKE '%{esc(search)}%'")

where_sql = (" WHERE " + " AND ".join(where_parts)) if where_parts else ""
where_cond = " AND ".join(where_parts) if where_parts else ""

# ── KPI ──────────────────────────────────────────────────────────────────────

kpis = q(f"""
    SELECT COUNT(*) AS totale, COUNT(DISTINCT serie) AS n_serie,
           COUNT(DISTINCT ente) AS n_enti,
           COUNT(DISTINCT CAST(data_pubblicazione AS DATE)) AS n_giorni
    FROM atti {where_sql}
""")

st.title("🏛️ Gazzetta Ufficiale — Monitor")
st.caption(
    f"**{kpis['totale'].iloc[0]:,}** atti · "
    f"**{kpis['n_serie'].iloc[0]}** serie · "
    f"**{kpis['n_enti'].iloc[0]:,}** enti · "
    f"**{kpis['n_giorni'].iloc[0]}** giorni"
)

# ── Riga 1: Trend + Serie ───────────────────────────────────────────────────

col_trend, col_serie = st.columns([3, 2])

with col_trend:
    st.subheader("📈 Atti per giorno")
    df_trend = q(f"""
        SELECT CAST(data_pubblicazione AS DATE) AS giorno, serie, COUNT(*) AS n
        FROM atti {where_sql}
        GROUP BY giorno, serie ORDER BY giorno
    """)
    if not df_trend.empty:
        df_pivot = df_trend.pivot(index="giorno", columns="serie", values="n").fillna(0)
        fig = go.Figure()
        for col in df_pivot.columns:
            fig.add_trace(go.Scatter(
                x=df_pivot.index, y=df_pivot[col], name=col,
                mode="lines+markers", stackgroup="one",
            ))
        fig.update_layout(
            margin=dict(l=0, r=0, t=0, b=0), height=350,
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
            xaxis_title="", yaxis_title="Atti", hovermode="x unified",
        )
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("Nessun dato per i filtri selezionati.")

with col_serie:
    st.subheader("📊 Per serie")
    df_serie_cnt = q(f"""
        SELECT serie, COUNT(*) AS n FROM atti {where_sql}
        GROUP BY serie ORDER BY n DESC
    """)
    if not df_serie_cnt.empty:
        colors_map = {
            "SG": "#636EFA", "S1": "#EF553B", "S2": "#00CC96",
            "S3": "#AB63FA", "S4": "#FFA15A", "S5": "#19D3F3", "P2": "#FF6692",
        }
        fig = px.bar(
            df_serie_cnt, x="n", y="serie", orientation="h", text="n",
            color="serie", color_discrete_map=colors_map,
        )
        fig.update_layout(
            margin=dict(l=0, r=0, t=0, b=0), height=350,
            showlegend=False, xaxis_title="", yaxis_title="",
        )
        fig.update_traces(textposition="outside")
        st.plotly_chart(fig, use_container_width=True)

# ── Riga 2: Top enti + Tipo atto ────────────────────────────────────────────

col_enti, col_tipi = st.columns(2)

with col_enti:
    st.subheader("🏢 Top 15 enti")
    ente_filter = [p for p in where_parts if not p.startswith("ente ")]
    df_enti_top = q(f"""
        SELECT ente, COUNT(*) AS n FROM atti
        WHERE ente IS NOT NULL {(' AND ' + ' AND '.join(ente_filter)) if ente_filter else ''}
        GROUP BY ente ORDER BY n DESC LIMIT 15
    """)
    if not df_enti_top.empty:
        df_enti_top["ente_short"] = df_enti_top["ente"].str[:55]
        fig = px.bar(
            df_enti_top.sort_values("n"), x="n", y="ente_short",
            orientation="h", text="n", color_discrete_sequence=["#636EFA"],
        )
        fig.update_layout(
            margin=dict(l=0, r=0, t=0, b=0), height=450, xaxis_title="", yaxis_title="",
        )
        fig.update_traces(textposition="outside")
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("Nessun ente nei dati filtrati.")

with col_tipi:
    st.subheader("📋 Per tipo di atto")
    df_tipi_cnt = q(f"""
        SELECT tipo_atto, COUNT(*) AS n FROM atti {where_sql}
        GROUP BY tipo_atto ORDER BY n DESC
    """)
    if not df_tipi_cnt.empty:
        fig = px.treemap(
            df_tipi_cnt, path=["tipo_atto"], values="n",
            color="n", color_continuous_scale="Blues",
        )
        fig.update_layout(margin=dict(l=0, r=0, t=0, b=0), height=450)
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("Nessun tipo nei dati filtrati.")

# ── Riga 3: Topic + Giorno settimana ────────────────────────────────────────

col_topic, col_giorno = st.columns(2)

with col_topic:
    st.subheader("🏷️ Topic")
    df_topics = q(f"""
        WITH split_topics AS (
            SELECT UNNEST(string_split(topic_str, ',')) AS topic
            FROM atti
            WHERE topic_str IS NOT NULL AND topic_str != ''
            {(' AND ' + where_cond) if where_cond else ''}
        )
        SELECT TRIM(topic) AS topic, COUNT(*) AS n FROM split_topics
        WHERE TRIM(topic) != '' GROUP BY TRIM(topic) ORDER BY n DESC
    """)
    if not df_topics.empty:
        fig = px.pie(
            df_topics, values="n", names="topic", hole=0.4,
            color_discrete_sequence=px.colors.qualitative.Set2,
        )
        fig.update_layout(
            margin=dict(l=0, r=0, t=0, b=0), height=400,
            showlegend=True, legend=dict(orientation="v", font=dict(size=11)),
        )
        fig.update_traces(textinfo="label+value")
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("Nessun topic classificato nei dati filtrati.")

with col_giorno:
    st.subheader("📅 Media atti per giorno settimana")
    df_giorno = q(f"""
        SELECT DAYNAME(CAST(data_pubblicazione AS DATE)) AS giorno,
               COUNT(*) AS totale,
               COUNT(DISTINCT CAST(data_pubblicazione AS DATE)) AS n_giorni,
               ROUND(COUNT(*) * 1.0 / COUNT(DISTINCT CAST(data_pubblicazione AS DATE)), 0) AS media
        FROM atti {where_sql}
        GROUP BY giorno ORDER BY media DESC
    """)
    if not df_giorno.empty:
        giorno_it = {
            "Monday": "Lun", "Tuesday": "Mar", "Wednesday": "Mer",
            "Thursday": "Gio", "Friday": "Ven", "Saturday": "Sab", "Sunday": "Dom",
        }
        giorno_ord = list(giorno_it.keys())
        df_giorno["ord"] = df_giorno["giorno"].map({g: i for i, g in enumerate(giorno_ord)})
        df_giorno = df_giorno.sort_values("ord")
        df_giorno["giorno_label"] = df_giorno["giorno"].map(giorno_it)
        fig = px.bar(
            df_giorno, x="giorno_label", y="media", text="media",
            color="media", color_continuous_scale="Teal",
        )
        fig.update_layout(
            margin=dict(l=0, r=0, t=0, b=0), height=400,
            xaxis_title="", yaxis_title="Atti / giorno", coloraxis_showscale=False,
        )
        fig.update_traces(textposition="outside")
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("Nessun dato.")

# ── Tabella dati ─────────────────────────────────────────────────────────────

st.markdown("---")
st.subheader("📋 Tabella atti")

df_table = q(f"""
    SELECT id, serie, gazzetta_numero AS n_gazzetta,
           data_pubblicazione AS data,
           tipo_atto, ente, titolo, topic_str AS topic,
           CASE WHEN link IS NOT NULL AND link != ''
                THEN link ELSE NULL END AS link
    FROM atti {where_sql}
    ORDER BY data_pubblicazione DESC, serie
""")

if not df_table.empty:
    st.dataframe(
        df_table, use_container_width=True, height=400,
        column_config={
            "data": st.column_config.DateColumn("Data"),
            "serie": st.column_config.TextColumn("Serie", width="small"),
            "n_gazzetta": st.column_config.TextColumn("N° GU", width="small"),
            "tipo_atto": st.column_config.TextColumn("Tipo", width="medium"),
            "ente": st.column_config.TextColumn("Ente", width="medium"),
            "link": st.column_config.LinkColumn("🔗 Link", display_text="Apri"),
        },
    )
    st.caption(f"{len(df_table):,} atti · Dati: data/gu_acts.parquet")
else:
    st.info("Nessun atto corrisponde ai filtri selezionati.")

# ── Footer ───────────────────────────────────────────────────────────────────

st.markdown("---")
st.caption(
    "📦 [gu-monitor](https://github.com/dataciviclab/gu-monitor) · "
    "Dati: Gazzetta Ufficiale · "
    "Aggiornamento: GitHub Actions · Licenza: MIT"
)

