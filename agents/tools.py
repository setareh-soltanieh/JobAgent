import csv
import os

from langchain.tools import tool
from config import load_config
from scraper import JobScraper
from scorer import JobScorer


LAST_SEARCH_RESULTS: list[dict] = []


def _load_seen_urls(csv_file: str) -> set[str]:
    if not os.path.exists(csv_file):
        return set()

    with open(csv_file, "r", encoding="utf-8") as f:
        return {row["url"] for row in csv.DictReader(f) if row.get("url")}


def _matches_text(value: str, query: str) -> bool:
    if not query:
        return True

    query_terms = [term for term in query.lower().replace(",", " ").split() if term]
    value = value.lower()
    return all(term in value for term in query_terms)


@tool
def search_jobs(
    company_name: str = "",
    role: str = "",
    location: str = "",
    max_results: int = 50,
) -> str:
    """Search for job postings from company career sites.

    Args:
        company_name: Name of the company to search (e.g., "Autodesk").
                     If not provided, searches all configured companies.
        role: Job title or role keywords to search for (e.g., "Machine Learning Engineer").
        location: Location keywords to filter by (e.g., "Toronto", "Toronto area", "Remote Canada").
        max_results: Maximum number of matching jobs to return.

    Returns:
        A list of found jobs with titles, companies, locations, and URLs.
    """
    global LAST_SEARCH_RESULTS

    config = load_config()
    companies = config.get("companies", [])

    if company_name:
        companies = [c for c in companies if company_name.lower() in c["name"].lower()]
        if not companies:
            available = [c["name"] for c in config.get("companies", [])]
            return f"No company found matching '{company_name}'. Available: {available}"

    if not companies:
        return "No companies configured in config.yaml"

    if role:
        config["scraping"]["search_text"] = role

    all_jobs = []
    for company_config in companies:
        scraper = JobScraper(config, company_config)
        jobs = scraper.scrape_all()
        all_jobs.extend(jobs)

    if not all_jobs:
        LAST_SEARCH_RESULTS = []
        return "No jobs found."

    LAST_SEARCH_RESULTS = all_jobs

    matching_jobs = []
    for job in all_jobs:
        searchable_role = f"{job.get('title', '')} {job.get('description', '')}"
        if not _matches_text(searchable_role, role):
            continue
        if not _matches_text(job.get("location", ""), location):
            continue
        matching_jobs.append(job)

    if not matching_jobs:
        filters = []
        if company_name:
            filters.append(f"company matching '{company_name}'")
        if role:
            filters.append(f"role matching '{role}'")
        if location:
            filters.append(f"location matching '{location}'")
        filter_text = ", ".join(filters) if filters else "the requested filters"
        return f"No jobs found for {filter_text}."

    max_results = max(1, max_results)
    result = f"Found {len(matching_jobs)} matching jobs"
    if len(matching_jobs) > max_results:
        result += f" (showing first {max_results})"
    result += ":\n\n"

    for job in matching_jobs[:max_results]:
        result += f"- {job['title']} at {job['company']}\n"
        result += f"  Location: {job['location']}\n"
        result += f"  URL: {job['url']}\n\n"

    return result


@tool
def list_companies() -> str:
    """List all companies configured for job scraping.

    Returns:
        A list of configured company names.
    """
    config = load_config()
    companies = config.get("companies", [])

    if not companies:
        return "No companies configured."

    result = f"Configured companies ({len(companies)}):\n\n"
    for c in companies:
        result += f"- {c['name']}\n"

    return result


@tool
def filter_jobs(
    role: str = "",
    location: str = "",
    company_name: str = "",
    min_score: int = 0,
    max_results: int = 10,
) -> str:
    """Filter the jobs found by the most recent search_jobs call.

    Args:
        role: Job title or role keywords to filter by (e.g., "Machine Learning Engineer").
        location: Location keywords to filter by (e.g., "Toronto", "Toronto area", "Remote Canada").
        company_name: Optional company name to filter the latest search results by.
        min_score: Minimum LLM relevance score from 1 to 10.
                   If not provided, uses config.yaml scoring.min_score.
        max_results: Maximum number of relevant jobs to return.

    Returns:
        Newly discovered jobs from the latest search that match the filters, including score and reason.
    """
    config = load_config()
    threshold = min_score or config["scoring"]["min_score"]
    seen_urls = _load_seen_urls(config["output"]["csv_file"])

    if not LAST_SEARCH_RESULTS:
        return (
            "No search results are available to filter yet. "
            "Call search_jobs first for a company, then call filter_jobs."
        )

    searched_jobs = LAST_SEARCH_RESULTS
    if company_name:
        searched_jobs = [
            job
            for job in searched_jobs
            if company_name.lower() in job.get("company", "").lower()
        ]

    new_jobs = [job for job in searched_jobs if job["url"] not in seen_urls]
    if not new_jobs:
        return "No newly discovered jobs found."

    candidate_jobs = []
    for job in new_jobs:
        searchable_role = f"{job.get('title', '')} {job.get('description', '')}"
        if not _matches_text(searchable_role, role):
            continue
        if not _matches_text(job.get("location", ""), location):
            continue
        candidate_jobs.append(job)

    if not candidate_jobs:
        return f"Found {len(new_jobs)} new jobs, but none matched the requested role/location filters."

    scorer = JobScorer(config)
    relevant_jobs = []
    for job in candidate_jobs:
        score_result = scorer.score(job)
        score = score_result.get("score", 0)
        reason = score_result.get("reason", "No reason provided")

        if score >= threshold:
            relevant_jobs.append(
                {
                    **job,
                    "score": score,
                    "reason": reason,
                }
            )

    if not relevant_jobs:
        return (
            f"Scored {len(candidate_jobs)} new candidate jobs, but none met "
            f"the minimum score of {threshold}/10."
        )

    relevant_jobs.sort(key=lambda job: job["score"], reverse=True)
    max_results = max(1, max_results)

    result = (
        f"Found {len(relevant_jobs)} relevant new jobs "
        f"with score >= {threshold}/10"
    )
    if len(relevant_jobs) > max_results:
        result += f" (showing top {max_results})"
    result += ":\n\n"

    for job in relevant_jobs[:max_results]:
        result += f"- {job['title']} at {job['company']} ({job['score']}/10)\n"
        result += f"  Location: {job['location']}\n"
        result += f"  Reason: {job['reason']}\n"
        result += f"  URL: {job['url']}\n\n"

    return result
