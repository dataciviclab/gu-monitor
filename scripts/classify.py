#!/usr/bin/env python3
"""GU Monitor — Classifier: arricchisce gli atti con ente, numero, topic."""

import json
import re
import sys
from collections import Counter
from pathlib import Path

# ── Topic keywords (synced with to_parquet.py) ─────────────────────────────
TOPIC_KEYWORDS = {
    "fisco": ["fiscale", "tributario", "tributi", "imposta", "irpef", "iva", "accisa",
              "bilancio", "rendicont"],
    "sanita": ["farmaco", "medicinale", "sanitario", "ospedaliero", "asl", "aifa",
               "medicin", "comirnaty", "linagliptin", "aciclovir", "eltrombopag", "mitapivat"],
    "lavoro": ["lavoro", "lavoratori", "impiego", "concors", "dipendente", "pubblico",
               "borsa di ricerca", "assegno di ricerca"],
    "ambiente": ["ambiente", "ecolog", "compost", "rifiuti", "inquinamento",
                 "bonifica", "sostenibilit"],
    "appalti": ["appalto", "contratto", "gara", "bandimento", "astante"],
    "pnrr": ["pnrr", "ripresa", "resilienza", "next generation"],
    "energia": ["energia", "elettric", "gas", "idrogeno", "carburante", "impianto fotovoltaico"],
    "giustizia": ["giustizia", "penale", "civile", "tribunale", "corte",
                  "notifica", "sentenza", "curatore", "falliment", "eredit"],
    "europa": ["europeo", "europea", "ue ", "regolamento (ue)", "decisione (ue)",
               "decisione pesc"],
    "agricoltura": ["agricoltura", "agricolo", "zootecnico", "alimentare", "pesca",
                    "viticolo", "denominazione di origine"],
    "istruzione": ["universit", "ricercat", "docente", "studente", "laurea",
                   "politecnico", "scuola"],
    "trasporti": ["trasport", "autostrad", "ferroviario", "aeronautico", "portuale"],
    "edilizia": ["edilizia", "casa", "immobiliare", "urbanistica", "catasto"],
    "sicurezza": ["sicurezza", "polizia", "carabinieri", "vigili del fuoco"],
    "business": ["societa'", "società", "cooperativ", "assemblea", "consiglio di amministrazione",
                 "s.p.a.", "s.r.l.", "s.a.s.", "conferimento"],
    "governo_locale": ["regione", "regionale", "provincia", "comune ", "comunale",
                       "concessione", "demaniale"],
    "sanita_farmaci": ["autorizzazione all'immissione in commercio", "immissione in commercio"],
}

# ── Ente patterns ──────────────────────────────────────────────────────

# SG/S3/S4: "ENTE - TIPO_ATTO ..."
ENTE_DASH_RE = re.compile(
    r"^(.+?)\s*-\s*(?:DECRETO|DETERMINA|COMUNICATO|ORDINANZA|"
    r"REGOLAMENTO|DECISIONE|RETTIFICA|GRADUATORIA|CONCORSO|AVVISO|"
    r"LEGGE|ANNULLAMENTO|DIARIO|TESTO COORDINATO|"
    r"AUTORIZZAZIONE|LIQUIDAZIONE|MODIFICA|REVOCA|VOLTURA|SOSTITUZIONE|"
    r"RINUNCIA|CONFERIMENTO|CONVOCAZIONE|NOMINA|ISCRIZIONE)",
    re.IGNORECASE,
)

# S3 regioni: "REGIONE X - LEGGE REGIONALE..." or "REGIONE X (PROVINCIA DI Y) - ..."
REGIONE_RE = re.compile(
    r"^(REGIONE\s+.+?)(?:\s*\(PROVINCIA\s+AUTONOMA\s+DI\s+(.+?)\))?\s*-",
    re.IGNORECASE,
)

