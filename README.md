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

Create a Google Cloud project and enable "Google Calendar API". Create OAuth 2.0 Client credentials with Application type = Desktop app. Then run:

```bash
export GOOGLE_CLIENT_ID=your_client_id
export GOOGLE_CLIENT_SECRET=your_client_secret
python3 scripts/get_google_refresh_token.py
```

Copy the output `GOOGLE_REFRESH_TOKEN` value.

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
- `create_event(calendar, summary, start, end, time_zone?, description?, location?, attendees?)` → `{ ok, event }`
- `update_event(calendar, event_id, patch)` → `{ ok, event }`
- `delete_event(calendar, event_id)` → `{ ok }`
- `resolve_calendar(query)` → `{ calendarId, summary }`

Times are ISO 8601 (e.g., `2025-10-22T14:30:00-04:00`) or all-day dates (`YYYY-MM-DD`). When aggregating across calendars, each event includes `calendarId`.

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
