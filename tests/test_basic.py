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
