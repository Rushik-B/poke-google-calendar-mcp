#!/usr/bin/env python3
import os
from typing import Any, Dict, List, Optional, Union, Literal

from dotenv import load_dotenv
from fastmcp import FastMCP
from googleapiclient.errors import HttpError

# Load environment variables from .env file
load_dotenv()

try:
    from google_calendar import (
        list_calendars as gc_list_calendars,
        list_events as gc_list_events,
        create_event as gc_create_event,
        update_event as gc_update_event,
        delete_event as gc_delete_event,
        resolve_calendar_id as gc_resolve_calendar_id,
    )
except ModuleNotFoundError:
    # Fallback when the working directory is the repo root and imports require the package prefix
    from src.google_calendar import (
        list_calendars as gc_list_calendars,
        list_events as gc_list_events,
        create_event as gc_create_event,
        update_event as gc_update_event,
        delete_event as gc_delete_event,
        resolve_calendar_id as gc_resolve_calendar_id,
    )


mcp = FastMCP("Poke Google Calendar MCP")


def _error_response(exc: Exception) -> Dict[str, Any]:
    message = str(exc)
    if isinstance(exc, HttpError):
        try:
            message = exc.error_details[0]["message"] if getattr(exc, "error_details", None) else str(exc)
        except Exception:
            message = str(exc)
    return {"ok": False, "error": {"type": exc.__class__.__name__, "message": message}}


def _normalize_attendees(value: Any) -> Optional[List[str]]:
    """Accept list[str], comma-separated string, empty object, or {emails:[...]}."""
    if value is None:
        return None
    if isinstance(value, list):
        return [str(x).strip() for x in value if isinstance(x, str) and str(x).strip()]
    if isinstance(value, str):
        parts = [p.strip() for p in value.split(",")]
        return [p for p in parts if p]
    if isinstance(value, dict):
        # Treat empty object {} as no attendees
        if not value:
            return None
        for key in ("emails", "attendees"):
            if key in value and isinstance(value[key], list):
                return [
                    str(x).strip() for x in value[key] if isinstance(x, str) and str(x).strip()
                ]
        return None
    return None


def _normalize_reminder_minutes(value: Any) -> Optional[List[int]]:
    """Accept list[int|float|str] or comma-separated string like "1h, 30m, 90" (minutes).
    Returns a sorted, deduplicated list of non-negative minute integers.
    """
    if value is None:
        return None
    raw_items: List[Any] = []
    if isinstance(value, list):
        raw_items = value
    elif isinstance(value, str):
        raw_items = [part.strip() for part in value.split(",") if part.strip()]
    else:
        return None

    minutes: List[int] = []
    for item in raw_items:
        if isinstance(item, (int, float)):
            m = int(item)
            if m >= 0:
                minutes.append(m)
            continue
        if isinstance(item, str):
            s = item.strip().lower().replace(" ", "")
            # Normalize units
            s = (
                s.replace("hours", "h")
                .replace("hour", "h")
                .replace("mins", "m")
                .replace("minute", "m")
                .replace("minutes", "m")
                .replace("min", "m")
            )
            try:
                if s.endswith("h"):
                    val = float(s[:-1])
                    m = int(val * 60)
                    if m >= 0:
                        minutes.append(m)
                elif s.endswith("m"):
                    val = float(s[:-1])
                    m = int(val)
                    if m >= 0:
                        minutes.append(m)
                else:
                    # Bare number implies minutes
                    val = float(s)
                    m = int(val)
                    if m >= 0:
                        minutes.append(m)
            except Exception:
                # Skip unparseable entries
                continue

    # Deduplicate and sort
    dedup_sorted = sorted({m for m in minutes})
    return dedup_sorted


@mcp.tool(description="List all calendars accessible to the user")
def list_calendars() -> Dict[str, Any]:
    try:
        calendars = gc_list_calendars()
        return {"calendars": calendars}
    except Exception as e:
        return _error_response(e)


