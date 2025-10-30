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
    creds = flow.run_local_server(open_browser=True)
    
    # If no refresh token, try to get one by forcing re-authorization
    if not creds.refresh_token:
        print("WARNING: No refresh token received. Forcing re-authorization with consent prompt...", file=sys.stderr)
        flow.redirect_uri = "http://localhost:8080/"
        authorization_url, _ = flow.authorization_url(
            access_type='offline',
            include_granted_scopes='true',
            prompt='consent'
        )
        print(f"\nPlease visit this URL to re-authorize:\n{authorization_url}\n")
        import webbrowser
        import socketserver
        import urllib.parse
        from http.server import BaseHTTPRequestHandler
        
        class OAuthHandler(BaseHTTPRequestHandler):
            def do_GET(self):
                query = urllib.parse.urlparse(self.path).query
                params = urllib.parse.parse_qs(query)
                if 'code' in params:
                    self.send_response(200)
                    self.send_header('Content-type', 'text/html')
                    self.end_headers()
                    self.wfile.write(b'<html><body><h1>Authorization successful!</h1><p>You can close this window.</p></body></html>')
                    self.server.auth_code = params['code'][0]
                else:
                    self.send_response(400)
                    self.end_headers()
                    
            def log_message(self, format, *args):
                pass
        
        with socketserver.TCPServer(("", 8080), OAuthHandler) as httpd:
            webbrowser.open(authorization_url)
            httpd.timeout = 300
            httpd.handle_request()
            
            if not hasattr(httpd, 'auth_code'):
                print("ERROR: Authorization failed or timed out.", file=sys.stderr)
                sys.exit(3)
            
            flow.fetch_token(code=httpd.auth_code)
            creds = flow.credentials

    if not creds.refresh_token:
        print("ERROR: No refresh token returned. Ensure you haven't previously consented with same scope, or reset test users.", file=sys.stderr)
        sys.exit(2)

    print("GOOGLE_REFRESH_TOKEN=\"%s\"" % creds.refresh_token)


if __name__ == "__main__":
    main()


