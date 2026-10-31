import streamlit as st
from sources import YEARS, fmt_num, query, urn_url

st.title("📜 Atti normativi")
st.caption(
    "Gli atti con codice `AAGG######`: sono gli unici che Normattiva "
    "indicizza e gli unici che entrano in legal-graph. Gli altri atti "
    "pubblicati in Gazzetta non esistono in nessun corpus normativo."
)

year = st.selectbox("Anno", YEARS, index=len(YEARS) - 1)

df = query(
    """SELECT data_pubblicazione, tipo_atto, estremi, titolo, ente, urn_normattiva
       FROM clean_input WHERE codice_genere = 'G'
       ORDER BY data_pubblicazione DESC""",
    year,
)

if df.empty:
    st.warning("Nessun atto normativo per l'anno selezionato.")
    st.stop()

tipi = sorted(df["tipo_atto"].dropna().unique())
scelti = st.multiselect("Tipo di atto", tipi, default=tipi)
df = df[df["tipo_atto"].isin(scelti)]

k1, k2 = st.columns(2)
k1.metric("Atti", fmt_num(len(df)))
k2.metric("Con URN", fmt_num(int(df["urn_normattiva"].ne("").sum())))

df = df.assign(link=df["urn_normattiva"].map(lambda u: urn_url(u) if u else None))

st.dataframe(
    df,
    width="stretch",
    hide_index=True,
    column_config={
        "data_pubblicazione": st.column_config.DateColumn("Data", format="YYYY-MM-DD"),
        "tipo_atto": "Tipo",
        "estremi": "Estremi",
        "titolo": st.column_config.TextColumn("Oggetto", width="large"),
        "ente": "Ente",
        "urn_normattiva": "URN",
        "link": st.column_config.LinkColumn("Normattiva", display_text="apri"),
    },
)
