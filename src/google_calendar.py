import os
import time
from typing import Any, Dict, List, Optional

from google.oauth2.credentials import Credentials
from google.auth.exceptions import RefreshError
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError


SCOPES = ["https://www.googleapis.com/auth/calendar"]


def build_service():
    refresh_token = os.environ.get("GOOGLE_REFRESH_TOKEN")
    client_id = os.environ.get("GOOGLE_CLIENT_ID")
    client_secret = os.environ.get("GOOGLE_CLIENT_SECRET")
    
    if not refresh_token or not client_id or not client_secret:
        raise ValueError(
            "Missing required environment variables: GOOGLE_REFRESH_TOKEN, "
            "GOOGLE_CLIENT_ID, and GOOGLE_CLIENT_SECRET must be set"
        )
    
    creds = Credentials(
        None,
        refresh_token=refresh_token,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=client_id,
        client_secret=client_secret,
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
        except RefreshError as e:
            # Provide helpful error message for expired refresh tokens
            error_msg = str(e)
            if "invalid_grant" in error_msg or "expired" in error_msg.lower() or "revoked" in error_msg.lower():
                raise RefreshError(
                    f"Refresh token has expired or been revoked. Please generate a new refresh token using:\n"
                    f"python3 scripts/get_google_refresh_token.py\n\n"
                    f"Original error: {error_msg}"
                ) from e
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
    reminders: Optional[Any] = None,
    send_updates: Optional[str] = None,
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
    # Reminders: accept dict with useDefault/overrides, a list of overrides, or a boolean
    if reminders is not None:
        rem_payload: Dict[str, Any] = {}
        if isinstance(reminders, bool):
            rem_payload["useDefault"] = reminders
        elif isinstance(reminders, list):
            cleaned: List[Dict[str, Any]] = []
            for o in reminders:
                if isinstance(o, dict):
                    method = str(o.get("method", "")).lower()
                    minutes = o.get("minutes")
                    if method in ("email", "popup") and isinstance(minutes, (int, float)):
                        cleaned.append({"method": method, "minutes": int(minutes)})
            rem_payload["useDefault"] = False
            if cleaned:
                rem_payload["overrides"] = cleaned
        elif isinstance(reminders, dict):
            # Only pass through the supported keys after light validation
            if "useDefault" in reminders:
                rem_payload["useDefault"] = bool(reminders.get("useDefault"))
            overrides = reminders.get("overrides")
            if isinstance(overrides, list):
                cleaned: List[Dict[str, Any]] = []
                for o in overrides:
                    if isinstance(o, dict):
                        method = str(o.get("method", "")).lower()
                        minutes = o.get("minutes")
                        if method in ("email", "popup") and isinstance(minutes, (int, float)):
                            cleaned.append({"method": method, "minutes": int(minutes)})
                if cleaned:
                    rem_payload["overrides"] = cleaned
                    # If overrides provided but useDefault not explicitly set, force useDefault False
                    if "useDefault" not in rem_payload:
                        rem_payload["useDefault"] = False
        if rem_payload:
            body["reminders"] = rem_payload

    # Prepare insert with optional sendUpdates for attendee notifications
    insert_kwargs: Dict[str, Any] = {"calendarId": calendar_id, "body": body}
    if isinstance(send_updates, str) and send_updates in ("all", "externalOnly", "none"):
        insert_kwargs["sendUpdates"] = send_updates

    ev = _retry(service.events().insert(**insert_kwargs).execute)
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


