"""Composio-backed service catalog with required configuration fields.

This is the single source of truth for:
- Which services KotoFlow supports
- Which actions map to which service
- What user-provided config each service needs before a workflow can run
"""

from __future__ import annotations

# ─── Service config requirements ────────────────────────────────────────────
# Each key is the canonical service name.
# "required_fields" lists what the orchestrator MUST collect from the user.
# "actions" lists the workflow actions that belong to this service.

SERVICE_CATALOG: dict[str, dict] = {
    # ── Email ────────────────────────────────────────────────────────────────
    "Gmail": {
        "required_fields": {
            "recipient_email": "Recipient email address",
        },
        "optional_fields": {
            "sender_email": "Sender email (if different from default)",
        },
        "actions": ["send_email", "list_emails"],
    },
    "Outlook": {
        "required_fields": {
            "recipient_email": "Recipient email address",
        },
        "optional_fields": {
            "sender_email": "Sender email (if different from default)",
        },
        "actions": ["send_email", "list_emails"],
    },
    # ── Messaging ────────────────────────────────────────────────────────────
    "Slack": {
        "required_fields": {
            "channel": "Slack channel name (e.g. #general)",
        },
        "optional_fields": {
            "workspace": "Slack workspace name",
        },
        "actions": ["send_slack_message", "slack_notify"],
    },
    "Discord": {
        "required_fields": {
            "channel": "Discord channel name",
            "server": "Discord server name",
        },
        "optional_fields": {},
        "actions": ["discord_message"],
    },
    "Teams": {
        "required_fields": {
            "channel": "Teams channel name",
            "team": "Team name",
        },
        "optional_fields": {},
        "actions": ["send_message"],
    },
    "Telegram": {
        "required_fields": {
            "chat_id": "Telegram chat/group ID or @username",
        },
        "optional_fields": {},
        "actions": ["send_message"],
    },
    "WhatsApp": {
        "required_fields": {
            "phone_number": "Recipient phone number with country code",
        },
        "optional_fields": {},
        "actions": ["send_message"],
    },
    # ── Calendar ─────────────────────────────────────────────────────────────
    "Google Calendar": {
        "required_fields": {
            "calendar_email": "Google Calendar email / calendar ID",
            "event_title": "Event title",
        },
        "optional_fields": {
            "event_description": "Event description",
            "attendees": "Comma-separated attendee emails",
        },
        "actions": ["create_calendar_event", "schedule_task"],
    },
    "Outlook Calendar": {
        "required_fields": {
            "calendar_email": "Outlook Calendar email",
            "event_title": "Event title",
        },
        "optional_fields": {},
        "actions": ["create_calendar_event", "schedule_task"],
    },
    # ── Project Management ───────────────────────────────────────────────────
    "Notion": {
        "required_fields": {
            "page_or_database_url": "Notion page or database URL",
        },
        "optional_fields": {},
        "actions": ["create_task", "write_document", "fetch_data"],
    },
    "Trello": {
        "required_fields": {
            "board_name": "Trello board name",
            "list_name": "Trello list name",
        },
        "optional_fields": {},
        "actions": ["create_task"],
    },
    "Asana": {
        "required_fields": {
            "project_name": "Asana project name",
        },
        "optional_fields": {
            "section_name": "Section within the project",
        },
        "actions": ["create_task"],
    },
    "ClickUp": {
        "required_fields": {
            "space_name": "ClickUp space name",
            "list_name": "ClickUp list name",
        },
        "optional_fields": {},
        "actions": ["create_task"],
    },
    "Linear": {
        "required_fields": {
            "team_key": "Linear team key (e.g. ENG)",
        },
        "optional_fields": {
            "project_name": "Linear project name",
        },
        "actions": ["create_task"],
    },
    "Jira": {
        "required_fields": {
            "project_key": "Jira project key (e.g. PROJ)",
            "domain": "Jira domain (e.g. mycompany.atlassian.net)",
        },
        "optional_fields": {
            "issue_type": "Issue type (Task, Bug, Story, etc.)",
        },
        "actions": ["create_task"],
    },
    # ── Code / DevOps ────────────────────────────────────────────────────────
    "GitHub": {
        "required_fields": {
            "repo": "Repository (owner/repo format)",
        },
        "optional_fields": {
            "branch": "Branch name",
        },
        "actions": ["create_task", "fetch_data", "deploy_service", "monitor_system"],
    },
    "GitLab": {
        "required_fields": {
            "repo": "Repository path (group/project)",
        },
        "optional_fields": {
            "branch": "Branch name",
        },
        "actions": ["create_task", "fetch_data", "deploy_service"],
    },
    # ── Spreadsheets / Data ──────────────────────────────────────────────────
    "Google Sheets": {
        "required_fields": {
            "spreadsheet_url": "Google Sheets URL or spreadsheet ID",
        },
        "optional_fields": {
            "sheet_name": "Specific sheet/tab name",
        },
        "actions": ["fetch_data", "transform_data", "aggregate_data", "write_document"],
    },
    "Airtable": {
        "required_fields": {
            "base_id": "Airtable base ID or URL",
            "table_name": "Table name",
        },
        "optional_fields": {},
        "actions": ["fetch_data", "create_task", "transform_data"],
    },
    # ── CRM ──────────────────────────────────────────────────────────────────
    "Salesforce": {
        "required_fields": {
            "instance_url": "Salesforce instance URL",
            "object_type": "Object type (Lead, Contact, Account, etc.)",
        },
        "optional_fields": {},
        "actions": ["fetch_data", "create_task", "query_database"],
    },
    "HubSpot": {
        "required_fields": {
            "object_type": "Object type (contact, deal, company, etc.)",
        },
        "optional_fields": {},
        "actions": ["fetch_data", "create_task", "query_database"],
    },
    # ── Social Media ─────────────────────────────────────────────────────────
    "Twitter": {
        "required_fields": {},
        "optional_fields": {
            "tweet_content_hint": "General topic or content direction",
        },
        "actions": ["post_social", "fetch_data"],
    },
    "LinkedIn": {
        "required_fields": {},
        "optional_fields": {
            "post_visibility": "Visibility (public, connections)",
        },
        "actions": ["post_social"],
    },
    "Facebook": {
        "required_fields": {
            "page_name": "Facebook page name (for page posts)",
        },
        "optional_fields": {},
        "actions": ["post_social"],
    },
    # ── Cloud Storage ────────────────────────────────────────────────────────
    "Dropbox": {
        "required_fields": {
            "folder_path": "Dropbox folder path",
        },
        "optional_fields": {},
        "actions": ["fetch_data", "write_document"],
    },
    "Google Drive": {
        "required_fields": {
            "folder_url": "Google Drive folder URL or ID",
        },
        "optional_fields": {},
        "actions": ["fetch_data", "write_document"],
    },
    "OneDrive": {
        "required_fields": {
            "folder_path": "OneDrive folder path",
        },
        "optional_fields": {},
        "actions": ["fetch_data", "write_document"],
    },
    "Box": {
        "required_fields": {
            "folder_id": "Box folder ID",
        },
        "optional_fields": {},
        "actions": ["fetch_data", "write_document"],
    },
    # ── Payments ─────────────────────────────────────────────────────────────
    "Stripe": {
        "required_fields": {},
        "optional_fields": {
            "customer_email": "Customer email for filtering",
        },
        "actions": ["fetch_data", "query_database"],
    },
    # ── Support ──────────────────────────────────────────────────────────────
    "Zendesk": {
        "required_fields": {
            "subdomain": "Zendesk subdomain (e.g. mycompany)",
        },
        "optional_fields": {},
        "actions": ["create_task", "fetch_data"],
    },
    "Intercom": {
        "required_fields": {},
        "optional_fields": {},
        "actions": ["send_message", "fetch_data"],
    },
    # ── Video / Meetings ─────────────────────────────────────────────────────
    "Zoom": {
        "required_fields": {
            "meeting_topic": "Meeting topic / title",
        },
        "optional_fields": {
            "attendee_emails": "Comma-separated attendee emails",
        },
        "actions": ["create_calendar_event", "schedule_task"],
    },
    "Google Meet": {
        "required_fields": {
            "meeting_topic": "Meeting topic / title",
        },
        "optional_fields": {
            "attendee_emails": "Comma-separated attendee emails",
        },
        "actions": ["create_calendar_event", "schedule_task"],
    },
    # ── E-Commerce ───────────────────────────────────────────────────────────
    "Shopify": {
        "required_fields": {
            "store_url": "Shopify store URL",
        },
        "optional_fields": {},
        "actions": ["fetch_data", "query_database"],
    },
    # ── Automation / Integration Hubs ────────────────────────────────────────
    "Zapier": {
        "required_fields": {
            "webhook_url": "Zapier webhook URL",
        },
        "optional_fields": {},
        "actions": ["api_call"],
    },
}

