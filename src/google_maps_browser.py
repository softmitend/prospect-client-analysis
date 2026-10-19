from __future__ import annotations

import hashlib
import re
import time
from dataclasses import dataclass
from typing import Any, Iterable
from urllib.parse import quote

from playwright.sync_api import Browser, BrowserContext, Page, TimeoutError as PlaywrightTimeoutError, sync_playwright


_CAPTCHA_MARKERS = (
    "unusual traffic",
    "our systems have detected",
    "traffic tidak biasa",
    "sistem kami mendeteksi",
    "captcha",
)

_CLOSED_MARKERS = {
    "temporarily closed": "CLOSED_TEMPORARILY",
    "tutup sementara": "CLOSED_TEMPORARILY",
    "permanently closed": "CLOSED_PERMANENTLY",
    "tutup permanen": "CLOSED_PERMANENTLY",
}


def _clean_text(value: str | None) -> str | None:
    if value is None:
        return None
    value = re.sub(r"\s+", " ", value).strip()
    return value or None


def _strip_label(value: str | None, labels: tuple[str, ...]) -> str | None:
    text = _clean_text(value)
    if not text:
        return None
    lowered = text.lower()
    for label in labels:
        prefix = label.lower().rstrip(":") + ":"
        if lowered.startswith(prefix):
            return _clean_text(text[len(prefix):])
    return text


def _parse_float(text: str | None) -> float | None:
    if not text:
        return None
    match = re.search(r"(\d+(?:[.,]\d+)?)", text)
    if not match:
        return None
    try:
        return float(match.group(1).replace(",", "."))
    except ValueError:
        return None


def _parse_review_count(text: str | None) -> int | None:
    if not text:
        return None
    lowered = text.lower().replace("\u00a0", " ")
    match = re.search(r"([\d.,]+)\s*(?:reviews?|ulasan)", lowered)
    if not match:
        return None
    digits = re.sub(r"\D", "", match.group(1))
    return int(digits) if digits else None


def _coordinates(url: str) -> tuple[float | None, float | None]:
    match = re.search(r"@(-?\d+(?:\.\d+)?),(-?\d+(?:\.\d+)?)", url)
    if not match:
        return None, None
    return float(match.group(1)), float(match.group(2))


