import csv
import os

from .models import JobResult, NotionJobEntry, ScoredJobResult


class AgentSession:
    def __init__(self) -> None:
        self.search_results: list[JobResult] = []
        self.filtered_jobs: list[ScoredJobResult] = []


session = AgentSession()


def json_output(model_obj) -> str:
    return model_obj.model_dump_json(indent=2)


def load_seen_urls(csv_file: str) -> set[str]:
    if not os.path.exists(csv_file):
        return set()

    with open(csv_file, "r", encoding="utf-8") as f:
        return {row["url"] for row in csv.DictReader(f) if row.get("url")}


def matches_job(job: JobResult, role: str, location: str) -> bool:
    if not role and not location:
        return True

    def all_terms_match(text: str, query: str) -> bool:
        terms = [term for term in query.lower().replace(",", " ").split() if term]
        return all(term in text.lower() for term in terms)

    if role:
        searchable_role = f"{job.title} {job.description or ''}"
        if not all_terms_match(searchable_role, role):
            return False

    if location:
        searchable_location = f"{job.location}"
        if not all_terms_match(searchable_location, location):
            return False

    return True


def notion_headers() -> dict:
    token = os.getenv("NOTION_API_KEY") or os.getenv("NOTION_TOKEN")
    if not token:
        raise ValueError("Missing NOTION_API_KEY or NOTION_TOKEN in .env")

    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Notion-Version": "2022-06-28",
    }


def build_notion_properties(entry: NotionJobEntry) -> dict:
    """Map a NotionJobEntry to the Applications database schema.

    Current DB columns: Company (title), Position (text), Link (url), Stage (status).
    Add more fields here when you extend the Notion database.
    """
    return {
        "Company": {
            "title": [{"text": {"content": entry.company[:2000]}}],
        },
        "Position": {
            "rich_text": [{"text": {"content": entry.title[:2000]}}],
        },
        "Link": {
            "url": str(entry.url) if entry.url else None,
        },
        "Stage": {
            "status": {"name": entry.stage},
        },
    }
