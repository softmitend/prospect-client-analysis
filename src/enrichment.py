from __future__ import annotations

import os
import re
import time
from dataclasses import dataclass
from html import unescape
from urllib.parse import urljoin, urlparse

import requests
import tldextract
from bs4 import BeautifulSoup


EMAIL_RE = re.compile(
    r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b",
    re.IGNORECASE,
)
PHONE_RE = re.compile(r"(?:\+?62|0)[\d\s().-]{7,18}\d")
WA_LINK_RE = re.compile(
    r"(?:https?://)?(?:wa\.me/|api\.whatsapp\.com/send\?phone=)(\+?\d+)",
    re.IGNORECASE,
)

LIKELY_PATHS = ("/contact", "/contact-us", "/kontak", "/about", "/about-us", "/tentang")


def _clean_phone(value: str | None) -> str | None:
    if not value:
        return None
    digits = re.sub(r"\D", "", value)
    if digits.startswith("0"):
        digits = "62" + digits[1:]
    if digits.startswith("62") and 9 <= len(digits) <= 15:
        return "+" + digits
    return "+" + digits if value.strip().startswith("+") and digits else (digits or None)


def _domain(url: str) -> str:
    ext = tldextract.extract(url)
    return ".".join(part for part in [ext.domain, ext.suffix] if part)


@dataclass
class WebsiteEnricher:
    timeout: int = 10
    pause_seconds: float = 0.35
    max_pages: int = 3
    user_agent: str = os.getenv(
        "WEBSITE_ENRICH_USER_AGENT",
        "ProspectClientAnalysis/1.0 (+research; public-contact-enrichment)",
    )

    def _fetch(self, url: str) -> tuple[str | None, str | None]:
        try:
            response = requests.get(
                url,
                timeout=self.timeout,
                headers={"User-Agent": self.user_agent, "Accept": "text/html,*/*"},
                allow_redirects=True,
            )
            ctype = response.headers.get("Content-Type", "")
            if response.ok and "text/html" in ctype:
                return response.url, response.text
        except requests.RequestException:
            pass
        return None, None

    def _same_site(self, base_url: str, candidate_url: str) -> bool:
        return _domain(base_url) == _domain(candidate_url)

    def enrich(self, website_url: str | None) -> dict[str, str | None]:
        empty = {
            "public_email": None,
            "whatsapp_number": None,
            "website_phone": None,
            "website_meta_description": None,
            "website_domain": None,
        }
        if not website_url:
            return empty

        if not website_url.startswith(("http://", "https://")):
            website_url = "https://" + website_url.lstrip("/")

        base_domain = _domain(website_url)
        emails: set[str] = set()
        phones: set[str] = set()
        whatsapp: set[str] = set()
        description: str | None = None
        visited: set[str] = set()
        queue = [website_url]

        while queue and len(visited) < self.max_pages:
            url = queue.pop(0)
            if url in visited:
                continue
            visited.add(url)

            final_url, html = self._fetch(url)
            if not html or not final_url:
                continue

            soup = BeautifulSoup(html, "html.parser")
            if description is None:
                meta = soup.find("meta", attrs={"name": re.compile("^description$", re.I)})
                if meta and meta.get("content"):
                    description = re.sub(r"\s+", " ", unescape(meta["content"])).strip()[:500]

            text = soup.get_text(" ", strip=True)
            emails.update(EMAIL_RE.findall(text))
            phones.update(_clean_phone(x) for x in PHONE_RE.findall(text) if _clean_phone(x))

            for link in soup.find_all("a", href=True):
                href = link.get("href", "").strip()
                if href.startswith("mailto:"):
                    email = href.split(":", 1)[1].split("?", 1)[0].strip()
                    if EMAIL_RE.fullmatch(email):
                        emails.add(email)
                elif href.startswith("tel:"):
                    phone = _clean_phone(href.split(":", 1)[1])
                    if phone:
                        phones.add(phone)

                wa = WA_LINK_RE.search(href)
                if wa:
                    phone = _clean_phone(wa.group(1))
                    if phone:
                        whatsapp.add(phone)

                absolute = urljoin(final_url, href)
                path = urlparse(absolute).path.lower().rstrip("/")
                if (
                    absolute.startswith(("http://", "https://"))
                    and self._same_site(final_url, absolute)
                    and any(path.endswith(p) for p in LIKELY_PATHS)
                    and absolute not in visited
                ):
                    queue.append(absolute)

            for match in WA_LINK_RE.findall(html):
                phone = _clean_phone(match)
                if phone:
                    whatsapp.add(phone)

            time.sleep(self.pause_seconds)

        return {
            "public_email": sorted(emails)[0] if emails else None,
            "whatsapp_number": sorted(whatsapp)[0] if whatsapp else None,
            "website_phone": sorted(phones)[0] if phones else None,
            "website_meta_description": description,
            "website_domain": base_domain or None,
        }
