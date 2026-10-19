from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Iterable

import requests


TEXT_SEARCH_URL = "https://places.googleapis.com/v1/places:searchText"

DEFAULT_FIELD_MASK = ",".join(
    [
        "places.id",
        "places.displayName",
        "places.formattedAddress",
        "places.location",
        "places.primaryType",
        "places.primaryTypeDisplayName",
        "places.types",
        "places.websiteUri",
        "places.nationalPhoneNumber",
        "places.internationalPhoneNumber",
        "places.regularOpeningHours",
        "places.googleMapsUri",
        "places.rating",
        "places.userRatingCount",
        "places.businessStatus",
        "nextPageToken",
    ]
)


@dataclass
class GooglePlacesClient:
    api_key: str
    timeout: int = 30
    request_pause_seconds: float = 0.15

    def _headers(self) -> dict[str, str]:
        if not self.api_key:
            raise ValueError("Google Maps API key is required.")
        return {
            "Content-Type": "application/json",
            "X-Goog-Api-Key": self.api_key,
            "X-Goog-FieldMask": DEFAULT_FIELD_MASK,
        }

    def search_text(
        self,
        text_query: str,
        max_results: int = 40,
        language_code: str = "id",
        region_code: str = "ID",
    ) -> list[dict[str, Any]]:
        """Collect up to max_results from Google Places Text Search (New)."""
        max_results = max(1, min(int(max_results), 60))
        records: list[dict[str, Any]] = []
        page_token: str | None = None

        while len(records) < max_results:
            payload: dict[str, Any] = {
                "textQuery": text_query,
                "languageCode": language_code,
                "regionCode": region_code,
                "pageSize": min(20, max_results - len(records)),
            }
            if page_token:
                payload["pageToken"] = page_token

            response = requests.post(
                TEXT_SEARCH_URL,
                headers=self._headers(),
                json=payload,
                timeout=self.timeout,
            )
            if not response.ok:
                detail = response.text[:1000]
                raise RuntimeError(
                    f"Google Places request failed ({response.status_code}): {detail}"
                )

            body = response.json()
            records.extend(body.get("places", []))
            page_token = body.get("nextPageToken")
            if not page_token or len(records) >= max_results:
                break

            time.sleep(self.request_pause_seconds)

        return records[:max_results]

    def collect_categories(
        self,
        location: str,
        categories: Iterable[str],
        max_results_per_category: int = 40,
        language_code: str = "id",
        region_code: str = "ID",
    ) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for category in [c.strip() for c in categories if c and c.strip()]:
            query = f"{category} in {location}"
            places = self.search_text(
                query,
                max_results=max_results_per_category,
                language_code=language_code,
                region_code=region_code,
            )
            for place in places:
                item = dict(place)
                item["_source_query"] = query
                item["_requested_category"] = category
                rows.append(item)
            time.sleep(self.request_pause_seconds)
        return rows
