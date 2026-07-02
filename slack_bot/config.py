"""
Configuration loader and validator for the Slack bot.
"""

import os
from dotenv import load_dotenv

load_dotenv()


class Config:
    def __init__(self):
        self.slack_bot_token = self._get_required_env("SLACK_BOT_TOKEN")
        self.slack_app_token = self._get_required_env("SLACK_APP_TOKEN")

        self.google_credentials_path = self._get_env("GOOGLE_APPLICATION_CREDENTIALS", "")
        self.google_cloud_project = self._get_env("GOOGLE_CLOUD_PROJECT", "")
        self.vertex_ai_location = self._get_env("VERTEX_AI_LOCATION", "us-central1")
        self.vertex_ai_model = self._get_env("VERTEX_AI_MODEL", "gemini-2.5-flash")

        self.jira_url = self._get_env("JIRA_URL", "")
        # Confluence may be on a different domain — falls back to JIRA_URL if not set
        self.confluence_url = self._get_env("CONFLUENCE_URL", "") or self.jira_url
        self.jira_email = self._get_env("JIRA_EMAIL", "")
        self.jira_api_token = self._get_env("JIRA_API_TOKEN", "")
        self.jira_default_project = self._get_env("JIRA_DEFAULT_PROJECT", "CLOGBI")

        self.pricing_channel_id = self._get_env("PRICING_CHANNEL_ID", "")
        self.escalation_group = self._get_env("ESCALATION_GROUP", "")

        if self.google_credentials_path:
            value = self.google_credentials_path.strip()
            if not value.startswith("{") and not os.path.exists(value):
                print(f"⚠️  Warning: GOOGLE_APPLICATION_CREDENTIALS file not found at: {value}")

        self.feedback_users: frozenset = frozenset(
            uid.strip()
            for uid in self._get_env("FEEDBACK_USERS", "").split(",")
            if uid.strip()
        )

        self.jira_enabled = bool(self.jira_url and self.jira_email and self.jira_api_token)
        if self.jira_url or self.jira_email or self.jira_api_token:
            if not self.jira_enabled:
                print("⚠️  Warning: Incomplete Jira credentials. Need JIRA_URL, JIRA_EMAIL, and JIRA_API_TOKEN")
            else:
                print(f"✓ Jira integration enabled: {self.jira_url}")

    @staticmethod
    def _get_required_env(key: str) -> str:
        value = os.getenv(key)
        if not value:
            raise ValueError(f"Missing required environment variable: {key}")
        return value

    @staticmethod
    def _get_env(key: str, default: str) -> str:
        return os.getenv(key, default)


config = Config()
