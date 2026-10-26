"""Hand-offs to the tools a CSM works in: Outlook (email, calendar), Teams and
Salesforce. Email, calendar and Teams links work as they are; the Salesforce
task is a preview of what an integration would create.
"""

from datetime import datetime, time, timedelta
from urllib.parse import quote, urlencode

TEAMS = "https://teams.microsoft.com/l"


def mailto(to, subject, body):
    return f"mailto:{','.join(to)}?subject={quote(subject)}&body={quote(body)}"


def teams_chat(users, message):
    return f"{TEAMS}/chat/0/0?" + urlencode({"users": ",".join(users), "message": message}, quote_via=quote)


def teams_meeting(subject, start, minutes, attendees, content):
    end = start + timedelta(minutes=minutes)
    params = {"subject": subject, "startTime": start.isoformat(), "endTime": end.isoformat(),
              "attendees": ",".join(attendees), "content": content}
    return f"{TEAMS}/meeting/new?" + urlencode(params, quote_via=quote)


def meeting_start(day, hour=10):
    return datetime.combine(day, time(hour, 0))


def ics(uid, subject, start, minutes, description, attendees, location=""):
    """Calendar invite (.ics) that Outlook opens as a new appointment."""
    end = start + timedelta(minutes=minutes)
    fmt = "%Y%m%dT%H%M%S"
    escape = lambda s: s.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")
    lines = [
        "BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//Nordic CS Radar//EN", "BEGIN:VEVENT",
        f"UID:{uid}@nordic-cs-radar", f"DTSTAMP:{datetime.now().strftime(fmt)}",
        f"DTSTART:{start.strftime(fmt)}", f"DTEND:{end.strftime(fmt)}",
        f"SUMMARY:{escape(subject)}", f"DESCRIPTION:{escape(description)}", f"LOCATION:{escape(location)}",
        *[f"ATTENDEE;ROLE=REQ-PARTICIPANT:mailto:{a}" for a in attendees],
        "END:VEVENT", "END:VCALENDAR",
    ]
    return "\r\n".join(lines) + "\r\n"


def salesforce_task(decision, account_name, reasons, crm_task_id):
    """The Salesforce Task an integration would create (field names as in the Salesforce API)."""
    return {
        "Id": crm_task_id or "(created on save)",
        "Subject": f"{decision['decision']}: {account_name}",
        "WhatId": f"Account: {account_name}",
        "ActivityDate": decision["due_on"],
        "Status": "Completed" if decision["status"] == "done" else "Not Started",
        "Priority": "High" if decision.get("severity") in ("critical", "high") else "Normal",
        "Type": decision["decision"],
        "Description": "\n".join([*reasons, "", decision.get("note") or ""]).strip(),
        "Source": "Nordic CS Radar",
    }
