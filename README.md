# Poke Google Calendar MCP (Multi-Calendar)

An [FastMCP](https://github.com/jlowin/fastmcp) server that lets Poke access and manage events across ALL of your Google Calendars, not just the primary one. Uses one-time local OAuth to obtain a refresh token; the server refreshes access automatically.

[![Deploy to Render](https://render.com/images/deploy-to-render-button.svg)](https://render.com/deploy?repo=https://github.com/InteractionCo/mcp-server-template)

## Local Development

### Setup

Fork the repo, then run:

```bash
git clone <your-repo-url>
cd poke-google-calendar-mcp
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

### One-time local OAuth (to obtain refresh token)

Create a Google Cloud project and enable "Google Calendar API". Create OAuth 2.0 Client credentials with Application type = Desktop app.

**Important for long-lived tokens:**
- Publish your OAuth consent screen (not just "Testing" mode) for refresh tokens to last longer
- Add yourself as a test user if still in testing mode
- The script will automatically request offline access with consent prompt to ensure a refresh token is issued

Then run:

```bash
export GOOGLE_CLIENT_ID=your_client_id
export GOOGLE_CLIENT_SECRET=your_client_secret
python3 scripts/get_google_refresh_token.py
```

Copy the output `GOOGLE_REFRESH_TOKEN` value.

**Note:** If your refresh token expires, regenerate it using the same script. The updated script ensures tokens are issued with proper offline access settings.

Copy `.env.example` to `.env` and fill in your credentials:

```bash
cp .env.example .env
# edit .env with your credentials
source .env
python3 src/server.py
```

Then in another terminal:

```bash
npx @modelcontextprotocol/inspector
```

Open http://localhost:3000 and connect to `http://localhost:8000/mcp` using "Streamable HTTP" transport (NOTE THE `/mcp`!).
Preflight requests (OPTIONS) are allowed by default via CORS, so browser clients will work.

## Deployment

### FastMCP Cloud (recommended)
1. Push this repo to GitHub and sign in to `fastmcp.cloud`.
2. Create a new project and point it at your repo.
3. Entrypoint: `src/server.py:mcp` (the FastMCP instance is named `mcp`).
4. Set environment variables:
   - `GOOGLE_CLIENT_ID`
   - `GOOGLE_CLIENT_SECRET`
   - `GOOGLE_REFRESH_TOKEN`
5. Deploy. Your URL will look like `https://<project>.fastmcp.app/mcp`.

Notes:
- Health endpoint at `/` returns `200 OK`.
- CORS is enabled, so browser-based clients can connect.

## Poke Setup

You can connect your MCP server to Poke at (poke.com/settings/connections)[poke.com/settings/connections].
To test the connection explitly, ask poke somethink like `Tell the subagent to use the "{connection name}" integration's "{tool name}" tool`.
If you run into persistent issues of poke not calling the right MCP (e.g. after you've renamed the connection) you may send `clearhistory` to poke to delete all message history and start fresh.
We're working hard on improving the integration use of Poke :)


## Exposed Tools

- `list_calendars()` → `{ calendars: [{ id, summary, primary, accessRole, timeZone }] }`
- `list_events(calendar?, time_min?, time_max?, max_results?, query?, include_all_calendars?)` → `{ events: [...] }`
- `create_event(calendar, summary, start, end, time_zone?, description?, location?, reminders?, recurrence?)` → `{ ok, event }`
- `update_event(calendar, event_id, patch)` → `{ ok, event }`
- `delete_event(calendar, event_id, as_instance?)` → `{ ok }`
- `resolve_calendar(query)` → `{ calendarId, summary }`
- `list_recurring_instances(calendar, recurring_event_id, time_min?, time_max?, max_results?)` → `{ ok, instances: [...] }`
- `cancel_recurring_instance(calendar, instance_id? [, recurring_event_id, original_start_time] )` → `{ ok, instance }`
- `update_following_instances(calendar, recurring_event_id, target_instance_start, change_patch, new_recurrence)` → `{ ok, newRecurringEvent }`

Times are ISO 8601 (e.g., `2025-10-22T14:30:00-04:00`) or all-day dates (`YYYY-MM-DD`). When aggregating across calendars, each event includes `calendarId`.

### Recurring events

- Creating a recurring event: pass `recurrence` as a list of RFC 5545 strings, e.g.:
  - `["RRULE:FREQ=WEEKLY;COUNT=5"]`
  - `["RRULE:FREQ=WEEKLY;UNTIL=20251231T235959Z"]`
- Listing instances of a recurring event: use `list_recurring_instances(...)`. This returns each occurrence with its `instanceId`, `recurringEventId`, and `originalStartTime`.
- Deleting/cancelling a single occurrence:
  - If you have an instance’s `eventId` (common when using `list_events` which flattens instances), call `delete_event(..., as_instance=true)` to cancel that occurrence.
  - Or use `cancel_recurring_instance(...)` with either the `instance_id` directly, or the pair `recurring_event_id` + `original_start_time`.
- Modify all following instances:
  - Use `update_following_instances(...)` to split the series at `target_instance_start` and create a new recurring series with your `change_patch` and `new_recurrence`.
  - Note: This helper supports dateTime events (not all-day). Provide `new_recurrence` explicitly to define how the new series should repeat.

## Customization

Add more tools by decorating functions with `@mcp.tool`:

```python
@mcp.tool
def calculate(x: float, y: float, operation: str) -> float:
    """Perform basic arithmetic operations."""
    if operation == "add":
        return x + y
    elif operation == "multiply":
        return x * y
    # ...
```
