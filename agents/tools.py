import csv
import os
from datetime import date

import requests

from langchain.tools import tool
from config import load_config
from scraper import JobScraper
from scorer import JobScorer
from .models import (
    FilterJobsOutput,
    JobResult,
    ListCompaniesOutput,
    NotionJobEntry,
    NotionSaveFailure,
    SaveJobsToNotionOutput,
    ScoredJobResult,
    SearchJobsOutput,
)


LAST_SEARCH_RESULTS: list[JobResult] = []
LAST_FILTERED_JOBS: list[ScoredJobResult] = []


def _json(model_obj):
    return model_obj.model_dump_json(indent=2)


def _load_seen_urls(csv_file: str) -> set[str]:
    if not os.path.exists(csv_file):
        return set()
    with open(csv_file, "r", encoding="utf-8") as f:
        return {row["url"] for row in csv.DictReader(f) if row.get("url")}


def _matches_job(job: JobResult, role: str, location: str) -> bool:
    if not role and not location:
        return True
    searchable = f"{job.title} {job.description}".lower()
    terms = [t for t in role.lower().replace(",", " ").split() if t]
    return all(t in searchable for t in terms)


def _notion_headers() -> dict:
    token = os.getenv("NOTION_API_KEY") or os.getenv("NOTION_TOKEN")
    if not token:
        raise ValueError("Missing NOTION_API_KEY or NOTION_TOKEN in .env")
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Notion-Version": "2022-06-28",
    }


_NOTION_BUILDERS = {
    "title": lambda v: {"title": [{"text": {"content": v[:2000]}}]},
    "rich_text": lambda v: {"rich_text": [{"text": {"content": v[:2000]}}]} if v else {"rich_text": []},
    "url": lambda v: {"url": v or None},
    "number": lambda v: {"number": v},
    "date": lambda v: {"date": {"start": v}},
    "select": lambda v: {"select": {"name": v}} if v else {"select": None},
    "status": lambda v: {"status": {"name": v}} if v else {"status": None},
}


def _build_notion_properties(
    entry: NotionJobEntry,
    properties_config: dict,
    title_property: str,
) -> dict:
    page_title = entry.company if title_property.lower() == "company" else f"{entry.title} - {entry.company}"
    properties = {title_property: _NOTION_BUILDERS["title"](page_title)}

    fields = [
        ("company", "rich_text", entry.company),
        ("role", "rich_text", entry.title),
        ("location", "rich_text", entry.location),
        ("url", "url", str(entry.url)),
        ("score", "number", entry.score or 0),
        ("reason", "rich_text", entry.reason or ""),
        ("status", "status", entry.stage),
        ("date", "date", date.today().isoformat()),
    ]
    for key, builder_name, value in fields:
        prop_name = properties_config.get(key)
        if prop_name:
            properties[prop_name] = _NOTION_BUILDERS[builder_name](value)

    return properties


def _search_output(
    message: str,
    total_found: int = 0,
    total_matching: int = 0,
    jobs: list[JobResult] = None,
) -> str:
    return _json(SearchJobsOutput(message=message, total_found=total_found, total_matching=total_matching, jobs=jobs or []))


def _filter_output(
    message: str,
    total_new_jobs: int = 0,
    total_candidates: int = 0,
    total_relevant: int = 0,
    min_score: float = 0,
    jobs: list[ScoredJobResult] = None,
) -> str:
    return _json(
        FilterJobsOutput(
            message=message,
            total_new_jobs=total_new_jobs,
            total_candidates=total_candidates,
            total_relevant=total_relevant,
            min_score=min_score,
            jobs=jobs or [],
        )
    )


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
            return _search_output(f"No company found matching '{company_name}'.", 0, 0, [])

    if not companies:
        return _search_output("No companies configured in config.yaml", 0, 0, [])

    if role:
        config["scraping"]["search_text"] = role

    all_jobs: list[JobResult] = []
    for company_config in companies:
        scraper = JobScraper(config, company_config)
        all_jobs.extend(JobResult.from_scraped_job(job) for job in scraper.scrape_all())

    if not all_jobs:
        LAST_SEARCH_RESULTS = []
        return _search_output("No jobs found.", 0, 0, [])

    LAST_SEARCH_RESULTS = all_jobs
    matching_jobs = [job for job in all_jobs if _matches_job(job, role, location)]

    if not matching_jobs:
        filters = [f"company matching '{company_name}'"] if company_name else []
        if role:
            filters.append(f"role matching '{role}'")
        if location:
            filters.append(f"location matching '{location}'")
        text = ", ".join(filters) if filters else "the requested filters"
        return _search_output(f"No jobs found for {text}.", len(all_jobs), 0, [])

    max_results = max(1, max_results)
    msg = f"Found {len(matching_jobs)} matching jobs"
    if len(matching_jobs) > max_results:
        msg += f" (showing first {max_results})"

    return _search_output(msg, len(all_jobs), len(matching_jobs), matching_jobs[:max_results])


