from langchain.tools import tool
from config import load_config
from scraper import JobScraper


@tool
def search_jobs(company_name: str = "") -> str:
    """Search for job postings from company career sites.

    Args:
        company_name: Name of the company to search (e.g., "Autodesk").
                     If not provided, searches all configured companies.

    Returns:
        A list of found jobs with titles, companies, locations, and URLs.
    """
    config = load_config()
    companies = config.get("companies", [])

    if company_name:
        companies = [c for c in companies if company_name.lower() in c["name"].lower()]
        if not companies:
            available = [c["name"] for c in config.get("companies", [])]
            return f"No company found matching '{company_name}'. Available: {available}"

    if not companies:
        return "No companies configured in config.yaml"

    all_jobs = []
    for company_config in companies[:1]:
        scraper = JobScraper(config, company_config)
        jobs = scraper.scrape_all()
        all_jobs.extend(jobs)

    if not all_jobs:
        return "No jobs found."

    result = f"Found {len(all_jobs)} jobs:\n\n"
    for job in all_jobs[:5]:
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
