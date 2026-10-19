from __future__ import annotations

import math

import numpy as np
import pandas as pd
from sklearn.cluster import MiniBatchKMeans
from sklearn.ensemble import IsolationForest
from sklearn.feature_extraction.text import TfidfVectorizer


def add_ml_features(df: pd.DataFrame, random_state: int = 42) -> pd.DataFrame:
    """Add unsupervised category/text clusters and record-level anomaly flags."""
    if df.empty:
        return df.copy()

    work = df.copy()
    corpus = (
        work.get("category", pd.Series("", index=work.index)).fillna("").astype(str)
        + " "
        + work.get("requested_category", pd.Series("", index=work.index)).fillna("").astype(str)
        + " "
        + work.get("types", pd.Series("", index=work.index)).fillna("").astype(str)
        + " "
        + work.get("business_name", pd.Series("", index=work.index)).fillna("").astype(str)
    )

    n_samples = len(work)
    if n_samples >= 4 and corpus.str.strip().nunique() >= 2:
        vectorizer = TfidfVectorizer(
            lowercase=True,
            ngram_range=(1, 2),
            min_df=1,
            max_features=1200,
        )
        matrix = vectorizer.fit_transform(corpus)
        n_clusters = min(10, max(2, int(round(math.sqrt(n_samples / 2)))))
        n_clusters = min(n_clusters, n_samples)
        clusterer = MiniBatchKMeans(
            n_clusters=n_clusters,
            random_state=random_state,
            n_init="auto",
            batch_size=min(256, max(16, n_samples)),
        )
        work["ml_cluster"] = clusterer.fit_predict(matrix)
    else:
        work["ml_cluster"] = 0

    def bool_series(name: str) -> pd.Series:
        return work[name].fillna(False).astype(bool).astype(int) if name in work else pd.Series(0, index=work.index)

    def numeric_series(name: str) -> pd.Series:
        source = work[name] if name in work else pd.Series(np.nan, index=work.index)
        return pd.to_numeric(source, errors="coerce").fillna(0)

    numeric = pd.DataFrame(
        {
            "website": bool_series("website_present"),
            "phone": bool_series("phone_present"),
            "email": bool_series("email_present"),
            "whatsapp": bool_series("whatsapp_present"),
            "hours": bool_series("hours_present"),
            "rating": numeric_series("rating"),
            "reviews_log": np.log1p(numeric_series("review_count")),
        }
    )
    if len(numeric) >= 12:
        model = IsolationForest(
            n_estimators=150,
            contamination="auto",
            random_state=random_state,
        )
        work["ml_anomaly"] = model.fit_predict(numeric) == -1
    else:
        work["ml_anomaly"] = False

    return work
