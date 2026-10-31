import plotly.express as px
import streamlit as st
from sources import YEARS, fmt_num, query

st.title("🗂️ Sezioni")
st.caption(
    "La rubrica della pagina: `Eredita'`, `Concorsi`, `LEGGI ED ALTRI ATTI NORMATIVI`. "
    "Attenzione alla granularità: su P2 e S5 è il secondo livello, sulle altre serie il primo."
)

year = st.selectbox("Anno", YEARS, index=len(YEARS) - 1)

df = query(
    """SELECT serie, sezione, count(*) AS atti
       FROM clean_input WHERE sezione IS NOT NULL
       GROUP BY 1, 2 ORDER BY atti DESC""",
    year,
)

serie = sorted(df["serie"].unique())
scelta = st.selectbox("Serie", ["Tutte", *serie])
if scelta != "Tutte":
    df = df[df["serie"] == scelta]

top = df.head(20)
fig = px.bar(
    top.iloc[::-1],
    x="atti",
    y="sezione",
    color="serie" if scelta == "Tutte" else None,
    orientation="h",
    labels={"atti": "", "sezione": "", "serie": ""},
)
fig.update_layout(height=520, margin={"t": 10, "b": 10}, legend_title_text="")
st.plotly_chart(fig, width="stretch")

st.metric("Sezioni distinte", fmt_num(df["sezione"].nunique()))
st.caption("La serie S3 (Regioni) non espone una rubrica nel markup: qui non compare.")
