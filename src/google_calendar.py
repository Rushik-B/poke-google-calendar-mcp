import os
import time
from typing import Any, Dict, List, Optional

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError


SCOPES = ["https://www.googleapis.com/auth/calendar"]


def build_service():
    creds = Credentials(
        None,
        refresh_token=os.environ["GOOGLE_REFRESH_TOKEN"],
        token_uri="https://oauth2.googleapis.com/token",
        client_id=os.environ["GOOGLE_CLIENT_ID"],
        client_secret=os.environ["GOOGLE_CLIENT_SECRET"],
        scopes=SCOPES,
    )
    return build("calendar", "v3", credentials=creds, cache_discovery=False)


def _retry(fn, *args, **kwargs):
    backoff = 1.0
    for attempt in range(5):
        try:
            return fn(*args, **kwargs)
        except HttpError as e:
            status = getattr(e, "status_code", None) or getattr(e, "resp", {}).get("status")
            if status and int(status) in (429, 500, 502, 503, 504):
                time.sleep(backoff)
                backoff = min(backoff * 2, 8)
                continue
            raise
        except Exception:
            # Non-HttpError, do not retry to avoid masking bugs
            raise


def list_calendars(service=None) -> List[Dict[str, Any]]:
    service = service or build_service()
    calendars: List[Dict[str, Any]] = []
    page_token: Optional[str] = None
    while True:
        resp = _retry(service.calendarList().list(pageToken=page_token).execute)
        for item in resp.get("items", []):
            calendars.append(
                {
                    "id": item.get("id"),
                    "summary": item.get("summary"),
                    "primary": bool(item.get("primary")),
                    "accessRole": item.get("accessRole"),
                    "timeZone": item.get("timeZone"),
                }
            )
        page_token = resp.get("nextPageToken")
        if not page_token:
            break
    return calendars


def resolve_calendar_id(query: Optional[str], service=None) -> str:
    service = service or build_service()
    if not query:
        return "primary"
    # Accept direct ID
    try:
        # Quick probe: get calendar by id
        _retry(service.calendars().get(calendarId=query).execute)
        return query
    except Exception:
        pass

    qnorm = (query or "").strip().lower()
    for cal in list_calendars(service):
        if cal["id"].lower() == qnorm:
            return cal["id"]
        if (cal.get("summary") or "").strip().lower() == qnorm:
            return cal["id"]
    # fallback to primary
    return "primary"


def list_events(
    calendar: Optional[str] = None,
    time_min: Optional[str] = None,
    time_max: Optional[str] = None,
    max_results: Optional[int] = 50,
    query: Optional[str] = None,
    include_all_calendars: bool = False,
    service=None,
) -> List[Dict[str, Any]]:
    service = service or build_service()

    def pull(calendar_id: str) -> List[Dict[str, Any]]:
        params: Dict[str, Any] = {
            "calendarId": calendar_id,
            "singleEvents": True,
            "orderBy": "startTime",
            "maxResults": max(1, min(int(max_results or 50), 500)),
        }
        if time_min:
            params["timeMin"] = time_min
        if time_max:
            params["timeMax"] = time_max
        if query:
            params["q"] = query

        resp = _retry(service.events().list(**params).execute)
        events: List[Dict[str, Any]] = []
        for ev in resp.get("items", []):
            start = ev.get("start", {})
            end = ev.get("end", {})
            events.append(
                {
                    "calendarId": calendar_id,
                    "eventId": ev.get("id"),
                    "summary": ev.get("summary"),
                    "description": ev.get("description"),
                    "start": start.get("dateTime") or start.get("date"),
                    "end": end.get("dateTime") or end.get("date"),
                    "timeZone": start.get("timeZone") or end.get("timeZone"),
                    "location": ev.get("location"),
                    "attendees": [a.get("email") for a in ev.get("attendees", []) if a.get("email")],
                    "status": ev.get("status"),
                }
            )
        return events

    if include_all_calendars or not calendar:
        events: List[Dict[str, Any]] = []
        for cal in list_calendars(service):
            events.extend(pull(cal["id"]))
        return events
    else:
        calendar_id = resolve_calendar_id(calendar, service)
        return pull(calendar_id)