@tool
def list_companies() -> str:
    """List all companies configured for job scraping.

    Returns:
        A list of configured company names.
    """
    config = load_config()
    companies = config.get("companies", [])
    if not companies:
        return _json(ListCompaniesOutput(message="No companies configured.", companies=[]))
    names = [c["name"] for c in companies]
    return _json(ListCompaniesOutput(message=f"Configured companies ({len(names)}).", companies=names))


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
    global LAST_FILTERED_JOBS

    config = load_config()
    threshold = min_score or config["scoring"]["min_score"]
    seen_urls = _load_seen_urls(config["output"]["csv_file"])

    if not LAST_SEARCH_RESULTS:
        return _filter_output(
            "No search results are available to filter yet. Call search_jobs first for a company, then filter_jobs.",
            0, 0, 0, threshold, [],
        )

    searched_jobs = LAST_SEARCH_RESULTS
    if company_name:
        searched_jobs = [j for j in searched_jobs if company_name.lower() in j.company.lower()]

    new_jobs = [j for j in searched_jobs if str(j.url) not in seen_urls]
    if not new_jobs:
        return _filter_output("No newly discovered jobs found.", 0, 0, 0, threshold, [])

    candidate_jobs = [j for j in new_jobs if _matches_job(j, role, location)]
    if not candidate_jobs:
        return _filter_output(
            f"Found {len(new_jobs)} new jobs, but none matched the requested role/location filters.",
            len(new_jobs), 0, 0, threshold, [],
        )

    scorer = JobScorer(config)
    relevant_jobs: list[ScoredJobResult] = []
    for job in candidate_jobs:
        sr = scorer.score(job.to_job_dict())
        score = sr.get("score", 0)
        if score >= threshold:
            relevant_jobs.append(ScoredJobResult.from_job_result(job, score, sr.get("reason", "")))

    if not relevant_jobs:
        LAST_FILTERED_JOBS = []
        return _filter_output(
            f"Scored {len(candidate_jobs)} new candidate jobs, but none met the minimum score of {threshold}/10.",
            len(new_jobs), len(candidate_jobs), 0, threshold, [],
        )

    relevant_jobs.sort(key=lambda j: j.score, reverse=True)
    LAST_FILTERED_JOBS = relevant_jobs
    max_results = max(1, max_results)

    msg = f"Found {len(relevant_jobs)} relevant new jobs with score >= {threshold}/10"
    if len(relevant_jobs) > max_results:
        msg += f" (showing top {max_results})"

    return _filter_output(
        msg, len(new_jobs), len(candidate_jobs), len(relevant_jobs), threshold, relevant_jobs[:max_results],
    )


@tool
def save_jobs_to_notion(max_results: int = 10, status: str = "To apply") -> str:
    """Save the latest filtered jobs, or latest search results, to a Notion database.

    Args:
        max_results: Maximum number of jobs to save.
        status: Status/select value to write if your Notion database has a status property.

    Returns:
        A summary of the jobs saved to Notion.
    """
    jobs_to_save = LAST_FILTERED_JOBS or LAST_SEARCH_RESULTS
    source = "filtered jobs" if LAST_FILTERED_JOBS else "latest search results"

    if not jobs_to_save:
        return _json(
            SaveJobsToNotionOutput(
                message="No jobs are available to save. Call search_jobs first, then save_jobs_to_notion.",
                source=source, saved_count=0, saved=[], failures=[],
            )
        )

    database_id = os.getenv("NOTION_DATABASE_ID")
    if not database_id:
        return _json(
            SaveJobsToNotionOutput(
                message="Missing NOTION_DATABASE_ID in .env.",
                source=source, saved_count=0, saved=[], failures=[],
            )
        )

    config = load_config()
    notion_config = config.get("notion", {})
    properties_config = notion_config.get("properties", {})
    title_property = properties_config.get("title", "Position")

    saved: list[NotionJobEntry] = []
    failed: list[NotionSaveFailure] = []
    headers = _notion_headers()

    for job in jobs_to_save[: max(1, max_results)]:
        entry = NotionJobEntry.from_job(job, stage=status)
        properties = _build_notion_properties(entry, properties_config, title_property)
        payload = {"parent": {"database_id": database_id}, "properties": properties}

        resp = requests.post("https://api.notion.com/v1/pages", headers=headers, json=payload, timeout=30)
        if resp.ok:
            saved.append(entry)
        else:
            job_title = entry.company if title_property.lower() == "company" else f"{entry.title} - {entry.company}"
            failed.append(NotionSaveFailure(title=job_title, status_code=resp.status_code, error=resp.text[:200]))

    msg = f"Saved {len(saved)} jobs from {source} to Notion."
    if failed:
        msg += f" Failed to save {len(failed)} jobs."

    return _json(SaveJobsToNotionOutput(message=msg, source=source, saved_count=len(saved), saved=saved, failures=failed))
