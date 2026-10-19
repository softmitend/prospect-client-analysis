# Prospect Client Analysis

A Google Maps / Google Places business intelligence pipeline for finding where website adoption is high or low across business categories, enriching public contact information, and exploring the results in a Streamlit dashboard.

## What this project does

The pipeline is deliberately split into data-engineering and ML stages:

1. **Extract** business records from Google Places API (New) using Text Search.
2. **Website enrichment** from the business' official website for public email, WhatsApp links/numbers, phone links, meta description, and basic contact/about pages.
3. **Preprocess** strings, URLs, phone numbers, opening hours, missing values, and deduplicate records.
4. **Transform / ETL** into a stable business schema with quality flags and derived digital-presence features.
5. **ML**:
   - TF-IDF + MiniBatchKMeans clustering to group semantically similar business records/categories.
   - Isolation Forest to flag unusual/incomplete records for quality review.
6. **Analytics**:
   - businesses per category,
   - businesses with/without websites,
   - website adoption percentage,
   - Wilson 95% confidence interval,
   - email/WhatsApp/phone coverage,
   - digital presence score.
7. **Dashboard** in Streamlit with category ranking, business-level tables, filters, data-quality views, and CSV/XLSX export.
8. **Google Colab notebook** for running and inspecting the same pipeline interactively.

> Important: the ranking is based on the businesses returned for the configured queries. Google Text Search is ranked and capped, so this is a **sample-based market analysis, not a census of every business in a city**.

## Why this is not "ML scraping"

Website-adoption ranking itself is an aggregation problem, not a machine-learning problem. ML is used only where it adds something useful: grouping messy business/category text and anomaly detection. The core collection, preprocessing, ETL, and percentage analysis remain deterministic and auditable.

## Data source

The default provider uses **Google Places API (New)** instead of scraping Google Maps HTML. This is more stable and gives structured fields such as:

- name
- primary category / types
- website
- national / international phone
- address
- location
- opening hours
- rating / review count
- business status
- Google Maps URL

Email and WhatsApp are **not direct Google Places fields**. When enrichment is enabled, the pipeline visits the official website (when one exists) and extracts public contact details from the homepage plus a small number of likely contact/about pages.

The code intentionally does not attempt CAPTCHA bypassing, account automation, or anti-bot evasion.

## Repository structure

```text
.
├── app.py
├── bin/
│   └── run_pipeline.py
├── data/
│   └── .gitkeep
├── notebooks/
│   └── prospect_client_analysis_colab.ipynb
├── src/
│   ├── __init__.py
│   ├── analysis.py
│   ├── enrichment.py
│   ├── etl.py
│   ├── export.py
│   ├── google_places.py
│   ├── ml.py
│   └── pipeline.py
├── .env.example
├── .gitignore
└── requirements.txt
```

## Quick start

### 1. Create a Google Maps Platform key

Enable **Places API (New)** in your Google Cloud project and create an API key. Restrict the key appropriately.

Copy `.env.example` to `.env`:

```bash
cp .env.example .env
```

Then set:

```env
GOOGLE_MAPS_API_KEY=your_key_here
```

### 2. Install

```bash
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

### 3. Run Streamlit

```bash
streamlit run app.py
```

### 4. CLI / bin usage

```bash
python bin/run_pipeline.py \
  --location "Banyuwangi, East Java, Indonesia" \
  --categories "restaurant,cafe,dentist,lawyer,beauty salon,car repair" \
  --max-results-per-category 40 \
  --enrich-websites \
  --output data/banyuwangi_businesses.xlsx
```

CSV output is also supported by changing the extension to `.csv`.

## Streamlit workflow

The dashboard supports two paths:

- **Collect live data** from Google Places.
- **Upload CSV/XLSX** from an earlier run and analyze it without calling the API again.

Recommended workflow:

1. Start with 8-20 categories and one city/area.
2. Use 20-40 results per category while validating the pipeline.
3. Turn on website enrichment only when you need email / WhatsApp / website descriptions because it creates additional requests to third-party websites.
4. Inspect the Data Quality tab.
5. Export the cleaned business table and category summary.

## Category ranking

The main summary includes:

| field | meaning |
|---|---|
| `category` | normalized business category |
| `total_businesses` | sample size |
| `businesses_with_website` | website present |
| `businesses_without_website` | website absent |
| `website_adoption_pct` | website share |
| `website_ci_low_pct` / `website_ci_high_pct` | Wilson 95% interval |
| `email_coverage_pct` | public email discovered |
| `whatsapp_coverage_pct` | WhatsApp discovered |
| `phone_coverage_pct` | phone available |
| `avg_rating` | mean rating |
| `median_review_count` | median review volume |

Use `min_category_size` in the dashboard to avoid ranking categories with tiny samples above categories with meaningful coverage.

## ETL schema

The transformed business table keeps core source fields and adds:

- `category`
- `website_present`
- `phone_present`
- `email_present`
- `whatsapp_present`
- `opening_hours_text`
- `website_domain`
- `public_email`
- `whatsapp_number`
- `website_meta_description`
- `business_description`
- `digital_presence_score`
- `ml_cluster`
- `ml_anomaly`
- `source_query`

## Notes on contact enrichment

The website enricher:

- uses a normal browser-like User-Agent,
- only follows the same host,
- only checks a small set of likely pages,
- has short timeouts,
- sleeps between requests,
- does not execute JavaScript,
- extracts only public contact data.

Some businesses expose WhatsApp or email only via JavaScript/social platforms, so those fields may remain empty even when the business uses them.

## Cost and sampling caveats

Google Places data fields are billed according to Google Maps Platform SKU rules. In particular, website, phone, rating, review count, and opening-hours fields may affect the SKU used. Keep the field mask constrained and start with small result limits.

Text Search (New) is not designed as a complete directory export. The API currently limits the number of results available across pages for a query. If you need stronger geographic coverage, split the study into explicit sub-areas or grid cells and deduplicate by Place ID.

## Google Colab

Open:

`notebooks/prospect_client_analysis_colab.ipynb`

The notebook installs dependencies, clones this repository, securely prompts for the API key, runs the same pipeline, shows category rankings, and exports CSV/XLSX files.

## Responsible use

Use public business data for legitimate research, market analysis, and prospecting. Do not use this project to harass businesses, bypass access controls, spam contacts, or evade platform restrictions.
