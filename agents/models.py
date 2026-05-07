from typing import Optional

from pydantic import BaseModel, Field, HttpUrl, field_validator


class JobResult(BaseModel):
    """A job returned by the search_jobs tool."""

    title: str
    company: str
    location: str = ""
    url: HttpUrl
    description: str = Field(default="", exclude=True)

    @classmethod
    def from_scraped_job(cls, job: dict) -> "JobResult":
        return cls(
            title=job.get("title", ""),
            company=job.get("company", ""),
            location=job.get("location", ""),
            url=job.get("url", ""),
            description=job.get("description", ""),
        )

    def to_job_dict(self) -> dict:
        return {
            "title": self.title,
            "company": self.company,
            "location": self.location,
            "url": str(self.url),
            "description": self.description,
        }


class ScoredJobResult(JobResult):
    """A job returned by the filter_jobs tool."""

    score: float
    reason: str

    @classmethod
    def from_job_result(
        cls,
        job: JobResult,
        score: float,
        reason: str,
    ) -> "ScoredJobResult":
        return cls(
            title=job.title,
            company=job.company,
            location=job.location,
            url=job.url,
            description=job.description,
            score=score,
            reason=reason,
        )


class NotionJobEntry(BaseModel):
    """A job entry to save in Notion."""

    title: str
    company: str
    location: str = ""
    url: HttpUrl
    stage: str = "To apply"
    score: Optional[float] = None
    reason: Optional[str] = None

    @field_validator("stage")
    @classmethod
    def validate_stage(cls, value: str) -> str:
        allowed_stages = {
            "No Answer",
            "To apply",
            "Applied",
            "Offer",
            "Rejected",
        }
        if value not in allowed_stages:
            raise ValueError(f"Stage must be one of {sorted(allowed_stages)}")
        return value

    @classmethod
    def from_job(cls, job: JobResult, stage: str = "To apply") -> "NotionJobEntry":
        score = job.score if isinstance(job, ScoredJobResult) else None
        reason = job.reason if isinstance(job, ScoredJobResult) else None
        return cls(
            title=job.title,
            company=job.company,
            location=job.location,
            url=job.url,
            stage=stage,
            score=score,
            reason=reason,
        )


class ToolOutput(BaseModel):
    """Base shape for tool responses."""

    message: str


class SearchJobsOutput(ToolOutput):
    total_found: int
    total_matching: int
    jobs: list[JobResult]


class FilterJobsOutput(ToolOutput):
    total_new_jobs: int
    total_candidates: int
    total_relevant: int
    min_score: float
    jobs: list[ScoredJobResult]


class ListCompaniesOutput(ToolOutput):
    companies: list[str]


class NotionSaveFailure(BaseModel):
    title: str
    status_code: int
    error: str


class SaveJobsToNotionOutput(ToolOutput):
    source: str
    saved_count: int
    saved: list[NotionJobEntry]
    failures: list[NotionSaveFailure] = []
