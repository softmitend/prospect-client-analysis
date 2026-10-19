from __future__ import annotations

from io import BytesIO

import pandas as pd


def to_csv_bytes(df: pd.DataFrame) -> bytes:
    return df.to_csv(index=False).encode("utf-8-sig")


def to_excel_bytes(
    businesses: pd.DataFrame,
    category_summary: pd.DataFrame,
) -> bytes:
    buffer = BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        businesses.to_excel(writer, index=False, sheet_name="businesses")
        category_summary.to_excel(writer, index=False, sheet_name="category_summary")
    buffer.seek(0)
    return buffer.getvalue()
