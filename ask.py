"""
Local CLI for testing Price Gandalf without Slack.
Usage: python ask.py
"""

import os
from dotenv import load_dotenv

load_dotenv()

import google.auth
from google import genai
from google.genai import types

from slack_bot.schema_catalog import get_schema_prompt
from slack_bot.config import config

SYSTEM_PROMPT = (
    "You are Price Gandalf, an AI assistant for the Pricing Analytics team at Delivery Hero. "
    "You help pricing team stakeholders and analysts answer questions about pricing experiments, "
    "subscription metrics, and pricing data. "
    "You are knowledgeable about BigQuery, SQL, and the Pricing team's data assets.\n\n"
    + get_schema_prompt()
)

credentials, project = google.auth.default(
    scopes=["https://www.googleapis.com/auth/cloud-platform"]
)
_client = genai.Client(
    vertexai=True,
    project=config.google_cloud_project or project,
    location=config.vertex_ai_location,
    credentials=credentials,
)
_model = config.vertex_ai_model


def ask(question: str) -> str:
    response = _client.models.generate_content(
        model=_model,
        contents=question,
        config=types.GenerateContentConfig(
            system_instruction=SYSTEM_PROMPT,
            temperature=0.2,
            max_output_tokens=8192,
        ),
    )
    return response.text


if __name__ == "__main__":
    print("Price Gandalf — local CLI (type 'quit' to exit)\n")
    while True:
        try:
            question = input("You: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nBye!")
            break
        if not question:
            continue
        if question.lower() in ("quit", "exit", "q"):
            print("Bye!")
            break
        print("\nGandalf:", ask(question), "\n")
