"""
Gemini AI client via Google Vertex AI (google.genai).
"""

import json

from google import genai
from google.genai import types
from google.oauth2 import service_account

from slack_bot.config import config


class VertexAIClient:
    def __init__(self):
        try:
            credentials = self._load_credentials()
            self.client = genai.Client(
                vertexai=True,
                project=config.google_cloud_project,
                location=config.vertex_ai_location,
                credentials=credentials,
            )
            self.model = config.vertex_ai_model
            print(f"✓ Gemini initialized")
            print(f"  Model: {self.model}")
            print(f"  Project: {config.google_cloud_project}")
            print(f"  Location: {config.vertex_ai_location}")
        except Exception as e:
            print(f"⚠️  Failed to initialize Gemini: {e}")
            self.client = None

    @staticmethod
    def _load_credentials():
        creds = config.google_credentials_path
        if not creds:
            raise ValueError("GOOGLE_APPLICATION_CREDENTIALS not set")
        try:
            credentials_info = json.loads(creds)
        except (json.JSONDecodeError, TypeError):
            with open(creds) as f:
                credentials_info = json.load(f)
        return service_account.Credentials.from_service_account_info(
            credentials_info,
            scopes=["https://www.googleapis.com/auth/cloud-platform"],
        )

    def get_ai_response(
        self,
        prompt: str,
        max_tokens: int = 8192,
        use_slack_formatting: bool = True,
        system_instruction: str = "",
    ) -> str:
        if not self.client:
            return "⚠️ AI integration is not available. Please check Gemini configuration."

        if use_slack_formatting:
            slack_instructions = """

IMPORTANT: Format your response for Slack using these rules:
- Use *bold* for emphasis (single asterisk, not double **)
- Use _italic_ for secondary emphasis
- Use • for bullet points
- Use numbered lists: 1. 2. 3.
- Use `code` for inline code
- Use ```code block``` for multi-line code
- Do NOT use ## or ### headers — use *Section Name* instead"""
            prompt = prompt + slack_instructions

        try:
            response = self.client.models.generate_content(
                model=self.model,
                contents=prompt,
                config=types.GenerateContentConfig(
                    system_instruction=system_instruction or None,
                    temperature=0.2,
                    max_output_tokens=max_tokens,
                ),
            )

            usage = response.usage_metadata
            if usage:
                in_tok = usage.prompt_token_count or 0
                out_tok = usage.candidates_token_count or 0
                print(
                    f"💰 Gemini usage — "
                    f"in: {in_tok:,} tokens, out: {out_tok:,} tokens, "
                    f"total: {in_tok + out_tok:,} tokens"
                )

            return response.text

        except Exception as e:
            error_msg = str(e)
            print(f"❌ Error calling Gemini: {error_msg}")
            if "403" in error_msg or "permission" in error_msg.lower():
                return "⚠️ Permission denied. Please check your service account permissions."
            elif "404" in error_msg or "not found" in error_msg.lower():
                return "⚠️ Model not found. Please verify the model name in your configuration."
            elif "429" in error_msg or "quota" in error_msg.lower():
                return "⚠️ Rate limit hit. Please try again later."
            else:
                return f"⚠️ AI error: {error_msg[:100]}"


try:
    vertex_client = VertexAIClient()
except Exception as e:
    print(f"⚠️  Could not initialize Gemini client: {e}")
    vertex_client = None
