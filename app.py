#!/usr/bin/env python3
"""Entry point per Streamlit Cloud.

La dashboard vive in `dashboard/` (standard del Lab). Questo file esiste solo
perché l'app Streamlit è deployata su `app.py`: esegue la dashboard vera e
mette la sua cartella nel path, così i `from sources import ...` delle pagine
funzionano. Da rimuovere quando il main file path punta a `dashboard/app.py`.
"""

import runpy
import sys
from pathlib import Path

DASH = Path(__file__).resolve().parent / "dashboard"
sys.path.insert(0, str(DASH))

runpy.run_path(str(DASH / "app.py"), run_name="__main__")
