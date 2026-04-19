import os
import csv
import logging
from datetime import date
from pathlib import Path
from typing import Optional

from config import load_config
from scraper import JobScraper
from scorer import JobScorer

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
    parser.add_argument("--criteria", "-c", help="Override job search criteria")
    parser.add_argument("--min-score", "-s", type=int, help="Minimum relevance score (1-10)")
    parser.add_argument("--search", help="Search term to filter jobs (e.g., 'machine learning')")
    parser.add_argument("--debug", action="store_true", help="Enable debug logging")

    args = parser.parse_args()

    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)

    run_agent(
        criteria_override=args.criteria,
        min_score_override=args.min_score,
        search_override=args.search,
    )


if __name__ == "__main__":
    main()
