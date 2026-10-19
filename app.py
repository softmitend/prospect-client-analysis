from __future__ import annotations

import os

import pandas as pd
import streamlit as st
from dotenv import load_dotenv

from src.export import to_csv_bytes, to_excel_bytes
from src.pipeline import analyze_existing_dataframe, run_pipeline


load_dotenv()

DEFAULT_CATEGORIES = [
    "restaurant",
    "cafe",
    "hotel",
    "dentist",
    "clinic",
    "beauty salon",
    "barbershop",
    "lawyer",
    "accounting firm",
    "real estate agency",
    "car repair",
    "car wash",
    "motorcycle repair",
    "pet shop",
    "veterinary clinic",
    "gym",
    "photographer",
    "wedding organizer",
    "printing service",
    "computer repair",
    "furniture store",
    "bakery",
]


st.set_page_config(
    page_title="Prospect Client Analysis",
    page_icon="📍",
    layout="wide",
)

st.title("📍 Prospect Client Analysis")
st.caption(
    "Google Maps → preprocessing → ETL → ML-assisted grouping/quality checks → "
    "website-adoption analysis → CSV/XLSX."
)

with st.sidebar:
    st.header("Collection")
    provider_label = st.selectbox(
        "Data source",
        [
            "Google Maps browser scraper (Playwright) — no API key",
            "Google Places API (optional)",
        ],
    )
    provider = "playwright" if provider_label.startswith("Google Maps browser") else "places_api"

    api_key = ""
    browser_headless = True
    browser_channel = None

    if provider == "places_api":
        api_key = st.text_input(
            "Google Maps API key",
            value=os.getenv("GOOGLE_MAPS_API_KEY", ""),
            type="password",
            help="Places API (New) must be enabled and billing must be configured.",
        )
    else:
        st.info(
            "No Google API key is needed. This automates the public Google Maps UI, "
            "so collection is slower and can break when the UI changes."
        )
        browser_headless = st.toggle(
            "Run browser headless",
            value=True,
            help="Turn this off while debugging to watch the browser work.",
        )
        browser_choice = st.selectbox(
            "Browser",
            ["Google Chrome", "Playwright Chromium"],
            help=(
                "Google Chrome is convenient on Windows. Playwright Chromium requires "
                "`python -m playwright install chromium` once."
            ),
        )
        browser_channel = "chrome" if browser_choice == "Google Chrome" else None

    location = st.text_input(
        "Location",
        value="Banyuwangi, East Java, Indonesia",
    )
    category_text = st.text_area(
        "Business categories",
        value="\n".join(DEFAULT_CATEGORIES),
        height=260,
        help="One category per line.",
    )
    max_limit = 100 if provider == "playwright" else 60
    max_results = st.slider(
        "Max results / category",
        min_value=5,
        max_value=max_limit,
        value=30,
        step=5,
    )
    min_category_size = st.number_input(
        "Minimum sample size / category",
        min_value=1,
        max_value=100,
        value=5,
    )
    enrich_websites = st.toggle(
        "Enrich email / WhatsApp from websites",
        value=True,
        help="Adds public website requests and will be slower.",
    )

    run_live = st.button("Run live collection", type="primary", use_container_width=True)

    st.divider()
    st.header("Analyze saved data")
    upload = st.file_uploader("Upload CSV/XLSX", type=["csv", "xlsx"])

if "businesses" not in st.session_state:
    st.session_state.businesses = None
if "summary" not in st.session_state:
    st.session_state.summary = None

if run_live:
    categories = [line.strip() for line in category_text.splitlines() if line.strip()]
    if provider == "places_api" and not api_key:
        st.error("Google Maps API key is required only for the Places API provider.")
    elif not categories:
        st.error("Add at least one business category.")
    else:
        progress_bar = st.progress(0)
        status = st.empty()

        def progress(stage: str, current: int, total: int) -> None:
            if total <= 0:
                return
            fraction = min(1.0, current / total)
            if stage in {"google_places", "google_maps_browser"}:
                source_name = "Google Maps browser" if stage == "google_maps_browser" else "Google Places"
                status.write(f"Collecting {source_name} data…")
                progress_bar.progress(min(0.45, fraction * 0.45))
            else:
                status.write(f"Enriching websites… {current}/{total}")
                progress_bar.progress(0.45 + fraction * 0.55)

        try:
            businesses, summary = run_pipeline(
                provider=provider,
                api_key=api_key or None,
                location=location,
                categories=categories,
                max_results_per_category=max_results,
                enrich_websites=enrich_websites,
                min_category_size=int(min_category_size),
                browser_headless=browser_headless,
                browser_channel=browser_channel,
                progress_callback=progress,
            )
            st.session_state.businesses = businesses
            st.session_state.summary = summary
            progress_bar.progress(1.0)
            status.success(f"Done. {len(businesses):,} unique businesses processed.")
        except Exception as exc:
            st.exception(exc)