# ── Derived constants ────────────────────────────────────────────────────────

SUPPORTED_SERVICES: frozenset[str] = frozenset(SERVICE_CATALOG.keys())

# Collect every action referenced across all services
_all_service_actions: set[str] = set()
for _svc in SERVICE_CATALOG.values():
    _all_service_actions.update(_svc["actions"])

COMPOSIO_ACTIONS: frozenset[str] = frozenset(_all_service_actions)


def get_required_fields_for_services(services: list[str]) -> dict[str, dict[str, str]]:
    """Return {service: {field: description}} for the given service names."""
    result: dict[str, dict[str, str]] = {}
    for svc in services:
        entry = SERVICE_CATALOG.get(svc)
        if entry and entry["required_fields"]:
            result[svc] = entry["required_fields"]
    return result


def build_service_config_prompt_section() -> str:
    """Build a prompt section listing every service and its required fields."""
    lines: list[str] = []
    for svc, entry in SERVICE_CATALOG.items():
        req = entry["required_fields"]
        opt = entry.get("optional_fields", {})
        if not req and not opt:
            continue
        fields_parts: list[str] = []
        for field, desc in req.items():
            fields_parts.append(f"  - {field} (required): {desc}")
        for field, desc in opt.items():
            fields_parts.append(f"  - {field} (optional): {desc}")
        lines.append(f"**{svc}**:\n" + "\n".join(fields_parts))
    return "\n".join(lines)
