from __future__ import annotations

import asyncio
import hashlib
import re
from dataclasses import dataclass
from typing import Any, Iterable
from urllib.parse import quote

from playwright.async_api import (
    Browser,
    BrowserContext,
    Page,
    TimeoutError as PlaywrightTimeoutError,
    async_playwright,
)


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
    value = re.sub(r"\s+", " ", str(value)).strip()
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
    match = re.search(r"@(-?\d+(?:\.\d+)?),(-?\d+(?:\.\d+)?)", url or "")
    if not match:
        return None, None
    return float(match.group(1)), float(match.group(2))


@dataclass
class GoogleMapsAsyncScraper:
    headless: bool = True
    navigation_timeout_ms: int = 30_000
    detail_pause_seconds: float = 0.7
    scroll_pause_seconds: float = 1.0
    max_idle_scrolls: int = 4

    async def _launch_browser(self, playwright) -> Browser:
        try:
            return await playwright.chromium.launch(headless=self.headless)
        except Exception as exc:
            raise RuntimeError(
                "Playwright Chromium is not installed. Run `python -m playwright install --with-deps chromium`."
            ) from exc

    async def _new_context(
        self,
        browser: Browser,
        language_code: str,
        region_code: str,
    ) -> BrowserContext:
        return await browser.new_context(
            locale=f"{language_code.lower()}-{region_code.upper()}",
            viewport={"width": 1440, "height": 1000},
        )

    @staticmethod
    async def _assert_not_blocked(page: Page) -> None:
        try:
            body = (await page.locator("body").inner_text(timeout=3000)).lower()
        except Exception:
            body = ""
        if any(marker in body for marker in _CAPTCHA_MARKERS):
            raise RuntimeError(
                "Google displayed a CAPTCHA / unusual-traffic page. The scraper intentionally does not bypass it. Reduce request volume or try again later."
            )

    @staticmethod
    async def _handle_consent(page: Page) -> None:
        for label in (
            "Accept all",
            "I agree",
            "Terima semua",
            "Setuju",
            "Reject all",
            "Tolak semua",
        ):
            try:
                button = page.get_by_role(
                    "button",
                    name=re.compile(f"^{re.escape(label)}$", re.I),
                )
                if await button.count():
                    await button.first.click(timeout=1500)
                    await page.wait_for_timeout(500)
                    return
            except Exception:
                continue

    @staticmethod
    async def _first_attr(page: Page, selectors: tuple[str, ...], attr: str) -> str | None:
        for selector in selectors:
            try:
                locator = page.locator(selector)
                if await locator.count():
                    value = await locator.first.get_attribute(attr)
                    if value:
                        return _clean_text(value)
            except Exception:
                continue
        return None

    @staticmethod
    async def _first_text(page: Page, selectors: tuple[str, ...]) -> str | None:
        for selector in selectors:
            try:
                locator = page.locator(selector)
                if await locator.count():
                    value = await locator.first.inner_text(timeout=2000)
                    if value:
                        return _clean_text(value)
            except Exception:
                continue
        return None

    async def _collect_result_links(self, page: Page, max_results: int) -> list[str]:
        feed = page.locator('div[role="feed"]')
        if not await feed.count():
            current = page.url
            return [current] if "/maps/place/" in current else []

        links: list[str] = []
        seen: set[str] = set()
        idle_scrolls = 0
        previous_count = 0

        while len(links) < max_results and idle_scrolls < self.max_idle_scrolls:
            hrefs = await page.locator('a[href*="/maps/place/"]').evaluate_all(
                "(els) => els.map(e => e.href).filter(Boolean)"
            )
            for href in hrefs:
                canonical = href.split("?")[0]
                if canonical not in seen:
                    seen.add(canonical)
                    links.append(href)
                    if len(links) >= max_results:
                        break

            if len(links) == previous_count:
                idle_scrolls += 1
            else:
                idle_scrolls = 0
                previous_count = len(links)

            if len(links) >= max_results:
                break

            try:
                await feed.evaluate("(el) => { el.scrollTop = el.scrollHeight; }")
            except Exception:
                await page.mouse.wheel(0, 5000)

            await page.wait_for_timeout(int(self.scroll_pause_seconds * 1000))
            await self._assert_not_blocked(page)

        return links[:max_results]

    async def _extract_detail(
        self,
        page: Page,
        url: str,
        requested_category: str,
        source_query: str,
    ) -> dict[str, Any] | None:
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=self.navigation_timeout_ms)
            await self._handle_consent(page)
            await self._assert_not_blocked(page)
            await page.locator("h1").first.wait_for(timeout=10_000)
        except PlaywrightTimeoutError:
            return None

        name = await self._first_text(page, ("h1",))
        if not name:
            return None

        address_aria = await self._first_attr(
            page,
            (
                '[data-item-id="address"]',
                'button[aria-label^="Address:"]',
                'button[aria-label^="Alamat:"]',
            ),
            "aria-label",
        )
        address = _strip_label(address_aria, ("Address", "Alamat"))

        website = await self._first_attr(
            page,
            (
                'a[data-item-id="authority"]',
                'a[aria-label^="Website:"]',
                'a[aria-label^="Situs:"]',
                'a[aria-label*="Website"]',
                'a[aria-label*="Situs"]',
            ),
            "href",
        )

        phone_item_id = await self._first_attr(
            page,
            ('button[data-item-id^="phone:tel:"]', '[data-item-id^="phone:tel:"]'),
            "data-item-id",
        )
        phone = None
        if phone_item_id and "phone:tel:" in phone_item_id:
            phone = _clean_text(phone_item_id.split("phone:tel:", 1)[1])
        if not phone:
            phone_aria = await self._first_attr(
                page,
                (
                    'button[aria-label^="Phone:"]',
                    'button[aria-label^="Telepon:"]',
                    'button[aria-label*="Phone"]',
                    'button[aria-label*="Telepon"]',
                ),
                "aria-label",
            )
            phone = _strip_label(phone_aria, ("Phone", "Telepon"))

        hours_aria = await self._first_attr(
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

        category = await self._first_text(
            page,
            (
                'button[jsaction*="pane.rating.category"]',
                'button[jsaction*="category"]',
                "button.DkEaL",
            ),
        ) or requested_category

        rating_aria = await self._first_attr(
            page,
            (
                '[role="img"][aria-label*="stars"]',
                '[role="img"][aria-label*="star"]',
                '[role="img"][aria-label*="bintang"]',
            ),
            "aria-label",
        )
        rating = _parse_float(rating_aria)

        reviews_aria = await self._first_attr(
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
            body_text = (await page.locator("body").inner_text(timeout=2000)).lower()
        except Exception:
            body_text = ""

        status = "OPERATIONAL"
        for marker, mapped in _CLOSED_MARKERS.items():
            if marker in body_text:
                status = mapped
                break

        stable_id = "maps:" + hashlib.sha1(current_url.split("?")[0].encode("utf-8")).hexdigest()

        await asyncio.sleep(self.detail_pause_seconds)

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
            "regularOpeningHours": {"weekdayDescriptions": [hours_text] if hours_text else []},
            "googleMapsUri": current_url,
            "rating": rating,
            "userRatingCount": review_count,
            "businessStatus": status,
            "_source_query": source_query,
            "_requested_category": requested_category,
        }

    async def collect_categories(
        self,
        location: str,
        categories: Iterable[str],
        max_results_per_category: int = 40,
        language_code: str = "id",
        region_code: str = "ID",
    ) -> list[dict[str, Any]]:
        clean_categories = [c.strip() for c in categories if c and c.strip()]
        rows: list[dict[str, Any]] = []

        async with async_playwright() as playwright:
            browser = await self._launch_browser(playwright)
            context = await self._new_context(browser, language_code, region_code)
            search_page = await context.new_page()
            detail_page = await context.new_page()
            search_page.set_default_timeout(self.navigation_timeout_ms)
            detail_page.set_default_timeout(self.navigation_timeout_ms)

            try:
                for category in clean_categories:
                    query = f"{category} in {location}"
                    search_url = f"https://www.google.com/maps/search/{quote(query, safe='')}"
                    await search_page.goto(
                        search_url,
                        wait_until="domcontentloaded",
                        timeout=self.navigation_timeout_ms,
                    )
                    await self._handle_consent(search_page)
                    await self._assert_not_blocked(search_page)
                    await search_page.wait_for_timeout(1500)

                    links = await self._collect_result_links(
                        search_page,
                        max(1, int(max_results_per_category)),
                    )

                    for link in links:
                        item = await self._extract_detail(
                            detail_page,
                            link,
                            requested_category=category,
                            source_query=query,
                        )
                        if item:
                            rows.append(item)
            finally:
                await context.close()
                await browser.close()

        return rows
