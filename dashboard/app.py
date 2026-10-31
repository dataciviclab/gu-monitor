#!/usr/bin/env python3
"""GU Monitor · Dashboard Streamlit — Gazzetta Ufficiale."""

from pathlib import Path

import streamlit as st
from lab_connectors.branding import apply_branding

st.set_page_config(
    page_title="GU Monitor · Gazzetta Ufficiale",
    page_icon="🏛️",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Path assoluti: la dashboard funziona anche quando è eseguita da un entry
# point diverso (es. lo shim `app.py` alla root usato da Streamlit Cloud).
PAGES = Path(__file__).parent / "pages"

apply_branding(
    repo_name="gu-monitor",
    repo_url="https://github.com/dataciviclab/gu-monitor",
)

pages = {
    "": [
        st.Page(str(PAGES / "01_Panoramica.py"), title="Panoramica", icon="📊", default=True),
    ],
    "Analisi": [
        st.Page(str(PAGES / "02_Normativi.py"), title="Atti normativi", icon="📜"),
        st.Page(str(PAGES / "03_Sezioni.py"), title="Sezioni", icon="🗂️"),
    ],
    "Strumenti": [
        st.Page(str(PAGES / "04_SQL.py"), title="Query SQL", icon="🧪"),
    ],
}

st.navigation(pages, position="sidebar").run()
