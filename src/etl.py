from __future__ import annotations

import re
from urllib.parse import urlparse

import numpy as np
import pandas as pd


def _text(value) -> str | None:
    if value is None:
        return None
    if isinstance(value, dict):
        value = value.get("text")
    value = str(value).strip()
    return value or None


def _normalize_phone(value) -> str | None:
    if value is None or (isinstance(value, float) and np.isnan(value)):
        return None
    raw = str(value).strip()
    digits = re.sub(r"\D", "", raw)
    if not digits:
        return None
    if digits.startswith("0"):
        digits = "62" + digits[1:]
    if digits.startswith("62"):
        return "+" + digits
    return "+" + digits if raw.startswith("+") else digits


def _domain(url: str | None) -> str | None:
    if not url:
        return None
    try:
        host = urlparse(url if "://" in url else f"https://{url}").netloc.lower()
        return host.removeprefix("www.") or None
    except Exception:
        return None


def _opening_hours(place: dict) -> str | None:
    hours = place.get("regularOpeningHours") or {}
    descriptions = hours.get("weekdayDescriptions") or []
    return " | ".join(descriptions) if descriptions else None


def places_to_frame(raw_places: list[dict]) -> pd.DataFrame:
    rows = []
    for place in raw_places:
        display_name = _text(place.get("displayName"))
        primary_display = _text(place.get("primaryTypeDisplayName"))
        location = place.get("location") or {}
        website = _text(place.get("websiteUri"))
        types = place.get("types") or []
        requested_category = _text(place.get("_requested_category"))

        category = primary_display or _text(place.get("primaryType")) or requested_category or "Other"
        phone = _normalize_phone(
            place.get("nationalPhoneNumber") or place.get("internationalPhoneNumber")
        )

        rows.append(
            {
                "place_id": _text(place.get("id")),
                "business_name": display_name,
                "category": category,
                "primary_type": _text(place.get("primaryType")),
                "types": ", ".join(types),
                "requested_category": requested_category,
                "source_query": _text(place.get("_source_query")),
                "website": website,
                "website_domain": _domain(website),
                "phone": phone,
                "address": _text(place.get("formattedAddress")),
                "opening_hours_text": _opening_hours(place),
                "latitude": location.get("latitude"),
                "longitude": location.get("longitude"),
                "rating": place.get("rating"),
                "review_count": place.get("userRatingCount"),
                "business_status": _text(place.get("businessStatus")),
                "google_maps_url": _text(place.get("googleMapsUri")),
            }
        )
    return pd.DataFrame(rows)


def preprocess_businesses(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df.copy()

    work = df.copy()

    for col in [
        "business_name",
        "category",
        "primary_type",
        "requested_category",
        "website",
        "website_domain",
        "phone",
        "address",
        "opening_hours_text",
    ]:
        if col in work:
            work[col] = (
                work[col]
                .astype("string")
                .str.replace(r"\s+", " ", regex=True)
                .str.strip()
                .replace({"": pd.NA, "<NA>": pd.NA, "nan": pd.NA})
            )

    work["category"] = work["category"].fillna(work.get("requested_category")).fillna("Other")
    work["website_present"] = work.get("website").notna()
    work["phone_present"] = work.get("phone").notna()
    work["hours_present"] = work.get("opening_hours_text").notna()

    if "place_id" in work and work["place_id"].notna().any():
        with_id = work[work["place_id"].notna()].drop_duplicates("place_id", keep="first")
        without_id = work[work["place_id"].isna()].copy()
        fallback_keys = [c for c in ["business_name", "address"] if c in without_id]
        if fallback_keys:
            without_id = without_id.drop_duplicates(fallback_keys, keep="first")
        work = pd.concat([with_id, without_id], ignore_index=True)
    else:
        fallback_keys = [c for c in ["business_name", "address"] if c in work]
        if fallback_keys:
            work = work.drop_duplicates(fallback_keys, keep="first").reset_index(drop=True)

    return work.reset_index(drop=True)


def merge_enrichment(df: pd.DataFrame, enrichment_rows: list[dict]) -> pd.DataFrame:
    if df.empty:
        return df.copy()

    work = df.copy()
    enrichment = pd.DataFrame(enrichment_rows)
    if enrichment.empty:
        for col in [
            "public_email",
            "whatsapp_number",
            "website_phone",
            "website_meta_description",
        ]:
            work[col] = pd.NA
    else:
        enrichment = enrichment.set_index("_row_id").rename(
            columns={"website_domain": "enriched_website_domain"}
        )
        work = work.join(enrichment, how="left")

    if "enriched_website_domain" in work.columns:
        work["website_domain"] = work["enriched_website_domain"].combine_first(
            work["website_domain"]
        )
        work = work.drop(columns=["enriched_website_domain"])

    work["public_email"] = work.get("public_email", pd.Series(index=work.index, dtype="string"))
    work["whatsapp_number"] = work.get("whatsapp_number", pd.Series(index=work.index, dtype="string"))
    work["website_phone"] = work.get("website_phone", pd.Series(index=work.index, dtype="string"))
    work["website_meta_description"] = work.get(
        "website_meta_description", pd.Series(index=work.index, dtype="string")
    )

    work["email_present"] = work["public_email"].notna()
    work["whatsapp_present"] = work["whatsapp_number"].notna()

    website_phone = work["website_phone"].astype("string")
    work["phone"] = work["phone"].astype("string").combine_first(website_phone)
    work["phone_present"] = work["phone"].notna()

    fallback_description = (
        work["business_name"].fillna("Business")
        + " · "
        + work["category"].fillna("Other")
        + work["address"].fillna("").map(lambda x: f" · {x}" if x else "")
    )
    work["business_description"] = (
        work["website_meta_description"].astype("string").combine_first(fallback_description)
    )

    work["digital_presence_score"] = (
        work["website_present"].astype(int) * 40
        + work["phone_present"].astype(int) * 20
        + work["email_present"].astype(int) * 15
        + work["whatsapp_present"].astype(int) * 15
        + work["hours_present"].astype(int) * 10
    )

    return work
