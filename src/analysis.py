from __future__ import annotations

import math

import numpy as np
import pandas as pd


def _wilson_interval(successes: int, total: int, z: float = 1.96) -> tuple[float, float]:
    if total <= 0:
        return (0.0, 0.0)
    p = successes / total
    denominator = 1 + (z**2 / total)
    centre = p + (z**2 / (2 * total))
    margin = z * math.sqrt((p * (1 - p) / total) + (z**2 / (4 * total**2)))
    low = (centre - margin) / denominator
    high = (centre + margin) / denominator
    return max(0.0, low), min(1.0, high)


def summarize_categories(df: pd.DataFrame, min_category_size: int = 1) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame(
            columns=[
                "category",
                "total_businesses",
                "businesses_with_website",
                "businesses_without_website",
                "website_adoption_pct",
            ]
        )

    work = df.copy()
    for col in ["website_present", "email_present", "whatsapp_present", "phone_present"]:
        if col not in work:
            work[col] = False
        work[col] = work[col].fillna(False).astype(bool)

    grouped = work.groupby("category", dropna=False)

    rows = []
    for category, group in grouped:
        total = len(group)
        if total < max(1, int(min_category_size)):
            continue
        with_website = int(group["website_present"].sum())
        low, high = _wilson_interval(with_website, total)

        rating_series = (
            pd.to_numeric(group["rating"], errors="coerce")
            if "rating" in group
            else pd.Series(np.nan, index=group.index)
        )
        review_series = (
            pd.to_numeric(group["review_count"], errors="coerce")
            if "review_count" in group
            else pd.Series(np.nan, index=group.index)
        )
        score_series = (
            pd.to_numeric(group["digital_presence_score"], errors="coerce")
            if "digital_presence_score" in group
            else pd.Series(np.nan, index=group.index)
        )

        rows.append(
            {
                "category": category or "Other",
                "total_businesses": total,
                "businesses_with_website": with_website,
                "businesses_without_website": total - with_website,
                "website_adoption_pct": round(with_website / total * 100, 2),
                "website_ci_low_pct": round(low * 100, 2),
                "website_ci_high_pct": round(high * 100, 2),
                "email_coverage_pct": round(group["email_present"].mean() * 100, 2),
                "whatsapp_coverage_pct": round(group["whatsapp_present"].mean() * 100, 2),
                "phone_coverage_pct": round(group["phone_present"].mean() * 100, 2),
                "avg_rating": round(rating_series.mean(), 2),
                "median_review_count": float(review_series.median())
                if review_series.notna().any()
                else np.nan,
                "avg_digital_presence_score": round(score_series.mean(), 2),
            }
        )

    result = pd.DataFrame(rows)
    if result.empty:
        return result

    return result.sort_values(
        ["website_adoption_pct", "total_businesses"],
        ascending=[False, False],
        ignore_index=True,
    )
