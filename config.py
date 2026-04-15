import os
import yaml
from pathlib import Path


def load_config() -> dict:
    config_path = Path(__file__).parent / "config.yaml"
    with open(config_path) as f:
        return yaml.safe_load(f)


def get_criteria() -> str:
    criteria = os.getenv("JOB_SEARCH_CRITERIA")
    if criteria:
        return criteria
    return "Machine Learning Engineer roles in Toronto area with a focus on deep learning, GenAI and NLP. Salary above $120k is preferred, but not required. I value opportunities for growth, interesting projects, and a positive company culture."