@mcp.tool(
    description=(
        "List events from a specific calendar or across all calendars. Times are ISO 8601. "
        "Set include_all_calendars=true to aggregate."
    )
)
def list_events(
    calendar: Optional[str] = None,
    time_min: Optional[str] = None,
    time_max: Optional[str] = None,
    max_results: Optional[int] = 50,
    query: Optional[str] = None,
    include_all_calendars: bool = False,
) -> Dict[str, Any]:
    try:
        events = gc_list_events(
            calendar=calendar,
            time_min=time_min,
            time_max=time_max,
            max_results=max_results,
            query=query,
            include_all_calendars=include_all_calendars,
        )
        return {"events": events}
    except Exception as e:
        return _error_response(e)


@mcp.tool(
    description=(
        "Create a calendar event. Start/end are ISO 8601 or all-day date (YYYY-MM-DD). "
        "Attendees may be a list of emails, a comma-separated string, an empty object, or an object with an 'emails' array. "
        "To set reminders, pass 'reminder_minutes' as an array (or comma-separated string) of minutes before start, e.g. [120, 60] or '2h, 60m'. "
        "To control attendee notifications, set 'send_updates' to 'all' | 'externalOnly' | 'none'."
    )
)
def create_event(
    calendar: str,
    summary: str,
    start: str,
    end: str,
    time_zone: Optional[str] = None,
    description: Optional[str] = None,
    location: Optional[str] = None,
    attendees: Optional[Union[List[str], str, Dict[str, Any]]] = None,
    reminder_minutes: Optional[Union[List[int], str]] = None,
    send_updates: Optional[Literal["all", "externalOnly", "none"]] = None,
) -> Dict[str, Any]:
    try:
        normalized_attendees = _normalize_attendees(attendees)
        minutes_list = _normalize_reminder_minutes(reminder_minutes)
        reminders_payload: Optional[Dict[str, Any]] = None
        if minutes_list is not None:
            # If list is empty, disable reminders; otherwise set popup overrides
            reminders_payload = {"useDefault": False}
            if len(minutes_list) > 0:
                reminders_payload["overrides"] = [
                    {"method": "popup", "minutes": m} for m in minutes_list
                ]
        return gc_create_event(
            calendar=calendar,
            summary=summary,
            start=start,
            end=end,
            time_zone=time_zone,
            description=description,
            location=location,
            attendees=normalized_attendees,
            reminders=reminders_payload,
            send_updates=send_updates,
        )
    except Exception as e:
        return _error_response(e)


@mcp.tool(description="Update an event by ID with a JSON patch of fields to change.")
def update_event(calendar: str, event_id: str, patch: Dict[str, Any]) -> Dict[str, Any]:
    try:
        safe_patch = dict(patch or {})
        if "attendees" in safe_patch:
            normalized = _normalize_attendees(safe_patch.get("attendees"))
            if normalized is not None:
                safe_patch["attendees"] = normalized
            else:
                # Remove invalid attendees payload to avoid downstream schema errors
                safe_patch.pop("attendees", None)
        return gc_update_event(calendar=calendar, event_id=event_id, patch=safe_patch)
    except Exception as e:
        return _error_response(e)


@mcp.tool(description="Delete an event by ID")
def delete_event(calendar: str, event_id: str) -> Dict[str, Any]:
    try:
        return gc_delete_event(calendar=calendar, event_id=event_id)
    except Exception as e:
        return _error_response(e)


@mcp.tool(description="Resolve a calendar by name or ID; returns the calendarId and summary")
def resolve_calendar(query: str) -> Dict[str, Any]:
    try:
        calendar_id = gc_resolve_calendar_id(query)
        # fetch summary
        for cal in gc_list_calendars():
            if cal["id"] == calendar_id:
                return {"calendarId": calendar_id, "summary": cal.get("summary")}
        return {"calendarId": calendar_id, "summary": None}
    except Exception as e:
        return _error_response(e)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    host = "0.0.0.0"

    print(f"Starting FastMCP server on {host}:{port}")

    mcp.run(transport="http", host=host, port=port, stateless_http=True)
