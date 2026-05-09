import os

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
from .tool_helpers import (
    build_notion_properties,
    json_output,
    load_seen_urls,
    load_notion_job_urls,
    matches_job,
    normalize_url,
    notion_headers,
    session,
)

@tool
def search_jobs(
    company_name: str = "",
    role: str = "",
    location: str = "",
    max_results: int = 50,
) -> str:
    """Search for jobs at one configured company using user-provided criteria.

    Args:
        company_name: Name of the company to search (e.g., "Autodesk", "TD Bank").
        role: Job title or role keywords (e.g., "Machine Learning Engineer").
        location: Location keywords (e.g., "Toronto", "Toronto area", "Remote Canada").
        max_results: Maximum number of matching jobs to return.

    Returns:
        JSON with matching jobs for the requested company, role, and location.
    """
    config = load_config()
    companies = config.get("companies", [])

    if not company_name:
        return json_output(SearchJobsOutput(
            message="Please provide a company name to search.",
            total_found=0, total_matching=0, jobs=[],
        ))

    company_config = next(
        (c for c in companies if company_name.lower() in c["name"].lower()),
        None,
    )
    if not company_config:
        available = [c["name"] for c in companies]
        return json_output(SearchJobsOutput(
            message=f"No company found matching '{company_name}'. Available: {available}",
            total_found=0, total_matching=0, jobs=[],
        ))

    search_text = " ".join(part for part in [role, location] if part).strip()
    scraping_config = config.get("scraping", {})

    search_config = {
        "scraping": {
            "limit_per_page": scraping_config.get("limit_per_page", 20),
            "rate_limit_delay": scraping_config.get("rate_limit_delay", 0),
            "search_text": search_text,
        },
        "cache": config.get(
            "cache",
            {"enabled": True, "cache_file": "jobs_cache.json"},
        ),
    }

    all_jobs: list[JobResult] = []
    try:
        scraper = JobScraper(search_config, company_config)
        all_jobs.extend(JobResult.from_scraped_job(job) for job in scraper.scrape_all())
    except Exception as e:
        session.search_results = []
        session.filtered_jobs = []
        return json_output(SearchJobsOutput(
            message=f"Failed to search {company_config['name']}: {e}",
            total_found=0, total_matching=0, jobs=[],
        ))

    if not all_jobs:
        session.search_results = []
        session.filtered_jobs = []
        return json_output(SearchJobsOutput(
            message="No jobs found.",
            total_found=0, total_matching=0, jobs=[],
        ))
 
    matching_jobs = [job for job in all_jobs if matches_job(job, role, location)]

    if not matching_jobs:
        session.search_results = []
        session.filtered_jobs = []
        filters = []
        if company_name:
            filters.append(f"company matching '{company_name}'")
        if role:
            filters.append(f"role matching '{role}'")
        if location:
            filters.append(f"location matching '{location}'")
        text = ", ".join(filters) if filters else "the requested filters"
        return json_output(SearchJobsOutput(
            message=f"No jobs found for {text}.",
            total_found=len(all_jobs), total_matching=0, jobs=[],
        ))

    try:
        notion_urls = load_notion_job_urls()
    except Exception as e:
        session.search_results = []
        session.filtered_jobs = []
        return json_output(SearchJobsOutput(
            message=f"Found matching jobs, but failed to check Notion first: {e}",
            total_found=len(all_jobs),
            total_matching=len(matching_jobs),
            jobs=[],
        ))

    available_jobs = [
        job for job in matching_jobs if normalize_url(str(job.url)) not in notion_urls
    ]
    already_in_notion = len(matching_jobs) - len(available_jobs)
    session.search_results = available_jobs
    session.filtered_jobs = []

    if not available_jobs:
        return json_output(SearchJobsOutput(
            message=(
                f"Found {len(matching_jobs)} matching jobs, but all of them are "
                "already in Notion."
            ),
            total_found=len(all_jobs),
            total_matching=0,
            jobs=[],
        ))

    max_results = max(1, max_results)
    msg = f"Found {len(available_jobs)} available jobs"
    if already_in_notion:
        msg += f" ({already_in_notion} matching jobs already in Notion)"
    if len(available_jobs) > max_results:
        msg += f" (showing first {max_results})"
 
    return json_output(SearchJobsOutput(
        message=msg,
        total_found=len(all_jobs),
        total_matching=len(available_jobs),
        jobs=available_jobs[:max_results],
    ))


