import unittest
from datetime import datetime, timezone
from urllib.parse import parse_qs, urlsplit

from trading_pro.integrations import fetch_newsapi, normalize_newsapi
from trading_pro.news import normalize_event
from trading_pro.relevance import classify, select


def event(headline, source="Wire", relevance=None):
    at = datetime(2026, 11, 18, 10, tzinfo=timezone.utc)
    label, topics = classify(headline)
    return normalize_event(source=source, url=f"https://example.org/{abs(hash(headline))}", headline=headline,
                           published_at=at, received_at=at, relevance=relevance or label, topics=topics)


class RelevanceTests(unittest.TestCase):
    def test_gold_market_headlines_are_high(self):
        for headline in ("Gold price hits record high as dollar slips", "XAUUSD slips below support",
                         "Spot gold edges higher ahead of CPI", "Central banks keep buying gold in October",
                         "Gold futures settle lower on COMEX"):
            self.assertEqual(classify(headline)[0], "high", headline)

    def test_macro_drivers_are_medium_but_other_senses_of_gold_are_not_market(self):
        self.assertEqual(classify("Fed signals rate cuts as inflation cools")[0], "medium")
        self.assertEqual(classify("Team wins gold medal at the Olympics")[0], "none")
        self.assertEqual(classify("Gold Coast hosts the festival")[0], "none")
        self.assertEqual(classify("She stuns in a gold beaded lehenga")[0], "low")
        self.assertEqual(classify("Heavy rain expected across the coast")[0], "none")

    def test_local_retail_rate_pages_are_only_medium(self):
        for headline in ("Gold price drops by Rs 1,900 per tola in domestic market",
                         "Gold price today Delhi: 22 carat 10 gram in rupees"):
            level, topics = classify(headline)
            self.assertEqual(level, "medium", headline)
            self.assertIn("retail_local", topics)
        self.assertEqual(classify("Gold price slides to one-year low as Fed signals cuts")[0], "high")

    def test_select_applies_floor_and_per_source_cap_and_reports_counts(self):
        events = [event("Gold price rises", "A"), event("Gold price falls", "A"), event("Gold price steadies", "A"),
                  event("Fed holds rates", "B"), event("Gold gala dress", "B"), event("Weather report", "C")]
        kept, report = select(events, minimum="medium", max_per_source=2)
        self.assertEqual([e.headline for e in kept], ["Gold price rises", "Gold price falls", "Fed holds rates"])
        self.assertEqual(report["dropped_by_source_cap"], 1)
        self.assertEqual(report["dropped_below_relevance"], 2)
        self.assertEqual(report["received"], 6)
        with self.assertRaises(ValueError):
            select(events, minimum="none")
        with self.assertRaises(ValueError):
            select(events, max_per_source=0)

    def test_newsapi_events_carry_a_label_but_stay_unconfirmed_and_asset_free(self):
        article = {"source": {"name": "Wire"}, "title": "Gold price rallies", "url": "https://example.org/a",
                   "publishedAt": "2026-11-18T09:00:00Z"}
        (parsed,) = normalize_newsapi({"status": "ok", "articles": [article]},
                                      received_at=datetime(2026, 11, 18, 10, tzinfo=timezone.utc))
        self.assertEqual(parsed.relevance, "high")
        self.assertEqual((parsed.status, parsed.severity, parsed.assets), ("unconfirmed", "low", ()))
        self.assertFalse(parsed.pauses_entries)

    def test_newsapi_request_searches_titles_only(self):
        seen = {}

        class Response:
            status = 200
            def __enter__(self): return self
            def __exit__(self, *args): return False
            def read(self, size): return b'{"status":"ok","articles":[]}'

        def transport(request, timeout):
            seen["query"] = parse_qs(urlsplit(request.full_url).query)
            return Response()
        fetch_newsapi(query="gold price", api_key="secret", opener=transport)
        self.assertEqual(seen["query"]["searchIn"], ["title"])


if __name__ == "__main__":
    unittest.main()
