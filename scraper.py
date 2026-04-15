import os
import json
import time
import logging
from pathlib import Path
from typing import Optional

from bs4 import BeautifulSoup
import network


logger = logging.getLogger(__name__)


class JobCache:
    def __init__(self, cache_file: str):
        self.cache_file = Path(cache_file)
        self._cache: dict = {}
        self.load()

    def load(self):
        if self.cache_file.exists():
            try:
                with open(self.cache_file) as f:
                    self._cache = json.load(f)
                logger.info(f"Loaded {len(self._cache)} cached job descriptions")
            except (json.JSONDecodeError, IOError) as e:
                logger.warning(f"Failed to load cache: {e}")
                self._cache = {}

    def save(self):
        with open(self.cache_file, "w") as f:
            json.dump(self._cache, f)
        logger.debug(f"Saved {len(self._cache)} job descriptions to cache")

    def get(self, url: str) -> Optional[str]:
        return self._cache.get(url)

    def set(self, url: str, description: str):
        self._cache[url] = description


class JobScraper:
    def __init__(self, config: dict, cache_enabled: bool = True):
        self.tenant = config["scraping"]["tenant"]
        self.site = config["scraping"]["site"]
        self.base_url = config["scraping"]["base_url"]
        self.api_url = f"{self.base_url}/wday/cxs/{self.tenant}/{self.site}/jobs"
        self.limit = config["scraping"]["limit_per_page"]
        self.rate_limit_delay = config["scraping"]["rate_limit_delay"]
        self.cache = (
            JobCache(config["cache"]["cache_file"])
            if cache_enabled and config["cache"]["enabled"]
            else None
        )

    def fetch_job_detail(self, external_path: str) -> str:
        url = f"{self.base_url}/wday/cxs/{self.tenant}/{self.site}/jobs/job{external_path}"

        if self.cache:
            cached = self.cache.get(url)
            if cached:
                logger.debug(f"Cache hit for: {external_path}")
                return cached

        def _fetch():
            return network.safe_request("GET", url, headers=network.HEADERS)

        resp = network.retry_with_backoff(_fetch)
        if not resp:
            return ""

        detail = resp.json().get("jobPostingInfo", {})
        raw_html = detail.get("jobDescription", "")
        description = BeautifulSoup(raw_html, "html.parser").get_text(" ", strip=True)

        if self.cache and description:
            self.cache.set(url, description)

        return description

    def scrape_all(self) -> list[dict]:
        jobs = []
        offset = 0

        logger.info(f"Starting job scrape from {self.site}")

        while True:
            payload = {
                "appliedFacets": {},
                "limit": self.limit,
                "offset": offset,
                "searchText": "",
            }

            resp = network.safe_request(
                "POST", self.api_url, headers=network.HEADERS, json=payload
            )
            if not resp:
                break

            data = resp.json()
            postings = data.get("jobPostings", [])
            if not postings:
                break

            for p in postings:
                external_path = p.get("externalPath", "")
                job_url = f"{self.base_url}/en-US/{self.site}{external_path}"

                description = self.fetch_job_detail(external_path)
                time.sleep(self.rate_limit_delay)

                location = p.get("locationsText", [""])
                if isinstance(location, list):
                    location = ", ".join(location)

                jobs.append(
                    {
                        "title": p.get("title", ""),
                        "company": "TD Bank",
                        "location": location,
                        "url": job_url,
                        "description": description[:2000],
                    }
                )

            total = data.get("total", 0)
            offset += self.limit
            logger.info(f"Scraped {len(jobs)}/{total} jobs")

            if offset >= total:
                break

        if self.cache:
            self.cache.save()

        logger.info(f"Finished scraping {len(jobs)} jobs")
        return jobs