@tool
def list_companies() -> str:
    """List all companies configured for job scraping.
 
    Returns:
        JSON with a list of configured company names.
    """
    config = load_config()
    companies = config.get("companies", [])
 
    if not companies:
        return json_output(ListCompaniesOutput(message="No companies configured.", companies=[]))
 
    names = [c["name"] for c in companies]
    return json_output(ListCompaniesOutput(
        message=f"Configured companies ({len(names)}).",
        companies=names,
    ))


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
        location: Location keywords to filter by (e.g., "Toronto", "Remote Canada").
        company_name: Optional company name to filter the latest search results by.
        min_score: Minimum LLM relevance score from 1 to 10.
                   If not provided, uses config.yaml scoring.min_score.
        max_results: Maximum number of relevant jobs to return.
 
    Returns:
        JSON with newly discovered jobs that match the filters, including score and reason.
    """
    config = load_config()
    threshold = min_score or config["scoring"]["min_score"]
    seen_urls = load_seen_urls(config["output"]["csv_file"])
 
    if not session.search_results:
        return json_output(FilterJobsOutput(
            message="No search results available. Call search_jobs first, then filter_jobs.",
            total_new_jobs=0, total_candidates=0, total_relevant=0, min_score=threshold, jobs=[],
        ))
 
    searched_jobs = session.search_results
    if company_name:
        searched_jobs = [j for j in searched_jobs if company_name.lower() in j.company.lower()]
 
    new_jobs = [j for j in searched_jobs if str(j.url) not in seen_urls]
    if not new_jobs:
        return json_output(FilterJobsOutput(
            message="No newly discovered jobs found.",
            total_new_jobs=0, total_candidates=0, total_relevant=0, min_score=threshold, jobs=[],
        ))
 
    candidate_jobs = [j for j in new_jobs if matches_job(j, role, location)]
    if not candidate_jobs:
        return json_output(FilterJobsOutput(
            message=f"Found {len(new_jobs)} new jobs, but none matched the requested role/location filters.",
            total_new_jobs=len(new_jobs), total_candidates=0, total_relevant=0, min_score=threshold, jobs=[],
        ))
 
    scorer = JobScorer(config)
    relevant_jobs: list[ScoredJobResult] = []
    for job in candidate_jobs:
        sr = scorer.score(job.to_job_dict())
        score = sr.get("score", 0)
        if score >= threshold:
            relevant_jobs.append(ScoredJobResult.from_job_result(job, score, sr.get("reason", "")))
 
    if not relevant_jobs:
        session.filtered_jobs = []
        return json_output(FilterJobsOutput(
            message=f"Scored {len(candidate_jobs)} new candidate jobs, but none met the minimum score of {threshold}/10.",
            total_new_jobs=len(new_jobs), total_candidates=len(candidate_jobs),
            total_relevant=0, min_score=threshold, jobs=[],
        ))
 
    relevant_jobs.sort(key=lambda j: j.score, reverse=True)
    session.filtered_jobs = relevant_jobs
    max_results = max(1, max_results)
 
    msg = f"Found {len(relevant_jobs)} relevant new jobs with score >= {threshold}/10"
    if len(relevant_jobs) > max_results:
        msg += f" (showing top {max_results})"
 
    return json_output(FilterJobsOutput(
        message=msg,
        total_new_jobs=len(new_jobs),
        total_candidates=len(candidate_jobs),
        total_relevant=len(relevant_jobs),
        min_score=threshold,
        jobs=relevant_jobs[:max_results],
    ))
 


@tool
def save_jobs_to_notion(max_results: int = 10, status: str = "To apply") -> str:
    """Save the latest filtered jobs (or search results) to the Notion Applications database.
 
    Args:
        max_results: Maximum number of jobs to save.
        status: Stage value to set. Must be one of: "To apply", "Applied",
                "Offer", "Rejected", "No Answer".
 
    Returns:
        JSON summary of saved and failed jobs.
    """
    jobs_to_save = session.filtered_jobs or session.search_results
    source = "filtered jobs" if session.filtered_jobs else "latest search results"
 
    if not jobs_to_save:
        return json_output(SaveJobsToNotionOutput(
            message="No jobs available to save. Call search_jobs first, then save_jobs_to_notion.",
            source=source, saved_count=0, saved=[], failures=[],
        ))
 
    database_id = os.getenv("NOTION_DATABASE_ID")
    if not database_id:
        return json_output(SaveJobsToNotionOutput(
            message="Missing NOTION_DATABASE_ID in .env.",
            source=source, saved_count=0, saved=[], failures=[],
        ))
 
    try:
        headers = notion_headers()
    except ValueError as e:
        return json_output(SaveJobsToNotionOutput(
            message=str(e),
            source=source, saved_count=0, saved=[], failures=[],
        ))
 
    saved: list[NotionJobEntry] = []
    failures: list[NotionSaveFailure] = []
 
    for job in jobs_to_save[:max(1, max_results)]:
        entry = NotionJobEntry.from_job(job, stage=status)
        payload = {
            "parent": {"database_id": database_id},
            "properties": build_notion_properties(entry),
        }
 
        resp = requests.post(
            "https://api.notion.com/v1/pages",
            headers=headers,
            json=payload,
            timeout=30,
        )
 
        if resp.ok:
            saved.append(entry)
        else:
            failures.append(NotionSaveFailure(
                title=f"{entry.title} - {entry.company}",
                status_code=resp.status_code,
                error=resp.text[:200],
            ))
 
    msg = f"Saved {len(saved)} jobs from {source} to Notion."
    if failures:
        msg += f" Failed to save {len(failures)} jobs."
 
    return json_output(SaveJobsToNotionOutput(
        message=msg,
        source=source,
        saved_count=len(saved),
        saved=saved,
        failures=failures,
    ))
