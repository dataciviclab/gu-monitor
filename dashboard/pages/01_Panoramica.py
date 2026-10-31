import plotly.express as px
import streamlit as st
from sources import YEARS, fmt_num, fmt_pct, query

st.title("🏛️ Gazzetta Ufficiale — Panoramica")
st.caption(
    "Tutti gli atti pubblicati nelle 7 serie. `codice_genere` separa i "
    "**normativi** (codici `AAGG######`, gli unici che Normattiva indicizza) "
    "dal resto: avvisi, concorsi, sentenze, notifiche."
)

year = st.selectbox("Anno", YEARS, index=len(YEARS) - 1)

kpi = query(
    """SELECT count(*) AS atti,
              count(*) FILTER (WHERE codice_genere = 'G') AS normativi,
              count(*) FILTER (WHERE codice_genere = 'G' AND urn_normattiva <> '') AS con_urn,
              count(DISTINCT serie) AS serie,
              count(DISTINCT ente) AS enti,
              count(DISTINCT sezione) AS sezioni
       FROM clean_input""",
    year,
).iloc[0]

k1, k2, k3, k4 = st.columns(4)
k1.metric("Atti pubblicati", fmt_num(kpi["atti"]))
k2.metric("Atti normativi", fmt_num(kpi["normativi"]))
k3.metric("Con URN Normattiva", fmt_pct(100 * kpi["con_urn"] / kpi["normativi"] if kpi["normativi"] else 0))
k4.metric("Serie", fmt_num(kpi["serie"]))

st.divider()

df_serie = query(
    """SELECT serie, codice_genere, count(*) AS atti
       FROM clean_input GROUP BY 1, 2 ORDER BY atti DESC""",
    year,
)
fig = px.bar(
    df_serie,
    x="serie",
    y="atti",
    color="codice_genere",
    barmode="stack",
    labels={"serie": "", "atti": "atti", "codice_genere": ""},
    color_discrete_map={"G": "#6366f1", "A": "#4b5563"},
)
fig.update_layout(height=340, margin={"t": 10, "b": 10}, legend_title_text="")
st.subheader("Atti per serie")
st.plotly_chart(fig, width="stretch")

col_giorno, col_tipi = st.columns([2, 1])

with col_giorno:
    df_giorno = query(
        """SELECT data_pubblicazione,
                  sum(CASE WHEN codice_genere = 'G' THEN 1 ELSE 0 END) AS normativi,
                  sum(CASE WHEN codice_genere = 'A' THEN 1 ELSE 0 END) AS altri
           FROM clean_input GROUP BY 1 ORDER BY 1""",
        year,
    )
    fig = px.line(
        df_giorno,
        x="data_pubblicazione",
        y=["normativi", "altri"],
        labels={"value": "atti", "variable": "", "data_pubblicazione": ""},
        color_discrete_sequence=["#6366f1", "#4b5563"],
    )
    fig.update_layout(height=320, margin={"t": 10, "b": 10}, legend_title_text="")
    st.subheader("Atti per giorno")
    st.plotly_chart(fig, width="stretch")

with col_tipi:
    df_tipi = query(
        """SELECT tipo_atto, count(*) AS atti
           FROM clean_input WHERE codice_genere = 'G'
           GROUP BY 1 ORDER BY atti DESC""",
        year,
    )
    fig = px.bar(
        df_tipi.head(8),
        x="atti",
        y="tipo_atto",
        orientation="h",
        labels={"atti": "", "tipo_atto": ""},
    )
    fig.update_layout(height=320, margin={"t": 10, "b": 10})
    st.subheader("Normativi per tipo")
    st.plotly_chart(fig, width="stretch")

st.divider()

df_enti = query(
    """SELECT ente, count(*) AS atti
       FROM clean_input WHERE ente IS NOT NULL
       GROUP BY 1 ORDER BY atti DESC LIMIT 15""",
    year,
)
st.subheader("Enti che pubblicano di più")
st.caption(
    "Solo le serie in cui l'ente è dichiarato dalla fonte (SG, S3, S4). "
    "Su P2 e S5 il campo della Gazzetta è una rubrica, quindi `ente` è NULL."
)
fig = px.bar(
    df_enti.iloc[::-1],
    x="atti",
    y="ente",
    orientation="h",
    labels={"atti": "", "ente": ""},
)
fig.update_layout(height=420, margin={"t": 10, "b": 10})
st.plotly_chart(fig, width="stretch")
