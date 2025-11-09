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
    end: Optional[str] = None,
    time_zone: Optional[str] = None,
    description: Optional[str] = None,
    location: Optional[str] = None,
    reminders: Optional[Any] = None,
    recurrence: Optional[List[str]] = None,
    all_day: bool = False,
    service=None,
) -> Dict[str, Any]:
    service = service or build_service()
    calendar_id = resolve_calendar_id(calendar, service)

    def _extract_date(value: str) -> str:
        # Accept YYYY-MM-DD or full ISO 8601; always return YYYY-MM-DD
        if "T" in value:
            return value.split("T", 1)[0]
        return value

    def time_payloads(start_value: str, end_value: Optional[str]) -> (Dict[str, Any], Dict[str, Any]):
        if all_day:
            from datetime import datetime, timedelta
            start_date = _extract_date(start_value)
            start_dt = datetime.fromisoformat(start_date)
            if end_value:
                end_date_raw = _extract_date(end_value)
                try:
                    end_dt = datetime.fromisoformat(end_date_raw)
                except Exception:
                    end_dt = start_dt
            else:
                end_dt = start_dt
            # Ensure end is strictly after start; if not, use next day (exclusive end)
            if end_dt <= start_dt:
                end_dt = start_dt + timedelta(days=1)
            return {"date": start_dt.date().isoformat()}, {"date": end_dt.date().isoformat()}
        else:
            if not end_value:
                raise ValueError("end is required unless creating an all-day event (all_day=true).")
            start_obj: Dict[str, Any] = {"dateTime": start_value}
            end_obj: Dict[str, Any] = {"dateTime": end_value}
            if time_zone:
                start_obj["timeZone"] = time_zone
                end_obj["timeZone"] = time_zone
            return start_obj, end_obj

    start_payload, end_payload = time_payloads(start, end)
    body: Dict[str, Any] = {"summary": summary, "start": start_payload, "end": end_payload}
    if description:
        body["description"] = description
    if location:
        body["location"] = location
    if recurrence:
        # Expecting a list of RFC 5545 RRULE/EXDATE strings, e.g. ["RRULE:FREQ=WEEKLY;COUNT=5"]
        cleaned_rules: List[str] = []
        for rule in recurrence:
            if isinstance(rule, str) and rule.strip():
                cleaned_rules.append(rule.strip())
        if cleaned_rules:
            body["recurrence"] = cleaned_rules
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
    if "recurrence" in patch and isinstance(patch.get("recurrence"), list):
        cleaned_rules: List[str] = []
        for rule in patch.get("recurrence") or []:
            if isinstance(rule, str) and rule.strip():
                cleaned_rules.append(rule.strip())
        if cleaned_rules:
            body["recurrence"] = cleaned_rules
    tz = patch.get("time_zone") or patch.get("timeZone")
    if "start" in patch:
        start_val = patch["start"]
        body["start"] = {"dateTime": start_val, **({"timeZone": tz} if tz else {})} if "T" in start_val else {"date": start_val}
    if "end" in patch:
        end_val = patch["end"]
        body["end"] = {"dateTime": end_val, **({"timeZone": tz} if tz else {})} if "T" in end_val else {"date": end_val}

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
            "status": ev.get("status"),
        },
    }


def delete_event(calendar: str, event_id: str, as_instance: bool = False, service=None) -> Dict[str, Any]:
    service = service or build_service()
    calendar_id = resolve_calendar_id(calendar, service)
    if as_instance:
        # Cancel a single occurrence by marking the instance as cancelled
        inst = _retry(service.events().get(calendarId=calendar_id, eventId=event_id).execute)
        inst["status"] = "cancelled"
        _retry(service.events().update(calendarId=calendar_id, eventId=event_id, body=inst).execute)
    else:
        _retry(service.events().delete(calendarId=calendar_id, eventId=event_id).execute)
    return {"ok": True}

def list_recurring_instances(
    calendar: str,
    recurring_event_id: str,
    time_min: Optional[str] = None,
    time_max: Optional[str] = None,
    max_results: Optional[int] = 50,
    service=None,
) -> Dict[str, Any]:
    service = service or build_service()
    calendar_id = resolve_calendar_id(calendar, service)
    params: Dict[str, Any] = {
        "calendarId": calendar_id,
        "eventId": recurring_event_id,
        "maxResults": max(1, min(int(max_results or 50), 500)),
    }
    if time_min:
        params["timeMin"] = time_min
    if time_max:
        params["timeMax"] = time_max
    resp = _retry(service.events().instances(**params).execute)
    instances: List[Dict[str, Any]] = []
    for inst in resp.get("items", []):
        start = inst.get("start", {})
        end = inst.get("end", {})
        ost = inst.get("originalStartTime", {}) or {}
        instances.append(
            {
                "calendarId": calendar_id,
                "instanceId": inst.get("id"),
                "recurringEventId": inst.get("recurringEventId"),
                "originalStartTime": ost.get("dateTime") or ost.get("date"),
                "start": start.get("dateTime") or start.get("date"),
                "end": end.get("dateTime") or end.get("date"),
                "status": inst.get("status"),
                "summary": inst.get("summary"),
                "location": inst.get("location"),
            }
        )
    return {"ok": True, "instances": instances}


