"""
Saxo OAuth Bootstrap - RUN THIS ONCE, LOCALLY, ON YOUR OWN MACHINE.

This is the one manual step that cannot be automated: Saxo requires an
interactive browser login to grant your app permission the very first
time. This script walks you through it and produces a refresh token
that the bot can then use indefinitely (Saxo rotates refresh tokens on
every use, so as long as the bot refreshes regularly - which it does,
every single scan cycle - you should not need to run this again unless
the chain breaks for some reason, e.g. an extended outage).

USAGE:
    python scripts/saxo_bootstrap.py

You'll need:
    - Your Saxo SIM AppKey and AppSecret (from developer.saxo)
    - The redirect URI you registered for your app (e.g. http://localhost:8080)

WHAT HAPPENS:
    1. This prints an authorization URL.
    2. Open it in a browser and log in with your Saxo SIM credentials.
    3. After approving, your browser will redirect to your redirect URI
       with a `code=...` parameter in the URL - it doesn't matter that
       the page itself won't load (localhost isn't a running server);
       just copy the FULL URL from your browser's address bar.
    4. Paste that URL back into this script when prompted.
    5. This exchanges the code for a refresh token and saves it to
       state/saxo_token.json - commit that file to your repo once,
       manually, and the bot takes over from there.
"""

import base64
import json
import sys
from pathlib import Path
from urllib.parse import urlencode, urlparse, parse_qs

import requests

BASE_DIR = Path(__file__).parent.parent
STATE_DIR = BASE_DIR / 'state'
TOKEN_FILE = STATE_DIR / 'saxo_token.json'


def main():
    print("=" * 60)
    print("Saxo OAuth Bootstrap")
    print("=" * 60)

    app_key = input("Enter your Saxo AppKey: ").strip()
    app_secret = input("Enter your Saxo AppSecret: ").strip()
    redirect_uri = input("Enter your registered redirect URI (e.g. http://localhost:8080): ").strip()
    auth_base = input("Auth base URL [https://sim.logonvalidation.net]: ").strip() or "https://sim.logonvalidation.net"

    params = {
        'response_type': 'code',
        'client_id': app_key,
        'redirect_uri': redirect_uri,
        'state': 'bootstrap',
    }
    auth_url = f"{auth_base}/authorize?{urlencode(params)}"

    print()
    print("Step 1: Open this URL in your browser and log in:")
    print()
    print(auth_url)
    print()
    print("Step 2: After logging in and approving, you'll be redirected to a URL")
    print("        that starts with your redirect URI and contains '?code=...'.")
    print("        The page itself may show an error (that's fine, expected) -")
    print("        just copy the FULL URL from your browser's address bar.")
    print()

    redirected_url = input("Paste the full redirected URL here: ").strip()

    parsed = urlparse(redirected_url)
    query = parse_qs(parsed.query)
    code = query.get('code', [None])[0]

    if not code:
        print("ERROR: couldn't find a 'code' parameter in that URL. Please try again.")
        sys.exit(1)

    print()
    print("Step 3: Exchanging authorization code for tokens...")

    credentials = base64.b64encode(f"{app_key}:{app_secret}".encode()).decode()

    response = requests.post(
        f"{auth_base}/token",
        headers={
            'Authorization': f'Basic {credentials}',
            'Content-Type': 'application/x-www-form-urlencoded'
        },
        data={
            'grant_type': 'authorization_code',
            'code': code,
            'redirect_uri': redirect_uri
        },
        timeout=15
    )

    if response.status_code != 200:
        print(f"ERROR: token exchange failed ({response.status_code}): {response.text}")
        sys.exit(1)

    payload = response.json()
    refresh_token = payload.get('refresh_token')

    if not refresh_token:
        print(f"ERROR: no refresh_token in response: {payload}")
        sys.exit(1)

    STATE_DIR.mkdir(parents=True, exist_ok=True)
    with open(TOKEN_FILE, 'w') as f:
        json.dump({'refresh_token': refresh_token}, f, indent=2)

    print()
    print("=" * 60)
    print(f"SUCCESS. Refresh token saved to: {TOKEN_FILE}")
    print("=" * 60)
    print()
    print("Next steps:")
    print(f"  1. git add {TOKEN_FILE.relative_to(BASE_DIR)}")
    print(f"  2. git commit -m 'Bootstrap Saxo OAuth token'")
    print(f"  3. git push")
    print()
    print("The bot will take it from here - it refreshes this token")
    print("automatically every cycle and commits the rotated token back")
    print("to the repo. You shouldn't need to run this script again unless")
    print("you see a Telegram alert saying Saxo auth needs re-bootstrapping.")


if __name__ == '__main__':
    main()
