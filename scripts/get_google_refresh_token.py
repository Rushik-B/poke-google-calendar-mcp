#!/usr/bin/env python3
import os
import sys
from dotenv import load_dotenv
from google_auth_oauthlib.flow import InstalledAppFlow

# Load environment variables from .env file
load_dotenv()

SCOPES = ["https://www.googleapis.com/auth/calendar"]


def main() -> None:
    client_id = os.environ.get("GOOGLE_CLIENT_ID")
    client_secret = os.environ.get("GOOGLE_CLIENT_SECRET")

    if not client_id or not client_secret:
        print("ERROR: Set GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET in your environment.", file=sys.stderr)
        sys.exit(1)

    # Build a client config structure compatible with InstalledAppFlow.from_client_config
    client_config = {
        "installed": {
            "client_id": client_id,
            "client_secret": client_secret,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": [
                "http://localhost",
                "http://localhost:8080/",
                "http://localhost:8080",
            ],
        }
    }

    flow = InstalledAppFlow.from_client_config(client_config, SCOPES)
    # Explicitly request offline access and force consent to ensure refresh token is issued
    # This ensures we get a refresh token that lasts longer
    creds = flow.run_local_server(
        open_browser=True,
        access_type='offline',
        prompt='consent'  # Force consent screen to ensure refresh token is issued
    )

    if not creds.refresh_token:
        print("ERROR: No refresh token returned. Ensure you haven't previously consented with same scope, or reset test users.", file=sys.stderr)
        sys.exit(2)

    print("GOOGLE_REFRESH_TOKEN=\"%s\"" % creds.refresh_token)


if __name__ == "__main__":
    main()


