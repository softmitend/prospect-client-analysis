# Prospect Client Analysis

Business-intelligence pipeline for collecting public Google Maps business information, measuring website adoption by category, enriching public contact data, and exploring the results in Streamlit.

The default collector now uses **Playwright browser automation** and does **not require a Google Maps API key or billing account**. Google Places API (New) remains available as an optional structured provider.

## Pipeline

1. **Extract** business listings from the public Google Maps web UI with Playwright, or optionally from Places API (New).
2. **Preprocess** names, categories, URLs, phone numbers, addresses, opening hours, missing values, and duplicates.
3. **ETL** into a stable business-level schema.
4. **Website enrichment** for public email, WhatsApp links/numbers, website phone, and meta description.
5. **ML-assisted analysis**:
   - TF-IDF + MiniBatchKMeans for semantic grouping.
   - Isolation Forest for unusual/incomplete-record detection.
6. **Analytics**:
   - total businesses per category,
   - businesses with/without websites,
   - website adoption percentage,
   - Wilson 95% confidence interval,
   - email/WhatsApp/phone coverage,
   - digital presence score.
7. **Streamlit dashboard** with filters, ranked category tables, data-quality view, and CSV/XLSX export.
8. **Google Colab notebook** using the same pipeline.

Website-adoption ranking itself is deterministic analytics, not machine learning. ML is only used where it actually adds value.

## Data collected

The browser collector attempts to collect these public fields from Google Maps:

- business name
- business category
- website
- phone
- address
- opening-hours summary
- rating
- review count
- business status
- latitude / longitude when present in the Maps URL
- Google Maps URL

Email and WhatsApp usually are not displayed directly by Google Maps. When website enrichment is enabled, the pipeline visits the official business website and looks for public `mailto:`, `tel:`, `wa.me`, WhatsApp API links, metadata, and a small number of likely contact/about pages.

## Important browser-scraping limitation

Google Maps is a dynamic website. Browser scraping is inherently more fragile than the official API because selectors, visible labels, and page structure can change.

The scraper intentionally **does not** bypass CAPTCHA, unusual-traffic pages, authentication barriers, or anti-bot controls. If Google shows one of those pages, the run stops with an explanatory error.

Use conservative result counts while testing. Do not treat the returned search results as a complete census of every business in a region.

## Repository structure

```text
.
├── app.py
├── bin/
│   └── run_pipeline.py
├── notebooks/
│   └── prospect_client_analysis_colab.ipynb
├── src/
│   ├── analysis.py
│   ├── enrichment.py
│   ├── etl.py
│   ├── export.py
│   ├── google_maps_browser.py
│   ├── google_places.py
│   ├── ml.py
│   └── pipeline.py
├── .env.example
└── requirements.txt
```

## Windows quick start

From Git Bash / PowerShell inside the repository:

```bash
py -m venv .venv
```

Git Bash:

```bash
source .venv/Scripts/activate
```

PowerShell:

```powershell
.\.venv\Scripts\Activate.ps1
```

Install Python dependencies:

```bash
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

### Browser choice A: use installed Google Chrome

This is the easiest option on a normal Windows machine. The Streamlit dashboard defaults to the Playwright `chrome` channel, so no Google API key is needed.

### Browser choice B: Playwright Chromium

Install it once:

```bash
python -m playwright install chromium
```

Then choose **Playwright Chromium** in the dashboard.

## Run Streamlit

```bash
python -m streamlit run app.py
```

In the sidebar choose:

```text
Google Maps browser scraper (Playwright) — no API key
```

Then configure location, business categories, max results per category, and whether website enrichment should run.

## CLI / bin usage without API key

Using installed Google Chrome:

```bash
python bin/run_pipeline.py \
  --provider playwright \
  --browser-channel chrome \
  --location "Banyuwangi, East Java, Indonesia" \
  --categories "restaurant,cafe,dentist,lawyer,beauty salon,car repair" \
  --max-results-per-category 30 \
  --enrich-websites \
  --output data/banyuwangi_businesses.xlsx
```

To watch the browser while debugging, add:

```text
--headed
```

To use Playwright's bundled Chromium instead of installed Chrome:

```bash
python -m playwright install chromium
python bin/run_pipeline.py \
  --provider playwright \
  --browser-channel "" \
  --location "Banyuwangi, East Java, Indonesia" \
  --categories "restaurant,cafe,dentist"
```

## Optional Google Places API provider

The old structured API path is still available if you later obtain a billing-enabled key:

```bash
python bin/run_pipeline.py \
  --provider places_api \
  --api-key YOUR_KEY \
  --location "Banyuwangi, East Java, Indonesia" \
  --categories "restaurant,cafe,dentist"
```

You can also put it in `.env`:

```env
GOOGLE_MAPS_API_KEY=your_optional_key_here
```

The API key is **not required** for the default Playwright path.

## Streamlit dashboard

The dashboard supports:

- Playwright Google Maps browser collection without an API key
- optional Google Places API collection
- CSV/XLSX upload for previously collected data
- category ranking from highest to lowest website adoption
- website/no-website filtering
- business-level contact table
- ETL/ML quality view
- CSV export
- Excel workbook export with `businesses` and `category_summary` sheets

## Category summary fields

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

Use the minimum category sample-size filter before interpreting rankings. A category with two records and 100% website adoption is not stronger evidence than a category with dozens of records.

## Google Colab

Open:

```text
notebooks/prospect_client_analysis_colab.ipynb
```

The notebook installs dependencies and Playwright Chromium, runs the browser-based collector without a Google API key, reads the generated workbook back into pandas, displays the ranking and business table, and plots website adoption by category.

Colab runs headless in a cloud environment, so browser scraping there may encounter more blocking than running the dashboard locally.

## Responsible use

Use public business information for legitimate research, market analysis, and prospecting. Do not use this project to bypass access controls, evade CAPTCHA/anti-bot systems, harass businesses, or automate spam.