def create_event(
    calendar: str,
    summary: str,
    start: str,
    end: str,
    time_zone: Optional[str] = None,
    description: Optional[str] = None,
    location: Optional[str] = None,
    attendees: Optional[List[str]] = None,
    service=None,
) -> Dict[str, Any]:
    service = service or build_service()
    calendar_id = resolve_calendar_id(calendar, service)

    def time_obj(value: str) -> Dict[str, Any]:
        if "T" in value:
            return {"dateTime": value, **({"timeZone": time_zone} if time_zone else {})}
        return {"date": value}

    body: Dict[str, Any] = {
        "summary": summary,
        "start": time_obj(start),
        "end": time_obj(end),
    }
    if description:
        body["description"] = description
    if location:
        body["location"] = location
    if attendees:
        body["attendees"] = [{"email": e} for e in attendees]

    ev = _retry(service.events().insert(calendarId=calendar_id, body=body).execute)
    return {
        "ok": True,
        "event": {
            "calendarId": calendar_id,
            "eventId": ev.get("id"),
            "summary": ev.get("summary"),
            "description": ev.get("description"),
            "start": ev.get("start", {}).get("dateTime") or ev.get("start", {}).get("date"),
            "end": ev.get("end", {}).get("dateTime") or ev.get("end", {}).get("date"),
            "timeZone": ev.get("start", {}).get("timeZone") or ev.get("end", {}).get("timeZone"),
            "location": ev.get("location"),
            "attendees": [a.get("email") for a in ev.get("attendees", []) if a.get("email")],
            "status": ev.get("status"),
        },
    }


def update_event(
    calendar: str,
    event_id: str,
    patch: Dict[str, Any],
    service=None,
) -> Dict[str, Any]:
    service = service or build_service()
    calendar_id = resolve_calendar_id(calendar, service)

    # Map friendly fields to Google structure
    body: Dict[str, Any] = {}
    if "summary" in patch:
        body["summary"] = patch["summary"]
    if "description" in patch:
        body["description"] = patch["description"]
    if "location" in patch:
        body["location"] = patch["location"]
    tz = patch.get("time_zone") or patch.get("timeZone")
    if "start" in patch:
        start_val = patch["start"]
        body["start"] = {"dateTime": start_val, **({"timeZone": tz} if tz else {})} if "T" in start_val else {"date": start_val}
    if "end" in patch:
        end_val = patch["end"]
        body["end"] = {"dateTime": end_val, **({"timeZone": tz} if tz else {})} if "T" in end_val else {"date": end_val}
    if "attendees" in patch and isinstance(patch["attendees"], list):
        body["attendees"] = [{"email": e} for e in patch["attendees"] if isinstance(e, str)]

    ev = _retry(service.events().patch(calendarId=calendar_id, eventId=event_id, body=body).execute)
    return {
        "ok": True,
        "event": {
            "calendarId": calendar_id,
            "eventId": ev.get("id"),
            "summary": ev.get("summary"),
            "description": ev.get("description"),
            "start": ev.get("start", {}).get("dateTime") or ev.get("start", {}).get("date"),
            "end": ev.get("end", {}).get("dateTime") or ev.get("end", {}).get("date"),
            "timeZone": ev.get("start", {}).get("timeZone") or ev.get("end", {}).get("timeZone"),
            "location": ev.get("location"),
            "attendees": [a.get("email") for a in ev.get("attendees", []) if a.get("email")],
            "status": ev.get("status"),
        },
    }


def delete_event(calendar: str, event_id: str, service=None) -> Dict[str, Any]:
    service = service or build_service()
    calendar_id = resolve_calendar_id(calendar, service)
    _retry(service.events().delete(calendarId=calendar_id, eventId=event_id).execute)
    return {"ok": True}


