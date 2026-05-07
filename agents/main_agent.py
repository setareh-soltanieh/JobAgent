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
    from .tools import search_jobs, list_companies
except ImportError:
    from agents.tools import search_jobs, list_companies

def main():
    load_dotenv()

    llm = ChatOllama(
        model="gemma4:e4b",
        temperature=0.7,
    )

    agent = create_agent(
        model=llm,
        tools=[search_jobs, list_companies],
        system_prompt="You are a job search assistant. You can search for jobs at companies and list configured companies.",
    )

    result = agent.invoke({
        "messages": [
            {"role": "user", "content": "What companies are configured for job searching?"}
        ]
    })

    print(result["messages"][-1].content)


if __name__ == "__main__":
    main()