@dataclass
class GoogleMapsPlaywrightScraper:
    headless: bool = True
    browser_channel: str | None = None
    navigation_timeout_ms: int = 30_000
    detail_pause_seconds: float = 0.65
    scroll_pause_seconds: float = 0.9
    max_idle_scrolls: int = 4

    def _launch_browser(self, playwright) -> Browser:
        kwargs: dict[str, Any] = {"headless": self.headless}
        if self.browser_channel:
            kwargs["channel"] = self.browser_channel
        try:
            return playwright.chromium.launch(**kwargs)
        except Exception as exc:
            if self.browser_channel:
                raise RuntimeError(
                    f"Could not launch browser channel '{self.browser_channel}'. "
                    "Try leaving browser channel empty or run "
                    "`python -m playwright install chromium`."
                ) from exc
            raise RuntimeError(
                "Playwright Chromium is not installed. Run "
                "`python -m playwright install chromium` once, then retry."
            ) from exc

    def _new_context(
        self,
        browser: Browser,
        language_code: str,
        region_code: str,
    ) -> BrowserContext:
        locale = f"{language_code.lower()}-{region_code.upper()}"
        return browser.new_context(
            locale=locale,
            viewport={"width": 1440, "height": 1000},
        )

    @staticmethod
    def _assert_not_blocked(page: Page) -> None:
        try:
            body = page.locator("body").inner_text(timeout=3_000).lower()
        except Exception:
            body = ""
        if any(marker in body for marker in _CAPTCHA_MARKERS):
            raise RuntimeError(
                "Google displayed a CAPTCHA / unusual-traffic page. "
                "The scraper intentionally does not bypass it. Stop the run, "
                "wait, reduce request volume, or use the official API."
            )

    @staticmethod
    def _handle_consent(page: Page) -> None:
        candidates = (
            "Accept all",
            "I agree",
            "Terima semua",
            "Setuju",
            "Reject all",
            "Tolak semua",
        )
        for label in candidates:
            try:
                button = page.get_by_role(
                    "button",
                    name=re.compile(f"^{re.escape(label)}$", re.I),
                )
                if button.count():
                    button.first.click(timeout=1_500)
                    page.wait_for_timeout(500)
                    return
            except Exception:
                continue

    @staticmethod
    def _first_attr(page: Page, selectors: tuple[str, ...], attr: str) -> str | None:
        for selector in selectors:
            try:
                locator = page.locator(selector)
                if locator.count():
                    value = locator.first.get_attribute(attr)
                    if value:
                        return _clean_text(value)
            except Exception:
                continue
        return None

    @staticmethod
    def _first_text(page: Page, selectors: tuple[str, ...]) -> str | None:
        for selector in selectors:
            try:
                locator = page.locator(selector)
                if locator.count():
                    value = locator.first.inner_text(timeout=2_000)
                    if value:
                        return _clean_text(value)
            except Exception:
                continue
        return None

    def _collect_result_links(self, page: Page, max_results: int) -> list[str]:
        feed = page.locator('div[role="feed"]')
        if not feed.count():
            current = page.url
            return [current] if "/maps/place/" in current else []

        links: list[str] = []
        seen: set[str] = set()
        idle_scrolls = 0
        previous_count = 0

        while len(links) < max_results and idle_scrolls < self.max_idle_scrolls:
            hrefs = page.locator('a[href*="/maps/place/"]').evaluate_all(
                "(els) => els.map(e => e.href).filter(Boolean)"
            )
            for href in hrefs:
                canonical = href.split("?")[0]
                if canonical not in seen:
                    seen.add(canonical)
                    links.append(href)
                    if len(links) >= max_results:
                        break

            if len(links) >= max_results:
                break

            if len(links) == previous_count:
                idle_scrolls += 1
            else:
                idle_scrolls = 0
                previous_count = len(links)

            try:
                feed.evaluate("(el) => { el.scrollTop = el.scrollHeight; }")
            except Exception:
                page.mouse.wheel(0, 5000)
            page.wait_for_timeout(int(self.scroll_pause_seconds * 1000))
            self._assert_not_blocked(page)

        return links[:max_results]

    def _extract_detail(
        self,
        page: Page,
        url: str,
        requested_category: str,
        source_query: str,
    ) -> dict[str, Any] | None:
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=self.navigation_timeout_ms)
            self._handle_consent(page)
            self._assert_not_blocked(page)
            page.locator("h1").first.wait_for(timeout=10_000)
        except PlaywrightTimeoutError:
            return None

        name = self._first_text(page, ("h1",))
        if not name:
            return None

        address_aria = self._first_attr(
            page,
            (
                '[data-item-id="address"]',
                'button[aria-label^="Address:"]',
                'button[aria-label^="Alamat:"]',
            ),
            "aria-label",
        )
        address = _strip_label(address_aria, ("Address", "Alamat"))

        website = self._first_attr(
            page,
            (
                'a[data-item-id="authority"]',
                'a[aria-label^="Website:"]',
                'a[aria-label^="Situs:"]',
            ),
            "href",
        )

        phone_item_id = self._first_attr(
            page,
            ('button[data-item-id^="phone:tel:"]', '[data-item-id^="phone:tel:"]'),
            "data-item-id",
        )
        phone = None
        if phone_item_id and "phone:tel:" in phone_item_id:
            phone = _clean_text(phone_item_id.split("phone:tel:", 1)[1])
        if not phone:
            phone_aria = self._first_attr(
                page,
                (
                    'button[aria-label^="Phone:"]',
                    'button[aria-label^="Telepon:"]',
                ),
                "aria-label",
            )
            phone = _strip_label(phone_aria, ("Phone", "Telepon"))

        hours_aria = self._first_attr(
            page,
            (
                '[data-item-id="oh"]',
                'button[aria-label*="hours"]',
                'button[aria-label*="Jam"]',
            ),
            "aria-label",
        )
        hours_text = _strip_label(
            hours_aria,
            ("Hours", "Opening hours", "Jam buka", "Jam operasional"),
        )

        category = self._first_text(
            page,
            (
                'button[jsaction*="pane.rating.category"]',
                'button[jsaction*="category"]',
                "button.DkEaL",
            ),
        ) or requested_category

        rating_aria = self._first_attr(
            page,
            (
                '[role="img"][aria-label*="stars"]',
                '[role="img"][aria-label*="star"]',
                '[role="img"][aria-label*="bintang"]',
            ),
            "aria-label",
        )
        rating = _parse_float(rating_aria)

        reviews_aria = self._first_attr(
            page,
            (
                'button[aria-label*="reviews"]',
                'button[aria-label*="ulasan"]',
                '[aria-label*="reviews"]',
                '[aria-label*="ulasan"]',
            ),
            "aria-label",
        )
        review_count = _parse_review_count(reviews_aria)

        current_url = page.url
        latitude, longitude = _coordinates(current_url)
        try:
            body_text = page.locator("body").inner_text(timeout=2_000).lower()
        except Exception:
            body_text = ""

        status = "OPERATIONAL"
        for marker, mapped in _CLOSED_MARKERS.items():
            if marker in body_text:
                status = mapped
                break

        stable_id = "maps:" + hashlib.sha1(
            current_url.split("?")[0].encode("utf-8")
        ).hexdigest()

        time.sleep(self.detail_pause_seconds)

        return {
            "id": stable_id,
            "displayName": {"text": name},
            "formattedAddress": address,
            "location": {"latitude": latitude, "longitude": longitude},
            "primaryType": requested_category,
            "primaryTypeDisplayName": {"text": category},
            "types": [requested_category],
            "websiteUri": website,
            "nationalPhoneNumber": phone,
            "internationalPhoneNumber": phone,
            "regularOpeningHours": {
                "weekdayDescriptions": [hours_text] if hours_text else []
            },
            "googleMapsUri": current_url,
            "rating": rating,
            "userRatingCount": review_count,
            "businessStatus": status,
            "_source_query": source_query,
            "_requested_category": requested_category,
        }

    def collect_categories(
        self,
        location: str,
        categories: Iterable[str],
        max_results_per_category: int = 40,
        language_code: str = "id",
        region_code: str = "ID",
    ) -> list[dict[str, Any]]:
        clean_categories = [c.strip() for c in categories if c and c.strip()]
        rows: list[dict[str, Any]] = []

        with sync_playwright() as playwright:
            browser = self._launch_browser(playwright)
            context = self._new_context(browser, language_code, region_code)
            search_page = context.new_page()
            detail_page = context.new_page()
            search_page.set_default_timeout(self.navigation_timeout_ms)
            detail_page.set_default_timeout(self.navigation_timeout_ms)

            try:
                for category in clean_categories:
                    query = f"{category} in {location}"
                    search_url = f"https://www.google.com/maps/search/{quote(query, safe='')}"
                    search_page.goto(
                        search_url,
                        wait_until="domcontentloaded",
                        timeout=self.navigation_timeout_ms,
                    )
                    self._handle_consent(search_page)
                    self._assert_not_blocked(search_page)
                    search_page.wait_for_timeout(1_500)

                    links = self._collect_result_links(
                        search_page,
                        max(1, int(max_results_per_category)),
                    )
                    if not links and "/maps/place/" in search_page.url:
                        links = [search_page.url]

                    for link in links:
                        item = self._extract_detail(
                            detail_page,
                            link,
                            requested_category=category,
                            source_query=query,
                        )
                        if item:
                            rows.append(item)
            finally:
                context.close()
                browser.close()

        return rows
