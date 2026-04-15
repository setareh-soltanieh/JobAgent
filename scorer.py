import json
import logging
from ollama import chat

from config import get_criteria

logger = logging.getLogger(__name__)


class JobScorer:
    def __init__(self, config: dict):
        self.model = config["scoring"]["model"]
        self.min_score = config["scoring"]["min_score"]
        self.criteria = get_criteria()

    def build_prompt(self, job: dict) -> str:
        return f"""You are a job filter.

My background and interests:
{self.criteria}

Rate this job from 1 to 10 based on:
- How closely the role relates to ML, Deep Learning, or GenAI (most important)
- Location: must be Toronto or remote (score 1-2 if elsewhere in Canada)
- Score 8-10 only if the job is clearly an ML/AI role in Toronto or remote
- Score 1-3 if the job has nothing to do with AI/ML or is outside Toronto

Job: {job["title"]} at {job["company"]}
Location: {job["location"]}
Description: {job["description"]}

Respond ONLY as valid JSON, no extra text: {{"score": 7, "reason": "..."}}"""

    def score(self, job: dict) -> dict:
        prompt = self.build_prompt(job)

        try:
            response = chat(
                model=self.model,
                messages=[
                    {
                        "role": "system",
                        "content": "You are a job filter. Respond only in valid JSON.",
                    },
                    {"role": "user", "content": prompt},
                ],
            )
        except Exception as e:
            logger.error(f"LLM request failed for '{job['title']}': {e}")
            return {"score": 0, "reason": f"LLM error: {str(e)}"}

        raw = response["message"]["content"].strip()
        logger.debug(f"LLM raw response for '{job['title']}': {raw[:200]}")

        if "```" in raw:
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
            raw = raw.strip()

        start = raw.find("{")
        end = raw.rfind("}") + 1
        if start == -1 or end == 0:
            logger.warning(f"Could not find JSON in response: {raw[:200]}")
            return {"score": 0, "reason": "Could not parse model response"}

        try:
            return json.loads(raw[start:end])
        except json.JSONDecodeError as e:
            logger.warning(f"JSON decode error: {e}")
            return {"score": 0, "reason": f"JSON parse error: {str(e)}"}

    def is_relevant(self, job: dict) -> bool:
        result = self.score(job)
        return result.get("score", 0) >= self.min_score