# S4 con scadenza: "ENTE - CONCORSO (scad. date)"
ENTE_SCAD_RE = re.compile(
    r"^(.+?)\s*-\s*(?:CONCORSO|GRADUATORIA|AVVISO|DIARIO|RETTIFICA|ANNULLAMENTO)",
    re.IGNORECASE,
)

# S4 with parentheses: extract ente before " - "
ENTE_PARENS_RE = re.compile(r"^(.+?)\s+-\s+(?:CONCORSO|GRADUATORIA)")

# S2: no ente in title, all EU acts
# S5/P2: just entity name

# Number extraction
NUMERO_RE = re.compile(r"n\.?\s*(\d[\d/.]*)")


def extract_ente(titolo: str, serie: str, content: str) -> str | None:
    """Extract entity name from title."""

    # S2 (UE): no ente in title
    if serie == "S2":
        return "UNIONE EUROPEA"

    # S1 (Corte Cost): no ente
    if serie == "S1":
        return "CORTE COSTITUZIONALE"

    # S3 (Regioni): check regione pattern
    if serie == "S3":
        m = REGIONE_RE.match(titolo)
        if m:
            regione = m.group(1).strip()
            prov = m.group(2)
            if prov:
                return f"{regione} ({prov})"
            return regione

    # S5/P2: just entity name (no dash separator usually)
    if serie in ("S5", "P2"):
        # Try dash pattern first
        m = ENTE_DASH_RE.match(titolo)
        if m:
            return normalize_ente(m.group(1))
        # If no dash, the whole title is the entity
        return normalize_ente(titolo)

    # SG/S4: "ENTE - TIPO..."
    m = ENTE_DASH_RE.match(titolo)
    if m:
        return normalize_ente(m.group(1))

    # SG: just "LEGGE..." without ente
    return None


def normalize_ente(raw: str) -> str:
    """Clean entity name."""
    ente = raw.strip().strip('"').strip("'")
    # Remove trailing date patterns
    ente = re.sub(r"\s+\d+\s+\w+\s+\d{4}.*$", "", ente)
    # Remove "IL " prefix
    ente = re.sub(r"^IL\s+", "", ente)
    return ente.strip()


def extract_numero(titolo: str) -> str | None:
    """Extract act number."""
    m = NUMERO_RE.search(titolo)
    return m.group(1) if m else None


def extract_topics(titolo: str, content: str) -> list[str]:
    """Extract topic keywords from title + content snippet."""
    text = f"{titolo} {content}".lower()
    found = []
    for topic, keywords in TOPIC_KEYWORDS.items():
        if any(kw in text for kw in keywords):
            found.append(topic)
    return found


def classify_act(atto: dict) -> dict:
    """Enrich a single act with classifier outputs."""
    titolo = atto["titolo"]
    serie = atto["serie"]
    content = atto.get("content_snippet", "")

    atto["ente"] = extract_ente(titolo, serie, content)
    atto["numero_atto"] = extract_numero(titolo)
    atto["topic"] = extract_topics(titolo, content)
    return atto


def main():
    data_dir = Path(__file__).parent.parent / "data"
    input_file = data_dir / "gu_acts.json"
    output_file = data_dir / "gu_acts_classified.json"

    if not input_file.exists():
        print(f"Errore: {input_file} non trovato. Esegui prima fetch_rss.py", file=sys.stderr)
        return 1

    data = json.loads(input_file.read_text())
    classified = [classify_act(a) for a in data]

    output_file.write_text(json.dumps(classified, indent=2, ensure_ascii=False))

    # Stats
    enti = Counter(a["ente"] for a in classified if a["ente"])
    topics = Counter(t for a in classified for t in a["topic"])

    print(f"Classificati {len(classified)} atti → {output_file.name}")
    print("\nTop 10 enti:")
    for e, n in enti.most_common(10):
        print(f"  {n:3d}  {e}")
    print("\nTopic distribution:")
    for t, n in topics.most_common():
        print(f"  {n:3d}  {t}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
