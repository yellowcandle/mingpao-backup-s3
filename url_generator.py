import requests
import re
import logging
import time
import random
from datetime import datetime
from typing import List, Set

logger = logging.getLogger(__name__)

class MingPaoUrlGenerator:
    # Use HTTP to avoid SSL issues with Ming Pao's unstable HTTPS
    BASE_URL = "http://www.mingpaocanada.com/tor"
    
    HK_GA_PREFIXES = [
        "gaa", "gab", "gac", "gad", "gae", "gaf", "gba", "gbb", "gbc", "gbd", "gbe", "gbf",
        "gca", "gcb", "gcc", "gcd", "gce", "gcf", "gga", "ggb", "ggc", "ggd", "gge", "ggf",
        "ggh", "gha", "ghb", "ghc", "ghd", "ghe", "ghf", "gma", "gmb", "gmc", "gmd", "gme",
        "gmf", "gmg", "gza", "gzb", "gzc",
    ]

    def __init__(self, timeout: int = 30):
        self.timeout = timeout
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }

    def get_article_urls(self, target_date: datetime) -> List[str]:
        """Try index page discovery first, fallback to bruteforce."""
        urls = self._discover_from_index(target_date)
        if not urls:
            logger.info(f"No URLs found in index for {target_date.date()}, falling back to bruteforce.")
            urls = self._generate_bruteforce(target_date)
        return urls

    def _discover_from_index(self, target_date: datetime, max_retries: int = 3) -> List[str]:
        date_str = target_date.strftime("%Y%m%d")
        index_url = f"{self.BASE_URL}/htm/News/{date_str}/HK-GAindex_r.htm"
        
        for attempt in range(max_retries + 1):
            try:
                # Disable redirects to avoid being sent to errorpage.html
                response = requests.get(index_url, headers=self.headers, timeout=self.timeout, allow_redirects=False)
                if response.status_code == 404:
                    return []
                # Treat redirects as "not found" since Ming Pao redirects missing pages
                if response.status_code in (301, 302, 303, 307, 308):
                    logger.debug(f"Index page redirected (likely missing): {index_url}")
                    return []
                if response.status_code != 200:
                    raise requests.exceptions.RequestException(f"HTTP {response.status_code}")
                
                article_urls = set()
                pattern = r'href="([^"]*htm/News/\d{8}/HK-[^"]+_r\.htm)"'
                matches = re.findall(pattern, response.text)
                
                for relative_path in matches:
                    if "index" in relative_path.lower():
                        continue
                    clean_path = relative_path.replace("../../../", "")
                    if f"News/{date_str}/" not in clean_path:
                        continue
                    absolute_url = f"{self.BASE_URL}/{clean_path}"
                    article_urls.add(absolute_url)
                    
                return sorted(list(article_urls))
            except (requests.exceptions.RequestException, Exception) as e:
                if attempt < max_retries:
                    wait_time = (2 ** attempt) + random.random()
                    logger.warning(f"Attempt {attempt+1} failed for index {index_url}: {e}. Retrying in {wait_time:.2f}s...")
                    time.sleep(wait_time)
                else:
                    logger.warning(f"Failed to discover from index {index_url} after {max_retries+1} attempts: {e}")
        
        return []

    def _generate_bruteforce(self, target_date: datetime) -> List[str]:
        date_str = target_date.strftime("%Y%m%d")
        base_path = f"{self.BASE_URL}/htm/News/{date_str}"
        article_urls = []
        for prefix in self.HK_GA_PREFIXES:
            for num in range(1, 9):
                url = f"{base_path}/HK-{prefix}{num}_r.htm"
                article_urls.append(url)
        return article_urls
