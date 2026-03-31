import requests
import re
import gzip
import logging
import time
import random
import xml.etree.ElementTree as ET
from datetime import datetime
from typing import List
from io import BytesIO

logger = logging.getLogger(__name__)


class YahooNewsUrlGenerator:
    """URL discovery for Yahoo News Hong Kong via RSS feeds and news sitemaps."""

    BASE_URL = "https://hk.news.yahoo.com"

    RSS_CATEGORIES = [
        "",            # main feed (all categories)
        "hong-kong",
        "world",
        "entertainment",
    ]

    SITEMAP_INDEX_URL = (
        "https://hk.news.yahoo.com/sitemap/news-sitemap_index_HK_zh-Hant-HK.xml.gz"
    )

    def __init__(self, timeout: int = 30):
        self.timeout = timeout
        self.headers = {
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            )
        }

    def get_article_urls(self, target_date: datetime) -> List[str]:
        """
        Get article URLs for a specific date.
        Tries news sitemap first (date-specific), falls back to RSS feeds.
        """
        urls = self._discover_from_sitemap(target_date)
        if not urls:
            logger.info(
                f"No URLs found in sitemap for {target_date.date()}, "
                "falling back to RSS feeds."
            )
            urls = self._discover_from_rss(target_date)
        return urls

    def get_latest_urls(self) -> List[str]:
        """
        Get the latest article URLs from RSS feeds (no date filter).
        Useful for daily backup of recent articles.
        """
        return self._discover_from_rss(target_date=None)

    def _discover_from_rss(
        self, target_date: datetime | None, max_retries: int = 3
    ) -> List[str]:
        """Discover article URLs from RSS feeds, optionally filtered by date."""
        all_urls = set()

        for category in self.RSS_CATEGORIES:
            if category:
                rss_url = f"{self.BASE_URL}/rss/{category}"
            else:
                rss_url = f"{self.BASE_URL}/rss/"

            for attempt in range(max_retries + 1):
                try:
                    response = requests.get(
                        rss_url,
                        headers=self.headers,
                        timeout=self.timeout,
                        allow_redirects=True,
                    )
                    if response.status_code == 403:
                        logger.debug(f"RSS feed blocked for category: {category}")
                        break
                    if response.status_code != 200:
                        raise requests.exceptions.RequestException(
                            f"HTTP {response.status_code}"
                        )

                    urls = self._parse_rss_xml(response.text, target_date)
                    all_urls.update(urls)
                    logger.debug(
                        f"Found {len(urls)} URLs from RSS category '{category or 'main'}'"
                    )
                    break

                except (requests.exceptions.RequestException, Exception) as e:
                    if attempt < max_retries:
                        wait_time = (2**attempt) + random.random()
                        logger.warning(
                            f"Attempt {attempt+1} failed for RSS {rss_url}: {e}. "
                            f"Retrying in {wait_time:.2f}s..."
                        )
                        time.sleep(wait_time)
                    else:
                        logger.warning(
                            f"Failed to fetch RSS {rss_url} after "
                            f"{max_retries+1} attempts: {e}"
                        )

        return sorted(list(all_urls))

    def _parse_rss_xml(
        self, xml_text: str, target_date: datetime | None
    ) -> List[str]:
        """Parse RSS XML and extract article URLs, optionally filtered by date."""
        urls = []
        try:
            root = ET.fromstring(xml_text)
            for item in root.iter("item"):
                link = item.find("link")
                if link is None or not link.text:
                    continue

                url = link.text.strip()
                if not url.endswith(".html"):
                    continue

                # Filter by date if specified
                if target_date is not None:
                    pub_date = item.find("pubDate")
                    if pub_date is not None and pub_date.text:
                        try:
                            # RSS date format: "Mon, 31 Mar 2026 07:49:45 +0000"
                            article_date = self._parse_rss_date(pub_date.text)
                            if article_date and article_date.date() != target_date.date():
                                continue
                        except Exception:
                            # If we can't parse the date, include the article
                            pass

                urls.append(url)
        except ET.ParseError as e:
            logger.warning(f"Failed to parse RSS XML: {e}")

        return urls

    def _parse_rss_date(self, date_str: str) -> datetime | None:
        """Parse RSS pubDate format."""
        # Format: "Mon, 31 Mar 2026 07:49:45 +0000"
        formats = [
            "%a, %d %b %Y %H:%M:%S %z",
            "%a, %d %b %Y %H:%M:%S %Z",
        ]
        for fmt in formats:
            try:
                return datetime.strptime(date_str.strip(), fmt)
            except ValueError:
                continue
        return None

    def _discover_from_sitemap(
        self, target_date: datetime, max_retries: int = 3
    ) -> List[str]:
        """
        Discover article URLs from Yahoo News sitemap.
        The sitemap index contains dated sub-sitemaps.
        """
        # First, fetch the sitemap index to find date-specific sitemaps
        for attempt in range(max_retries + 1):
            try:
                response = requests.get(
                    self.SITEMAP_INDEX_URL,
                    headers=self.headers,
                    timeout=self.timeout,
                )
                if response.status_code != 200:
                    if attempt < max_retries:
                        wait_time = (2**attempt) + random.random()
                        time.sleep(wait_time)
                        continue
                    logger.warning(
                        f"Sitemap index returned HTTP {response.status_code}"
                    )
                    return []

                # Decompress gzip content
                xml_text = gzip.decompress(response.content).decode("utf-8")
                return self._parse_sitemap_index(xml_text, target_date)

            except (requests.exceptions.RequestException, Exception) as e:
                if attempt < max_retries:
                    wait_time = (2**attempt) + random.random()
                    logger.warning(
                        f"Attempt {attempt+1} failed for sitemap index: {e}. "
                        f"Retrying in {wait_time:.2f}s..."
                    )
                    time.sleep(wait_time)
                else:
                    logger.warning(
                        f"Failed to fetch sitemap index after "
                        f"{max_retries+1} attempts: {e}"
                    )

        return []

    def _parse_sitemap_index(
        self, xml_text: str, target_date: datetime
    ) -> List[str]:
        """Parse sitemap index XML and fetch date-matching sub-sitemaps."""
        all_urls = []
        date_str = target_date.strftime("%Y-%m-%d")

        try:
            root = ET.fromstring(xml_text)
            # Handle XML namespace
            ns = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}

            for sitemap in root.findall("sm:sitemap", ns):
                loc = sitemap.find("sm:loc", ns)
                if loc is None or not loc.text:
                    continue

                sitemap_url = loc.text.strip()

                # Check if this sub-sitemap matches our target date
                if date_str in sitemap_url:
                    urls = self._fetch_sub_sitemap(sitemap_url)
                    all_urls.extend(urls)

        except ET.ParseError as e:
            logger.warning(f"Failed to parse sitemap index XML: {e}")

        return all_urls

    def _fetch_sub_sitemap(
        self, sitemap_url: str, max_retries: int = 3
    ) -> List[str]:
        """Fetch and parse a sub-sitemap for article URLs."""
        for attempt in range(max_retries + 1):
            try:
                response = requests.get(
                    sitemap_url,
                    headers=self.headers,
                    timeout=self.timeout,
                )
                if response.status_code != 200:
                    if attempt < max_retries:
                        wait_time = (2**attempt) + random.random()
                        time.sleep(wait_time)
                        continue
                    return []

                # Handle gzipped content
                if sitemap_url.endswith(".gz"):
                    xml_text = gzip.decompress(response.content).decode("utf-8")
                else:
                    xml_text = response.text

                return self._parse_sitemap_urls(xml_text)

            except (requests.exceptions.RequestException, Exception) as e:
                if attempt < max_retries:
                    wait_time = (2**attempt) + random.random()
                    time.sleep(wait_time)
                else:
                    logger.warning(
                        f"Failed to fetch sub-sitemap {sitemap_url}: {e}"
                    )

        return []

    def _parse_sitemap_urls(self, xml_text: str) -> List[str]:
        """Parse a sitemap XML and extract article URLs."""
        urls = []
        try:
            root = ET.fromstring(xml_text)
            ns = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}

            for url_elem in root.findall("sm:url", ns):
                loc = url_elem.find("sm:loc", ns)
                if loc is not None and loc.text:
                    url = loc.text.strip()
                    if url.endswith(".html"):
                        urls.append(url)
        except ET.ParseError as e:
            logger.warning(f"Failed to parse sitemap XML: {e}")

        return urls
