from pathlib import Path
import os
import sys
from dotenv import load_dotenv

from langchain_ollama import ChatOllama
from langchain.agents import create_agent

PROJECT_ROOT = Path(__file__).resolve().parents[1]

if __package__ in {None, ""}:
    sys.path.insert(0, str(PROJECT_ROOT))

try:
    from .tools import filter_jobs, search_jobs, list_companies
except ImportError:
    from agents.tools import filter_jobs, search_jobs, list_companies

def main():
    load_dotenv()

    user_prompt = input("What would you like the job agent to do? ").strip()
    if not user_prompt:
        user_prompt = "What companies are configured for job searching?"

    llm = ChatOllama(
        model="gemma4:e4b",
        temperature=0.7,
    )

    agent = create_agent(
        model=llm,
        tools=[search_jobs, filter_jobs, list_companies],
        system_prompt=(
            "You are a job search assistant. You can list configured companies and search for jobs. "
            "When the user mentions a role, location, or company, pass those as specific arguments "
            "to the right tool. Use search_jobs first to collect jobs from a company. Then use "
            "filter_jobs to filter and score the jobs from the most recent search."
        ),
    )

    result = agent.invoke({
        "messages": [
            {"role": "user", "content": user_prompt}
        ]
    })

    print(result["messages"][-1].content)


if __name__ == "__main__":
    main()
