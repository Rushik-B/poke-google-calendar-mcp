#!/usr/bin/env python3
import os
from typing import Any, Dict, List, Optional

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
        list_recurring_instances as gc_list_instances,
        cancel_recurring_instance as gc_cancel_instance,
        update_following_instances as gc_update_following,
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
        list_recurring_instances as gc_list_instances,
        cancel_recurring_instance as gc_cancel_instance,
        update_following_instances as gc_update_following,
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


def _normalize_reminder_minutes(value: Any) -> Optional[List[int]]:
    """Accept list[int|float]. Returns a sorted, deduplicated list of non-negative minutes."""
    if value is None:
        return None
    if not isinstance(value, list):
        return None
    minutes: List[int] = []
    for item in value:
        if isinstance(item, (int, float)):
            m = int(item)
            if m >= 0:
                minutes.append(m)
    return sorted({m for m in minutes})


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
        "Create a calendar event for yourself. Start/end are ISO 8601 or all-day date (YYYY-MM-DD). "
        "Set pop-up reminders with 'reminders' as an array of minutes before start, e.g. [120, 60]. "
        "To disable reminders, pass an empty array []. Omit 'reminders' to use calendar defaults. "
        "For recurring events, pass 'recurrence' as a list of RRULE/EXDATE strings. "
        "To create an all-day event, set all_day=true and provide 'start' as YYYY-MM-DD. "
        "You may omit 'end' and it will default to the next day (exclusive). "
        "For multi-day all-day, set 'end' to the day after the last day."
    )
)
def create_event(
    calendar: str,
    summary: str,
    start: str,
    end: Optional[str] = None,
    time_zone: Optional[str] = None,
    description: Optional[str] = None,
    location: Optional[str] = None,
    reminders: Optional[List[int]] = None,
    recurrence: Optional[List[str]] = None,
    all_day: Optional[bool] = None,
) -> Dict[str, Any]:
    try:
        minutes_list = _normalize_reminder_minutes(reminders)
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
            reminders=reminders_payload,
            recurrence=recurrence,
            all_day=bool(all_day) if all_day is not None else False,
        )
    except Exception as e:
        return _error_response(e)


@mcp.tool(description="Update an event by ID with a JSON patch of fields to change.")
def update_event(calendar: str, event_id: str, patch: Dict[str, Any]) -> Dict[str, Any]:
    try:
        safe_patch = dict(patch or {})
        return gc_update_event(calendar=calendar, event_id=event_id, patch=safe_patch)
    except Exception as e:
        return _error_response(e)


@mcp.tool(description="Delete an event by ID. For a single occurrence of a recurring series, set as_instance=true.")
def delete_event(calendar: str, event_id: str, as_instance: bool = False) -> Dict[str, Any]:
    try:
        return gc_delete_event(calendar=calendar, event_id=event_id, as_instance=as_instance)
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


@mcp.tool(
    description=(
        "List instances of a recurring event. Provide the recurring event's ID. "
        "Optionally filter by time_min/time_max. Times are ISO 8601."
    )
)
def list_recurring_instances(
    calendar: str,
    recurring_event_id: str,
    time_min: Optional[str] = None,
    time_max: Optional[str] = None,
    max_results: Optional[int] = 50,
) -> Dict[str, Any]:
    try:
        return gc_list_instances(
            calendar=calendar,
            recurring_event_id=recurring_event_id,
            time_min=time_min,
            time_max=time_max,
            max_results=max_results,
        )
    except Exception as e:
        return _error_response(e)


@mcp.tool(
    description=(
        "Cancel a single occurrence of a recurring event. Provide either instance_id, "
        "or (recurring_event_id AND original_start_time). original_start_time must match the instance's "
        "originalStartTime value (ISO 8601)."
    )
)
def cancel_recurring_instance(
    calendar: str,
    instance_id: Optional[str] = None,
    recurring_event_id: Optional[str] = None,
    original_start_time: Optional[str] = None,
) -> Dict[str, Any]:
    try:
        return gc_cancel_instance(
            calendar=calendar,
            instance_id=instance_id,
            recurring_event_id=recurring_event_id,
            original_start_time=original_start_time,
        )
    except Exception as e:
        return _error_response(e)


@mcp.tool(
    description=(
        "Modify all following instances starting from a target instance by splitting the series. "
        "Requires recurring_event_id, target_instance_start (ISO), change_patch for new event fields, "
        "and new_recurrence (list of RRULE/EXDATE strings) for the new series. "
        "Only supports dateTime (not all-day) events."
    )
)
def update_following_instances(
    calendar: str,
    recurring_event_id: str,
    target_instance_start: str,
    change_patch: Dict[str, Any],
    new_recurrence: List[str],
) -> Dict[str, Any]:
    try:
        return gc_update_following(
            calendar=calendar,
            recurring_event_id=recurring_event_id,
            target_instance_start=target_instance_start,
            change_patch=change_patch,
            new_recurrence=new_recurrence,
        )
    except Exception as e:
        return _error_response(e)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    host = "0.0.0.0"

    print(f"Starting FastMCP server on {host}:{port}")

    mcp.run(transport="http", host=host, port=port, stateless_http=True)
