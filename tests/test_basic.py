#!/usr/bin/env python3
"""Tests for GU Monitor scripts."""

import sys
from pathlib import Path

import duckdb
import pytest

# Add scripts to path
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))


class TestExtractTopics:
    """Test topic classification (now in to_parquet.py)."""

    def test_extract_topics(self):
        from to_parquet import extract_topics

        assert "sanita" in extract_topics("Classificazione medicinale Comirnaty", "")
        assert "lavoro" in extract_topics("Concorso pubblico per assistente", "")
        assert "europa" in extract_topics("Regolamento (UE) 2026/1395", "")
        assert "fisco" in extract_topics("Imposta sul redditi", "")
        assert len(extract_topics("Test generico", "")) == 0


class TestParquet:
    """Test parquet dataset."""

    @pytest.fixture
    def parquet_path(self):
        path = Path(__file__).parent.parent / "data" / "gu_acts.parquet"
        if not path.exists():
            pytest.skip("Parquet file not found")
        return path

    def test_parquet_exists(self, parquet_path):
        assert parquet_path.exists()

    def test_parquet_schema(self, parquet_path):
        con = duckdb.connect(":memory:")
        con.execute(f"CREATE TABLE atti AS SELECT * FROM read_parquet('{parquet_path}')")

        columns = {row[0] for row in con.execute("DESCRIBE atti").fetchall()}
        expected = {"id", "serie", "gazzetta_numero", "data_pubblicazione",
                    "titolo", "tipo_atto", "ente", "link", "topic_str",
                    "urn_normattiva", "link_normattiva"}
        assert expected.issubset(columns)

    def test_parquet_has_all_series(self, parquet_path):
        con = duckdb.connect(":memory:")
        con.execute(f"CREATE TABLE atti AS SELECT * FROM read_parquet('{parquet_path}')")

        series = {row[0] for row in con.execute("SELECT DISTINCT serie FROM atti").fetchall()}
        assert series == {"SG", "S1", "S2", "S3", "S4", "S5", "P2"}

    def test_parquet_row_count(self, parquet_path):
        con = duckdb.connect(":memory:")
        con.execute(f"CREATE TABLE atti AS SELECT * FROM read_parquet('{parquet_path}')")

        count = con.execute("SELECT COUNT(*) FROM atti").fetchone()[0]
        assert count >= 1500  # At least 1500 unique acts from 30 days (after dedup on id+link)

    def test_parquet_date_range(self, parquet_path):
        con = duckdb.connect(":memory:")
        con.execute(f"CREATE TABLE atti AS SELECT * FROM read_parquet('{parquet_path}')")

        min_date = con.execute("SELECT MIN(data_pubblicazione) FROM atti").fetchone()[0]
        max_date = con.execute("SELECT MAX(data_pubblicazione) FROM atti").fetchone()[0]
        assert min_date is not None
        assert max_date is not None
        assert max_date >= min_date

    def test_parquet_urn_normattiva(self, parquet_path):
        con = duckdb.connect(":memory:")
        con.execute(f"CREATE TABLE atti AS SELECT * FROM read_parquet('{parquet_path}')")

        # All rows should have urn_normattiva column (possibly empty)
        cols = {row[0] for row in con.execute("DESCRIBE atti").fetchall()}
        assert "urn_normattiva" in cols
        assert "link_normattiva" in cols

        # Some rows should have non-empty URN (from gu_links.json crossref)
        non_empty = con.execute(
            "SELECT COUNT(*) FROM atti WHERE urn_normattiva IS NOT NULL AND urn_normattiva != ''"
        ).fetchone()[0]
        assert non_empty > 0


class TestAnalytics:
    """Test analytics script runs without errors."""

    def test_analytics_runs(self, capsys):
        from analytics import main

        # Mock sys.argv
        old_argv = sys.argv
        sys.argv = ["analytics.py"]
        try:
            result = main()
            assert result == 0
        finally:
            sys.argv = old_argv


class TestAlertHighImpact:
    """Test alert_high_impact script logic."""

    @pytest.fixture
    def parquet_path(self):
        path = Path(__file__).parent.parent / "data" / "gu_acts.parquet"
        if not path.exists():
            pytest.skip("Parquet file not found")
        return path

    def test_alert_query_structure(self):
        """Verify query filters only LEGGE/DECRETO-LEGGE."""
        from alert_high_impact import QUERY
        
        # Query must filter by tipo_atto
        assert "tipo_atto IN ('LEGGE', 'DECRETO-LEGGE')" in QUERY
        # Must exclude regional
        assert "NOT LIKE '%REGIONE%'" in QUERY
        # Must use CURRENT_DATE for 24h window
        assert "CURRENT_DATE" in QUERY

    def test_alert_runs_with_real_data(self, parquet_path):
        """Script runs without errors on real data."""
        from alert_high_impact import main
        
        old_argv = sys.argv
        sys.argv = ["alert_high_impact.py"]
        try:
            # Should return 0 even if no results today
            result = main()
            assert result == 0
        finally:
            sys.argv = old_argv

    def test_alert_scoring_logic(self):
        """Verify scoring weights in query."""
        from alert_high_impact import QUERY
        
        # DECRETO-LEGGE should score higher than LEGGE
        assert "WHEN tipo_atto = 'DECRETO-LEGGE' THEN 10" in QUERY
        assert "WHEN tipo_atto = 'LEGGE' THEN 9" in QUERY
        # PCM should have highest ente score
        assert "%PRESIDENZA DEL CONSIGLIO%' THEN 4" in QUERY

    def test_alert_excludes_regional(self, parquet_path):
        """Query excludes regional legislation."""
        import duckdb
        from alert_high_impact import QUERY
        
        con = duckdb.connect(":memory:")
        query = QUERY.format(
            parquet=str(parquet_path.resolve()),
            threshold=9
        )
        results = con.execute(query).fetchall()
        con.close()
        
        # No regional acts should appear
        for row in results:
            ente = row[4] or ""
            titolo = row[5] or ""
            assert "REGIONE" not in ente.upper()
            assert "PROVINCIA" not in ente.upper()
            assert "REGIONALE" not in titolo.upper()

    def test_alert_only_high_impact_types(self, parquet_path):
        """Only LEGGE and DECRETO-LEGGE should appear."""
        import duckdb
        from alert_high_impact import QUERY
        
        con = duckdb.connect(":memory:")
        query = QUERY.format(
            parquet=str(parquet_path.resolve()),
            threshold=9
        )
        results = con.execute(query).fetchall()
        con.close()
        
        for row in results:
            tipo = row[3]
            assert tipo in ("LEGGE", "DECRETO-LEGGE")
