"""
Jira Cloud integration client for the Slack bot.
"""

import json
from typing import Dict, List, Optional, Any
from atlassian import Jira
from slack_bot.config import config


class JiraClient:
    def __init__(self):
        self.enabled = config.jira_enabled
        self.jira = None
        self.default_project = config.jira_default_project

        if self.enabled:
            try:
                self.jira = Jira(
                    url=config.jira_url,
                    username=config.jira_email,
                    password=config.jira_api_token,
                    cloud=True
                )
                self.jira.myself()
                print("✓ Jira client initialized successfully")
            except Exception as e:
                print(f"⚠️  Failed to initialize Jira client: {str(e)}")
                self.enabled = False
                self.jira = None

    def is_enabled(self) -> bool:
        return self.enabled and self.jira is not None

    def search_issues(self, jql_query: str, max_results: int = 10) -> Dict[str, Any]:
        if not self.is_enabled():
            return {"success": False, "error": "Jira integration is not configured."}

        try:
            results = self.jira.jql(jql_query, limit=max_results)
            if not results or results.get("total", 0) == 0:
                return {"success": True, "count": 0, "message": "No issues found.", "issues": []}

            issues = [self._format_issue_summary(i) for i in results.get("issues", [])]
            return {"success": True, "count": results.get("total", 0), "issues": issues}

        except Exception as e:
            return {"success": False, "error": f"Search failed: {str(e)}"}

    def get_issue(self, issue_key: str) -> Dict[str, Any]:
        if not self.is_enabled():
            return {"success": False, "error": "Jira integration is not configured."}

        try:
            issue = self.jira.issue(issue_key)
            if not issue:
                return {"success": False, "error": f"Issue {issue_key} not found."}
            return {"success": True, "issue": self._format_issue_detail(issue)}
        except Exception as e:
            error_msg = str(e)
            if "404" in error_msg or "does not exist" in error_msg.lower():
                return {"success": False, "error": f"Issue {issue_key} not found."}
            return {"success": False, "error": f"Failed to get issue: {error_msg}"}

    def create_issue(
        self,
        summary: str,
        project: Optional[str] = None,
        issue_type: str = "Task",
        description: Optional[str] = None,
        priority: Optional[str] = None,
        assignee: Optional[str] = None,
    ) -> Dict[str, Any]:
        if not self.is_enabled():
            return {"success": False, "error": "Jira integration is not configured."}

        project = project or self.default_project
        if not project:
            return {"success": False, "error": "No project specified."}

        try:
            fields: Dict[str, Any] = {
                "project": {"key": project},
                "summary": summary,
                "issuetype": {"name": issue_type},
            }
            if description:
                fields["description"] = description
            if priority:
                fields["priority"] = {"name": priority}
            if assignee:
                fields["assignee"] = {"name": assignee}

            new_issue = self.jira.create_issue(fields=fields)
            issue_key = new_issue.get("key")
            return {
                "success": True,
                "issue_key": issue_key,
                "issue_url": f"{config.jira_url}/browse/{issue_key}",
            }
        except Exception as e:
            return {"success": False, "error": f"Failed to create issue: {str(e)}"}

    def _format_issue_summary(self, issue: Dict) -> Dict[str, str]:
        fields = issue.get("fields", {})
        key = issue.get("key", "")
        return {
            "key": key,
            "url": f"{config.jira_url}/browse/{key}",
            "summary": fields.get("summary", "No summary"),
            "status": fields.get("status", {}).get("name", "Unknown"),
            "type": fields.get("issuetype", {}).get("name", "Unknown"),
            "priority": fields.get("priority", {}).get("name", "None"),
            "assignee": self._get_name(fields.get("assignee"), "Unassigned"),
        }

    def _format_issue_detail(self, issue: Dict) -> Dict[str, Any]:
        fields = issue.get("fields", {})
        key = issue.get("key", "")
        return {
            "key": key,
            "url": f"{config.jira_url}/browse/{key}",
            "summary": fields.get("summary", "No summary"),
            "description": fields.get("description", "No description"),
            "status": fields.get("status", {}).get("name", "Unknown"),
            "type": fields.get("issuetype", {}).get("name", "Unknown"),
            "priority": fields.get("priority", {}).get("name", "None"),
            "assignee": self._get_name(fields.get("assignee"), "Unassigned"),
            "reporter": self._get_name(fields.get("reporter"), "Unknown"),
            "created": fields.get("created", "Unknown"),
            "updated": fields.get("updated", "Unknown"),
            "labels": fields.get("labels", []),
        }

    @staticmethod
    def _get_name(person: Optional[Dict], default: str) -> str:
        if not person:
            return default
        return person.get("displayName", person.get("name", default))

    def format_search_results(self, result: Dict[str, Any]) -> str:
        if not result.get("success"):
            return f"❌ {result.get('error', 'Unknown error')}"
        if result.get("count", 0) == 0:
            return "🔍 No issues found matching your criteria."

        issues = result.get("issues", [])
        count = result.get("count", 0)
        lines = [f"🔍 *Found {count} issue(s):*\n"]
        for issue in issues[:10]:
            lines.append(
                f"• *<{issue['url']}|{issue['key']}>* - {issue['summary']}\n"
                f"  Status: {issue['status']} | Type: {issue['type']} | Assignee: {issue['assignee']}"
            )
        if count > 10:
            lines.append(f"\n_...and {count - 10} more_")
        return "\n".join(lines)

    def format_issue_detail(self, result: Dict[str, Any]) -> str:
        if not result.get("success"):
            return f"❌ {result.get('error', 'Unknown error')}"
        issue = result.get("issue", {})
        description = issue.get("description", "No description")
        if len(description) > 500:
            description = description[:500] + "..."
        labels = ", ".join(issue.get("labels", [])) or "None"
        return "\n".join([
            f"📋 *<{issue['url']}|{issue['key']}>*\n",
            f"*Summary:* {issue['summary']}",
            f"*Status:* {issue['status']}",
            f"*Type:* {issue['type']}",
            f"*Priority:* {issue['priority']}",
            f"*Assignee:* {issue['assignee']}",
            f"*Reporter:* {issue['reporter']}",
            f"*Labels:* {labels}",
            f"*Created:* {issue['created']}",
            f"*Updated:* {issue['updated']}",
            f"\n*Description:*\n{description}",
        ])

    def format_create_result(self, result: Dict[str, Any]) -> str:
        if not result.get("success"):
            return f"❌ {result.get('error', 'Unknown error')}"
        return f"✅ *Issue created:* <{result['issue_url']}|{result['issue_key']}>"


jira_client = JiraClient()