if upload is not None:
    try:
        if upload.name.lower().endswith(".csv"):
            uploaded_df = pd.read_csv(upload)
        else:
            uploaded_df = pd.read_excel(upload)
        businesses, summary = analyze_existing_dataframe(
            uploaded_df,
            min_category_size=int(min_category_size),
        )
        st.session_state.businesses = businesses
        st.session_state.summary = summary
        st.success(f"Loaded {len(businesses):,} rows from {upload.name}.")
    except Exception as exc:
        st.exception(exc)

businesses = st.session_state.businesses
summary = st.session_state.summary

if businesses is None or summary is None:
    st.info(
        "Run a live collection from the sidebar, or upload a previously exported CSV/XLSX."
    )
    st.stop()

website_rate = float(businesses["website_present"].mean() * 100) if len(businesses) else 0.0
email_rate = float(businesses["email_present"].mean() * 100) if len(businesses) else 0.0
wa_rate = float(businesses["whatsapp_present"].mean() * 100) if len(businesses) else 0.0

m1, m2, m3, m4 = st.columns(4)
m1.metric("Businesses", f"{len(businesses):,}")
m2.metric("Website adoption", f"{website_rate:.1f}%")
m3.metric("Email discovered", f"{email_rate:.1f}%")
m4.metric("WhatsApp discovered", f"{wa_rate:.1f}%")

tab1, tab2, tab3 = st.tabs(
    ["Website adoption by category", "Business table", "ETL / ML quality"]
)

with tab1:
    st.subheader("Categories ranked from highest to lowest website adoption")
    if summary.empty:
        st.warning("No category meets the current minimum sample size.")
    else:
        chart = summary.set_index("category")[["website_adoption_pct"]]
        st.bar_chart(chart, horizontal=True, height=max(400, len(chart) * 28))
        st.dataframe(
            summary,
            use_container_width=True,
            hide_index=True,
            column_config={
                "website_adoption_pct": st.column_config.ProgressColumn(
                    "Website %",
                    min_value=0,
                    max_value=100,
                    format="%.1f%%",
                ),
                "email_coverage_pct": st.column_config.NumberColumn("Email %", format="%.1f"),
                "whatsapp_coverage_pct": st.column_config.NumberColumn("WhatsApp %", format="%.1f"),
                "phone_coverage_pct": st.column_config.NumberColumn("Phone %", format="%.1f"),
            },
        )

with tab2:
    categories_available = sorted(
        x for x in businesses["category"].dropna().astype(str).unique()
    )
    selected = st.multiselect(
        "Filter category",
        categories_available,
        default=[],
    )
    website_filter = st.selectbox(
        "Website filter",
        ["All", "Has website", "No website"],
    )

    filtered = businesses.copy()
    if selected:
        filtered = filtered[filtered["category"].isin(selected)]
    if website_filter == "Has website":
        filtered = filtered[filtered["website_present"]]
    elif website_filter == "No website":
        filtered = filtered[~filtered["website_present"]]

    visible_columns = [
        c
        for c in [
            "business_name",
            "category",
            "business_description",
            "website",
            "public_email",
            "whatsapp_number",
            "phone",
            "address",
            "opening_hours_text",
            "rating",
            "review_count",
            "google_maps_url",
            "digital_presence_score",
            "ml_cluster",
        ]
        if c in filtered
    ]
    st.dataframe(
        filtered[visible_columns],
        use_container_width=True,
        hide_index=True,
        height=600,
    )

with tab3:
    q1, q2, q3 = st.columns(3)
    q1.metric("Duplicate-free rows", f"{len(businesses):,}")
    q2.metric(
        "ML anomalies",
        f"{int(businesses.get('ml_anomaly', pd.Series(False, index=businesses.index)).sum()):,}",
    )
    q3.metric(
        "Missing websites",
        f"{int((~businesses['website_present']).sum()):,}",
    )

    quality_columns = [
        c
        for c in [
            "business_name",
            "category",
            "website_present",
            "phone_present",
            "email_present",
            "whatsapp_present",
            "hours_present",
            "digital_presence_score",
            "ml_cluster",
            "ml_anomaly",
            "source_query",
        ]
        if c in businesses
    ]
    st.dataframe(
        businesses[quality_columns],
        use_container_width=True,
        hide_index=True,
        height=520,
    )

st.divider()
st.subheader("Export")
c1, c2, c3 = st.columns(3)
c1.download_button(
    "Download businesses CSV",
    data=to_csv_bytes(businesses),
    file_name="businesses_clean.csv",
    mime="text/csv",
    use_container_width=True,
)
c2.download_button(
    "Download category summary CSV",
    data=to_csv_bytes(summary),
    file_name="category_website_adoption.csv",
    mime="text/csv",
    use_container_width=True,
)
c3.download_button(
    "Download Excel workbook",
    data=to_excel_bytes(businesses, summary),
    file_name="prospect_client_analysis.xlsx",
    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    use_container_width=True,
)

st.caption(
    "Browser-scraped Google Maps results are a ranked sample, not a complete business census. "
    "Selectors and visible fields may change when Google Maps changes its UI."
)
