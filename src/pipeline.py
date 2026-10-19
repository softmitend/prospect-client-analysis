from __future__ import annotations

from collections.abc import Callable

import pandas as pd

from .analysis import summarize_categories
from .enrichment import WebsiteEnricher
from .etl import merge_enrichment, places_to_frame, preprocess_businesses
from .google_maps_browser import GoogleMapsPlaywrightScraper
from .google_places import GooglePlacesClient
from .ml import add_ml_features


ProgressCallback = Callable[[str, int, int], None]


def _noop_progress(stage: str, current: int, total: int) -> None:
    return None


def run_pipeline(
    *,
    location: str,
    categories: list[str],
    provider: str = "playwright",
    api_key: str | None = None,
    max_results_per_category: int = 40,
    enrich_websites: bool = True,
    min_category_size: int = 1,
    language_code: str = "id",
    region_code: str = "ID",
    browser_headless: bool = True,
    browser_channel: str | None = None,
    progress_callback: ProgressCallback | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Run collection, preprocessing, enrichment, ML and category analytics.

    provider="playwright" is the no-API-key default and automates the public
    Google Maps web UI. provider="places_api" keeps the structured Google
    Places API path available when a billing-enabled API key exists.
    """
    progress = progress_callback or _noop_progress
    normalized_provider = provider.strip().lower()

    if normalized_provider in {"playwright", "browser", "google_maps_browser"}:
        client = GoogleMapsPlaywrightScraper(
            headless=browser_headless,
            browser_channel=browser_channel or None,
        )
        collection_stage = "google_maps_browser"
    elif normalized_provider in {"places_api", "google_places", "api"}:
        if not api_key:
            raise ValueError("Google Maps API key is required when provider='places_api'.")
        client = GooglePlacesClient(api_key=api_key)
        collection_stage = "google_places"
    else:
        raise ValueError("Unknown provider. Use 'playwright' or 'places_api'.")

    progress(collection_stage, 0, len(categories))
    raw = client.collect_categories(
        location=location,
        categories=categories,
        max_results_per_category=max_results_per_category,
        language_code=language_code,
        region_code=region_code,
    )
    progress(collection_stage, len(categories), len(categories))

    if not raw:
        hint = (
            " No businesses were collected. If you are using Playwright, try turning "
            "off headless mode to inspect the page, reduce the number of categories, "
            "and confirm that Google Maps search results are loading normally."
        )
        raise RuntimeError(hint.strip())

    businesses = preprocess_businesses(places_to_frame(raw))

    enrichment_rows: list[dict] = []
    if enrich_websites and not businesses.empty:
        enricher = WebsiteEnricher()
        total = int(businesses["website_present"].sum())
        completed = 0
        progress("website_enrichment", completed, total)
        for idx, row in businesses.iterrows():
            if not row.get("website_present", False):
                continue
            enriched = enricher.enrich(row.get("website"))
            enriched["_row_id"] = idx
            enrichment_rows.append(enriched)
            completed += 1
            progress("website_enrichment", completed, total)

    businesses = merge_enrichment(businesses, enrichment_rows)
    businesses = add_ml_features(businesses)

    category_summary = summarize_categories(
        businesses,
        min_category_size=min_category_size,
    )
    return businesses, category_summary


def analyze_existing_dataframe(
    df: pd.DataFrame,
    min_category_size: int = 1,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Normalize a previously exported business table and recompute analytics."""
    work = df.copy()
    required = {
        "category": "Other",
        "website": pd.NA,
        "phone": pd.NA,
        "public_email": pd.NA,
        "whatsapp_number": pd.NA,
        "opening_hours_text": pd.NA,
    }
    for col, default in required.items():
        if col not in work:
            work[col] = default

    work["website_present"] = work["website"].notna()
    work["phone_present"] = work["phone"].notna()
    work["email_present"] = work["public_email"].notna()
    work["whatsapp_present"] = work["whatsapp_number"].notna()
    work["hours_present"] = work["opening_hours_text"].notna()

    if "digital_presence_score" not in work:
        work["digital_presence_score"] = (
            work["website_present"].astype(int) * 40
            + work["phone_present"].astype(int) * 20
            + work["email_present"].astype(int) * 15
            + work["whatsapp_present"].astype(int) * 15
            + work["hours_present"].astype(int) * 10
        )

    if "ml_cluster" not in work or "ml_anomaly" not in work:
        work = add_ml_features(work)

    return work, summarize_categories(work, min_category_size=min_category_size)
