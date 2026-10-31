#!/usr/bin/env python3
"""GU Monitor · Dashboard Streamlit — Gazzetta Ufficiale."""

import streamlit as st
from lab_connectors.branding import apply_branding

st.set_page_config(
    page_title="GU Monitor · Gazzetta Ufficiale",
    page_icon="🏛️",
    layout="wide",
    initial_sidebar_state="expanded",
)

apply_branding(
    repo_name="gu-monitor",
    repo_url="https://github.com/dataciviclab/gu-monitor",
)

pages = {
    "": [
        st.Page("pages/01_Panoramica.py", title="Panoramica", icon="📊", default=True),
    ],
    "Analisi": [
        st.Page("pages/02_Normativi.py", title="Atti normativi", icon="📜"),
        st.Page("pages/03_Sezioni.py", title="Sezioni", icon="🗂️"),
    ],
    "Strumenti": [
        st.Page("pages/04_SQL.py", title="Query SQL", icon="🧪"),
    ],
}

st.navigation(pages, position="sidebar").run()
