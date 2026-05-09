import csv
import os
from urllib.parse import urlsplit, urlunsplit

import requests
from dotenv import load_dotenv

from config import load_config
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


def normalize_url(url: str) -> str:
    if not url:
        return ""

    parts = urlsplit(url.strip())
    path = parts.path.rstrip("/")
    return urlunsplit((parts.scheme, parts.netloc.lower(), path, "", ""))


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
    load_dotenv()
    token = os.getenv("NOTION_API_KEY") or os.getenv("NOTION_TOKEN")
    if not token:
        raise ValueError("Missing NOTION_API_KEY or NOTION_TOKEN in .env")

    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Notion-Version": "2022-06-28",
    }


def load_notion_job_urls() -> set[str]:
    load_dotenv()
    database_id = os.getenv("NOTION_DATABASE_ID")
    if not database_id:
        raise ValueError("Missing NOTION_DATABASE_ID in .env")

    config = load_config()
    link_property = (
        config.get("notion", {})
        .get("properties", {})
        .get("url", "Link")
    )

    known_urls = set()
    payload = {"page_size": 100}

    while True:
        response = requests.post(
            f"https://api.notion.com/v1/databases/{database_id}/query",
            headers=notion_headers(),
            json=payload,
            timeout=30,
        )
        response.raise_for_status()
        data = response.json()

        for page in data.get("results", []):
            url_value = (
                page.get("properties", {})
                .get(link_property, {})
                .get("url")
            )
            if url_value:
                known_urls.add(normalize_url(url_value))

        if not data.get("has_more"):
            break

        payload["start_cursor"] = data.get("next_cursor")

    return known_urls


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
