#!/usr/bin/env python3
"""Tests for GU Monitor scripts."""

import json
import sys
from pathlib import Path

import duckdb
import pytest

# Add scripts to path
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))


class TestFetchRss:
    """Test RSS feed parsing."""

    def test_parse_feed_returns_list(self):
        from fetch_rss import parse_feed

        xml = b"""<?xml version="1.0" encoding="UTF-8"?>
        <rss version="2.0" xmlns:content="http://purl.org/rss/1.0/modules/content/">
        <channel>
            <title>Test</title>
            <item>
                <title>LEGGE 1 agosto 2026, n. 100</title>
                <link>http://example.com/eli/id/2026/08/01/26G00100/SG</link>
                <content:encoded>Test content</content:encoded>
                <pubDate>Sat, 01 Aug 2026 10:00:00 GMT</pubDate>
            </item>
        </channel>
        </rss>"""

        result = parse_feed(xml, "SG")
        assert len(result) == 1
        assert result[0].id == "26G00100"
        assert result[0].serie == "SG"
        assert result[0].tipo_atto == "LEGGE"
        assert result[0].data_pubblicazione == "2026-08-01"

    def test_classify_tipo(self):
        from fetch_rss import classify_tipo

        assert classify_tipo("LEGGE 1 agosto 2026, n. 100") == "LEGGE"
        assert classify_tipo("DECRETO 1 agosto 2026") == "DECRETO"
        assert classify_tipo("COMUNICATO") == "COMUNICATO"
        assert classify_tipo("MINISTERO - DECRETO 1 agosto 2026") == "DECRETO"
        assert classify_tipo("Random text") == "ALTRO"

    def test_extract_ente(self):
        from fetch_rss import extract_ente

        assert extract_ente("MINISTERO DEL LAVORO - DECRETO 1 agosto") == "MINISTERO DEL LAVORO"
        assert extract_ente("AGENZIA ITALIANA DEL FARMACO - COMUNICATO") == "AGENZIA ITALIANA DEL FARMACO"
        assert extract_ente("REGOLAMENTO 17 giugno 2026") is None
        assert extract_ente("LEGGE 1 agosto 2026") is None


class TestClassify:
    """Test topic classification."""

    def test_extract_topics(self):
        from classify import extract_topics

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
                    "titolo", "tipo_atto", "ente", "link", "topic_str"}
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
        assert count > 4000  # At least 4000 acts from 30 days

    def test_parquet_date_range(self, parquet_path):
        con = duckdb.connect(":memory:")
        con.execute(f"CREATE TABLE atti AS SELECT * FROM read_parquet('{parquet_path}')")

        min_date = con.execute("SELECT MIN(data_pubblicazione) FROM atti").fetchone()[0]
        max_date = con.execute("SELECT MAX(data_pubblicazione) FROM atti").fetchone()[0]
        assert min_date is not None
        assert max_date is not None
        assert max_date >= min_date


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