def cancel_recurring_instance(
    calendar: str,
    recurring_event_id: Optional[str] = None,
    instance_id: Optional[str] = None,
    original_start_time: Optional[str] = None,
    service=None,
) -> Dict[str, Any]:
    service = service or build_service()
    calendar_id = resolve_calendar_id(calendar, service)
    instance: Optional[Dict[str, Any]] = None

    if instance_id:
        instance = _retry(service.events().get(calendarId=calendar_id, eventId=instance_id).execute)
        # If provided, validate it belongs to the recurring series
        if recurring_event_id and instance.get("recurringEventId") != recurring_event_id:
            raise ValueError("Provided instance_id does not belong to the specified recurring_event_id.")
    else:
        if not (recurring_event_id and original_start_time):
            raise ValueError("Provide either instance_id, or both recurring_event_id and original_start_time.")
        # Lookup via instances and match by originalStartTime value
        resp = _retry(
            service.events()
            .instances(calendarId=calendar_id, eventId=recurring_event_id, maxResults=250)
            .execute
        )
        data = resp
        for inst in data.get("items", []):
            ost = inst.get("originalStartTime", {}) or {}
            ost_val = ost.get("dateTime") or ost.get("date")
            if ost_val == original_start_time:
                instance = inst
                break
        if not instance:
            raise ValueError("Could not find instance matching original_start_time.")

    instance["status"] = "cancelled"
    updated = _retry(service.events().update(calendarId=calendar_id, eventId=instance["id"], body=instance).execute)
    return {
        "ok": True,
        "instance": {
            "instanceId": updated.get("id"),
            "recurringEventId": updated.get("recurringEventId"),
            "status": updated.get("status"),
            "updated": updated.get("updated"),
        },
    }


def update_following_instances(
    calendar: str,
    recurring_event_id: str,
    target_instance_start: str,
    change_patch: Dict[str, Any],
    new_recurrence: List[str],
    service=None,
) -> Dict[str, Any]:
    """
    Split a recurring series at a target instance:
    1) Trim the original series by setting UNTIL to just before target_instance_start
    2) Create a new recurring series starting at target_instance_start with provided changes and new_recurrence

    Notes:
    - Only supports dateTime (not all-day date) instances for simplicity.
    - Caller must supply new_recurrence rules for the new series.
    """
    from datetime import datetime, timedelta, timezone

    service = service or build_service()
    calendar_id = resolve_calendar_id(calendar, service)

    # Fetch original recurring event
    original = _retry(service.events().get(calendarId=calendar_id, eventId=recurring_event_id).execute)
    start_obj = original.get("start", {})
    end_obj = original.get("end", {})
    if not (start_obj.get("dateTime") and end_obj.get("dateTime")):
        raise ValueError("update_following_instances only supports events with dateTime (not all-day).")

    # Compute duration
    def _parse_iso(dt_str: str) -> datetime:
        # Support 'Z' and offset formats
        if dt_str.endswith("Z"):
            dt_str = dt_str.replace("Z", "+00:00")
        return datetime.fromisoformat(dt_str)

    original_start_dt = _parse_iso(start_obj["dateTime"])
    original_end_dt = _parse_iso(end_obj["dateTime"])
    duration = original_end_dt - original_start_dt

    # Compute UNTIL just before the target start in UTC
    tgt_dt = _parse_iso(target_instance_start)
    tgt_utc = tgt_dt.astimezone(timezone.utc) - timedelta(seconds=1)
    until_str = tgt_utc.strftime("%Y%m%dT%H%M%SZ")

    # Prepare trimmed recurrence for the original event: adjust the first RRULE line
    rec: List[str] = original.get("recurrence") or []
    if not rec:
        raise ValueError("Event is not a recurring series.")
    new_rec: List[str] = []
    rrule_applied = False
    for line in rec:
        if isinstance(line, str) and line.upper().startswith("RRULE:"):
            rule = line[len("RRULE:") :].strip()
            parts = [p for p in rule.split(";") if p]
            parts = [p for p in parts if not p.upper().startswith("UNTIL=") and not p.upper().startswith("COUNT=")]
            parts.append(f"UNTIL={until_str}")
            new_rec.append("RRULE:" + ";".join(parts))
            rrule_applied = True
        else:
            new_rec.append(line)
    if not rrule_applied:
        raise ValueError("Could not find RRULE in original recurrence.")

    # Apply trim to original series
    trimmed_body = {"recurrence": new_rec}
    _retry(
        service.events()
        .update(calendarId=calendar_id, eventId=recurring_event_id, body={**original, **trimmed_body})
        .execute
    )

    # Create the new series starting at target_instance_start
    new_start_dt = tgt_dt
    new_end_dt = new_start_dt + duration
    start_payload = {"dateTime": new_start_dt.isoformat()}
    end_payload = {"dateTime": new_end_dt.isoformat()}
    if start_obj.get("timeZone"):
        start_payload["timeZone"] = start_obj.get("timeZone")
    if end_obj.get("timeZone"):
        end_payload["timeZone"] = end_obj.get("timeZone")

    new_body: Dict[str, Any] = {
        "summary": change_patch.get("summary", original.get("summary")),
        "description": change_patch.get("description", original.get("description")),
        "location": change_patch.get("location", original.get("location")),
        "start": start_payload,
        "end": end_payload,
        "recurrence": new_recurrence,
    }

    created = _retry(service.events().insert(calendarId=calendar_id, body=new_body).execute)
    return {
        "ok": True,
        "newRecurringEvent": {
            "calendarId": calendar_id,
            "eventId": created.get("id"),
            "summary": created.get("summary"),
            "start": created.get("start", {}).get("dateTime"),
            "end": created.get("end", {}).get("dateTime"),
            "recurrence": created.get("recurrence"),
        },
    }

