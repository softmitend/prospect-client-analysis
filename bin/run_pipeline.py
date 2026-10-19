from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.export import to_excel_bytes
from src.pipeline import run_pipeline


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run prospect client analysis pipeline.")
    parser.add_argument("--location", required=True)
    parser.add_argument(
        "--categories",
        required=True,
        help="Comma-separated business categories.",
    )
    parser.add_argument(
        "--provider",
        choices=["playwright", "places_api"],
        default="playwright",
        help="Default is Playwright browser scraping and needs no API key.",
    )
    parser.add_argument("--api-key", default=None)
    parser.add_argument("--max-results-per-category", type=int, default=30)
    parser.add_argument("--min-category-size", type=int, default=1)
    parser.add_argument("--enrich-websites", action="store_true")
    parser.add_argument(
        "--headed",
        action="store_true",
        help="Show the browser window instead of running headless.",
    )
    parser.add_argument(
        "--browser-channel",
        default="chrome",
        help=(
            "Playwright browser channel. Default 'chrome' uses installed Google Chrome. "
            "Pass an empty string to use Playwright Chromium."
        ),
    )
    parser.add_argument("--output", default="data/prospect_client_analysis.xlsx")
    return parser.parse_args()


def main() -> None:
    load_dotenv()
    args = parse_args()
    api_key = args.api_key or os.getenv("GOOGLE_MAPS_API_KEY")

    if args.provider == "places_api" and not api_key:
        raise SystemExit(
            "Missing API key for provider=places_api. Set GOOGLE_MAPS_API_KEY or pass --api-key."
        )

    categories = [x.strip() for x in args.categories.split(",") if x.strip()]
    businesses, summary = run_pipeline(
        provider=args.provider,
        api_key=api_key,
        location=args.location,
        categories=categories,
        max_results_per_category=args.max_results_per_category,
        enrich_websites=args.enrich_websites,
        min_category_size=args.min_category_size,
        browser_headless=not args.headed,
        browser_channel=args.browser_channel or None,
    )

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)

    if output.suffix.lower() == ".csv":
        businesses.to_csv(output, index=False, encoding="utf-8-sig")
        summary.to_csv(
            output.with_name(output.stem + "_category_summary.csv"),
            index=False,
            encoding="utf-8-sig",
        )
    elif output.suffix.lower() in {".xlsx", ".xls"}:
        output.write_bytes(to_excel_bytes(businesses, summary))
    else:
        raise SystemExit("Output must end with .csv or .xlsx")

    print(f"Saved {len(businesses)} businesses to {output}")
    print(summary.to_string(index=False))


if __name__ == "__main__":
    main()
