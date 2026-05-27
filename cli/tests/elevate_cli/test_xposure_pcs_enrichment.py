"""Unit tests for xposure-pcs buyer-brief enrichment.

Lock down the pure-function pieces (search summarizer, recency
formatter, tier bucketer, brief builder). The DB walk in
``run_enrichment`` is covered by integration runs against the live
PG; the synthesizer is what an operator's reading on every /leads
card, so any regression here is loudly visible.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from elevate_cli.xposure_pcs_enrichment import (
    _build_brief,
    _format_price,
    _format_recency,
    _summarize_searches,
    _tier_for,
)


class TestFormatPrice:
    def test_millions_clean(self) -> None:
        assert _format_price(1_000_000) == "$1M"
        assert _format_price(2_000_000) == "$2M"

    def test_millions_fractional(self) -> None:
        assert _format_price(1_200_000) == "$1.20M"
        assert _format_price(850_000) == "$850k"

    def test_thousands(self) -> None:
        assert _format_price(500_000) == "$500k"
        assert _format_price(250_000) == "$250k"

    def test_bad_input(self) -> None:
        assert _format_price(None) is None
        assert _format_price("not-a-number") is None


class TestSummarizeSearches:
    def test_structured_full(self) -> None:
        searches = [
            {
                "price_min": 800_000,
                "price_max": 1_200_000,
                "beds": 3,
                "area": "Aberdeen",
            },
            {"price_min": 700_000, "price_max": 1_100_000, "beds": 3, "area": "Westsyde"},
        ]
        result = _summarize_searches(searches)
        assert result["price_range"] == "$700k-$1.20M"
        assert result["beds"] == "3+ bed"
        assert result["areas"] == "Aberdeen + Westsyde"

    def test_camelcase_price_keys(self) -> None:
        result = _summarize_searches(
            [{"priceMin": 500_000, "priceMax": 800_000, "minBeds": 2}]
        )
        assert result["price_range"] == "$500k-$800k"
        assert result["beds"] == "2+ bed"

    def test_max_only(self) -> None:
        result = _summarize_searches([{"price_max": 600_000}])
        assert result["price_range"] == "up to $600k"

    def test_min_only(self) -> None:
        result = _summarize_searches([{"price_min": 400_000}])
        assert result["price_range"] == "from $400k"

    def test_dedup_areas(self) -> None:
        result = _summarize_searches(
            [
                {"area": "Aberdeen"},
                {"area": "Aberdeen"},
                {"area": "Westsyde"},
            ]
        )
        assert result["areas"] == "Aberdeen + Westsyde"

    def test_unstructured_labels_fallback(self) -> None:
        result = _summarize_searches(
            ["Kamloops 3-bed under 800k", "Westsyde investor"]
        )
        assert result["labels"] == "Kamloops 3-bed under 800k / Westsyde investor"
        assert "price_range" not in result
        assert "areas" not in result

    def test_filters_no_title_label(self) -> None:
        # Real scraper sometimes emits "no title" for unsaved searches —
        # noise, never useful, must be filtered.
        result = _summarize_searches(["no title", "no title"])
        assert result == {}

    def test_empty(self) -> None:
        assert _summarize_searches([]) == {}


class TestFormatRecency:
    def test_no_search(self) -> None:
        assert _format_recency(None) == "no recorded search"

    def test_today(self) -> None:
        now = datetime.now(timezone.utc)
        assert _format_recency(now) == "last search today"

    def test_one_day(self) -> None:
        ts = datetime.now(timezone.utc) - timedelta(days=1, hours=1)
        assert _format_recency(ts) == "last search 1d ago"

    def test_week_range(self) -> None:
        ts = datetime.now(timezone.utc) - timedelta(days=6)
        assert _format_recency(ts) == "last search 6d ago"

    def test_one_month_plus(self) -> None:
        ts = datetime.now(timezone.utc) - timedelta(days=45)
        # 45 // 7 = 6 weeks
        assert _format_recency(ts) == "last search 6w ago"

    def test_months(self) -> None:
        ts = datetime.now(timezone.utc) - timedelta(days=120)
        # 120 // 30 = 4 months
        assert _format_recency(ts) == "last search 4mo ago"


class TestTierFor:
    def _now(self) -> datetime:
        return datetime.now(timezone.utc)

    def test_active_requires_recent_and_volume(self) -> None:
        assert (
            _tier_for(
                last_search_at=self._now() - timedelta(days=5),
                search_count_90d=3,
            )
            == "active"
        )

    def test_warm_recent_low_volume(self) -> None:
        # Recent search but only 1 in 90d — still warm, not active.
        assert (
            _tier_for(
                last_search_at=self._now() - timedelta(days=5),
                search_count_90d=1,
            )
            == "warm"
        )

    def test_warm_inside_30d(self) -> None:
        assert (
            _tier_for(
                last_search_at=self._now() - timedelta(days=20),
                search_count_90d=5,
            )
            == "warm"
        )

    def test_dormant(self) -> None:
        assert (
            _tier_for(
                last_search_at=self._now() - timedelta(days=60),
                search_count_90d=10,
            )
            == "dormant"
        )

    def test_never_touched_old(self) -> None:
        assert (
            _tier_for(
                last_search_at=self._now() - timedelta(days=200),
                search_count_90d=0,
            )
            == "never-touched"
        )

    def test_never_touched_no_search(self) -> None:
        assert (
            _tier_for(last_search_at=None, search_count_90d=0) == "never-touched"
        )


class TestBuildBrief:
    def _now(self) -> datetime:
        return datetime.now(timezone.utc)

    def test_full_structured_brief(self) -> None:
        brief = _build_brief(
            searches=[
                {"price_min": 800_000, "price_max": 1_200_000, "beds": 3, "area": "Aberdeen"}
            ],
            last_search_at=self._now() - timedelta(days=6),
            search_count_90d=14,
            tier="HOT",
        )
        # Order matters — price → beds → area → recency → volume.
        assert brief.startswith("$800k-$1.20M, 3+ bed, Aberdeen, last search 6d ago")
        assert "14 searches in 90d" in brief

    def test_falls_back_when_no_structure(self) -> None:
        brief = _build_brief(
            searches=["no title"],
            last_search_at=self._now() - timedelta(days=2),
            search_count_90d=0,
            tier="HOT",
        )
        # No price/beds/area AND only filtered labels — falls back to
        # "MLS buyer (hot)" prefix.
        assert brief.startswith("MLS buyer (hot)")
        assert "last search 2d ago" in brief
        # search count 0 should not produce a "0 searches in 90d" tail.
        assert "searches in 90d" not in brief

    def test_no_tier_no_searches(self) -> None:
        brief = _build_brief(
            searches=[],
            last_search_at=None,
            search_count_90d=0,
            tier=None,
        )
        assert "MLS buyer" in brief
        assert "no recorded search" in brief

    def test_uses_label_when_no_structured_fields(self) -> None:
        brief = _build_brief(
            searches=["Kamloops 3-bed under 800k"],
            last_search_at=self._now() - timedelta(days=1),
            search_count_90d=2,
            tier="WARM",
        )
        assert "Kamloops 3-bed under 800k" in brief
        assert "2 searches in 90d" in brief
