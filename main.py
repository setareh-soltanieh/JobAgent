import os
import csv
import logging
import time
import requests
from datetime import date
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse
from bs4 import BeautifulSoup

from config import load_config
from scraper import JobScraper
from scorer import JobScorer
from network import retry_with_backoff

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)


def load_seen_urls(csv_file: str) -> set:
    if not os.path.exists(csv_file):
        return set()
    with open(csv_file, "r", encoding="utf-8") as f:
        return {row["url"] for row in csv.DictReader(f)}


def append_jobs_to_csv(csv_file: str, fieldnames: list, jobs: list[dict]):
    is_empty = not os.path.exists(csv_file) or os.path.getsize(csv_file) == 0

    with open(csv_file, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        if is_empty:
            writer.writeheader()
        writer.writerows(jobs)


def scrape_single_job(url: str, output_dir: str = "jobs", use_session: bool = True):
    parsed = urlparse(url)

    headers = {
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,application/xhtml+xml,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "gzip, deflate, br",
        "DNT": "1",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "none",
        "Sec-Fetch-User": "?1",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    }

    session = requests.Session() if use_session else requests

    def _fetch():
        resp = session.get(url, headers=headers, timeout=30, allow_redirects=True)
        resp.raise_for_status()
        return resp

    try:
        resp = retry_with_backoff(_fetch)
    except requests.exceptions.RequestException as e:
        logger.error(f"Failed to fetch {url}: {e}")
        return None

    soup = BeautifulSoup(resp.text, "html.parser")
    description = soup.get_text(" ", strip=True)

    parsed = urlparse(url)
    path_parts = [p for p in parsed.path.strip("/").split("/") if p]
    filename = (
        "-".join(path_parts[-2:])
        if len(path_parts) >= 2
        else parsed.path.strip("/").replace("/", "-")
    )
    if not filename:
        filename = "job"
    filename = f"{filename[:50]}.md"
    filename = "".join(c if c.isalnum() or c in "-_" else "_" for c in filename)

    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    full_path = output_path / filename
    content = f"""# Job Posting

**URL:** {url}

**Date Scraped:** {date.today().isoformat()}

---

{description}

---

*Scraped from: {url}*
"""
    with open(full_path, "w", encoding="utf-8") as f:
        f.write(content)

    logger.info(f"Saved to: {full_path}")
    return full_path


def run_agent(
    criteria_override: Optional[str] = None,
    min_score_override: Optional[int] = None,
    search_override: Optional[str] = None,
):

    config = load_config()

    if criteria_override:
        os.environ["JOB_SEARCH_CRITERIA"] = criteria_override

    if min_score_override is not None:
        config["scoring"]["min_score"] = min_score_override

    if search_override is not None:
        config["scraping"]["search_text"] = search_override

    csv_file = config["output"]["csv_file"]
    fieldnames = config["output"]["fieldnames"]

    seen = load_seen_urls(csv_file)
    logger.info(f"Loaded {len(seen)} previously seen job URLs")

    all_jobs = []
    companies = config.get("companies", [])
    if not companies:
        logger.error("No companies configured in config.yaml")
        return

    for company_config in companies:
        logger.info(f"\n{'=' * 50}")
        logger.info(f"Scraping: {company_config['name']}")
        logger.info(f"{'=' * 50}")

        scraper = JobScraper(config, company_config)
        jobs = scraper.scrape_all()
        all_jobs.extend(jobs)

    new_jobs = [j for j in all_jobs if j["url"] not in seen]
    logger.info(f"Found {len(new_jobs)} new jobs to evaluate")

    if not new_jobs:
        logger.info("No new jobs found. Exiting.")
        return

    scorer = JobScorer(config)
    relevant_jobs = []

    for i, job in enumerate(new_jobs, 1):
        logger.info(f"[{i}/{len(new_jobs)}] Scoring: {job['title']}")

        try:
            result = scorer.score(job)
            score = result.get("score", 0)
            reason = result.get("reason", "No reason provided")

            if score >= config["scoring"]["min_score"]:
                logger.info(f"  ✓ {job['title']} — {score}/10: {reason}")
                relevant_jobs.append(
                    {
                        "date": date.today().isoformat(),
                        "title": job["title"],
                        "company": job["company"],
                        "location": job["location"],
                        "url": job["url"],
                        "score": score,
                        "reason": reason,
                    }
                )
            else:
                logger.info(f"  ✗ {job['title']} — {score}/10 (skipped)")
        except Exception as e:
            logger.error(f"  Error scoring '{job['title']}': {e}")

    if relevant_jobs:
        append_jobs_to_csv(csv_file, fieldnames, relevant_jobs)
        logger.info(f"Added {len(relevant_jobs)} relevant jobs to {csv_file}")
    else:
        logger.info("No relevant jobs found matching criteria")


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Job Search Agent")
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    subparsers.add_parser("run", help="Run the job search agent")

    scrape_parser = subparsers.add_parser(
        "scrape", help="Scrape a job posting URL to markdown"
    )
    scrape_parser.add_argument("url", help="Job posting URL")
    scrape_parser.add_argument(
        "--output", "-o", default="jobs", help="Output directory"
    )

    parser.add_argument("--criteria", "-c", help="Override job search criteria")
    parser.add_argument(
        "--min-score", "-s", type=int, help="Minimum relevance score (1-10)"
    )
    parser.add_argument(
        "--search", help="Search term to filter jobs (e.g., 'machine learning')"
    )
    parser.add_argument("--debug", action="store_true", help="Enable debug logging")

    args = parser.parse_args()

    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)

    if args.command == "scrape":
        logger.info(f"Fetching: {args.url}")
        result = scrape_single_job(args.url, args.output)
        if result:
            logger.info(f"Done! Saved to {result}")
        else:
            logger.error("Failed to scrape job posting")
            import sys

            sys.exit(1)
        return

    run_agent(
        criteria_override=args.criteria,
        min_score_override=args.min_score,
        search_override=args.search,
    )


if __name__ == "__main__":
    main()
