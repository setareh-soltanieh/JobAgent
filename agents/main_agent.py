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
    from .tools import filter_jobs, save_jobs_to_notion, search_jobs, list_companies
except ImportError:
    from agents.tools import filter_jobs, save_jobs_to_notion, search_jobs, list_companies

def main():
    load_dotenv()

    llm = ChatOllama(
        model="gemma4:e4b",
        temperature=0.7,
    )

    agent = create_agent(
        model=llm,
        tools=[search_jobs, filter_jobs, save_jobs_to_notion, list_companies],
        system_prompt=(
            "You are a job search assistant. Help with the user's current request without assuming "
            "extra steps. Use list_companies when the user asks what companies are configured. Use "
            "search_jobs when the user asks to find or search jobs at a specific company; pass the "
            "company, role, and location they mention as tool arguments. If the user asks to search "
            "but does not name a company, ask which configured company to search. Use filter_jobs only when the user asks to "
            "filter, refine, rank, score, or evaluate the jobs from the most recent search. Use "
            "save_jobs_to_notion only when the user explicitly asks to save, add, put, or send jobs "
            "to Notion; it can save either the latest filtered jobs or the latest search results."
        ),
    )

    messages = []
    print("Job agent ready. Type 'exit', 'quit', or 'q' to stop.")

    while True:
        user_prompt = input("\nYou: ").strip()
        if user_prompt.lower() in {"exit", "quit", "q"}:
            print("Goodbye.")
            break

        if not user_prompt:
            continue

        messages.append({"role": "user", "content": user_prompt})
        result = agent.invoke({"messages": messages})

        messages = result["messages"]
        print(f"\nAgent: {messages[-1].content}")


if __name__ == "__main__":
    main()
