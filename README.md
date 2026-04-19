# Job Search Agent

Personal job search automation agent that scrapes job listings and uses AI (LLM) to score and filter relevant positions.

## Features

- Scrapes job postings from company career sites (Workday API)
- Uses local LLM (Ollama) to score job relevance
- Caches job descriptions to avoid redundant requests
- Filters jobs based on configurable criteria
- Deduplicates against previously seen jobs

## Requirements

- Python 3.13+
- [Ollama](https://ollama.ai/) with `gemma4:e4b` model

## Setup

```bash
# Install dependencies
uv sync

# Pull required LLM model
ollama pull gemma4:e4b
```

## Configuration

Copy `.env.example` to `.env` and customize:

```bash
cp .env.example .env
```

Edit `config.yaml` to adjust:
- Target company/tenant
- Scoring threshold
- Rate limiting
- Cache settings

## Usage

```bash
# Default run
uv run python main.py

# Custom criteria
uv run python main.py -c "Data Scientist roles in Vancouver"

# Search for specific jobs (bypasses API limit)
uv run python main.py --search "machine learning"

# Search + custom criteria
uv run python main.py --search "data scientist" -c "ML roles in Toronto"

# Higher relevance threshold
uv run python main.py -s 8

# Debug logging
uv run python main.py --debug
```

## Output

Relevant jobs are saved to `jobs.csv` with:
- Date discovered
- Job title, company, location
- Direct link to posting
- Relevance score (1-10)
- Reasoning from LLM

## Project Structure

```
├── main.py         # Entry point, CLI, logging
├── config.py       # Config loader
├── config.yaml     # Settings
├── scraper.py      # Job scraping + caching
├── scorer.py       # LLM scoring
├── network.py      # HTTP helpers + retry
└── .env.example    # Environment template
```
