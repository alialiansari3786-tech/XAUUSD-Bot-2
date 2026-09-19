"""
Saxo OAuth Bootstrap - RUN THIS ONCE, LOCALLY, ON YOUR OWN MACHINE.

This is the one manual step that cannot be automated: Saxo requires an
interactive browser login to grant your app permission the very first
time. This script walks you through it and produces a refresh token
that the bot can then use indefinitely (Saxo rotates refresh tokens on
every use, so as long as the bot refreshes regularly - which it does,
every single scan cycle - you should not need to run this again unless
the chain breaks for some reason, e.g. an extended outage).

This script can be run from anywhere (it doesn't assume it's sitting
inside your cloned repo) - it saves the result next to itself AND
prints it directly to the terminal, so you can just copy-paste the
JSON straight into GitHub's web editor if that's easier than using git.

USAGE:
    python saxo_bootstrap.py

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
    5. This exchanges the code for a refresh token, prints it, and
       saves it to saxo_token.json next to this script. Either way,
       that content needs to end up at state/saxo_token.json in your
       GitHub repo (via git, or by pasting into GitHub's web editor).
"""

import base64
import json
import sys
from pathlib import Path
from urllib.parse import urlencode, urlparse, parse_qs

import requests

# Saved next to this script, wherever that happens to be - no
# assumption about being inside the repo.
OUTPUT_FILE = Path(__file__).parent / 'saxo_token.json'


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

    if response.status_code < 200 or response.status_code >= 300:
        print(f"ERROR: token exchange failed ({response.status_code}): {response.text}")
        sys.exit(1)

    payload = response.json()
    refresh_token = payload.get('refresh_token')

    if not refresh_token:
        print(f"ERROR: no refresh_token in response: {payload}")
        sys.exit(1)

    token_json = json.dumps({'refresh_token': refresh_token}, indent=2)

    with open(OUTPUT_FILE, 'w') as f:
        f.write(token_json)

    print()
    print("=" * 60)
    print("SUCCESS")
    print("=" * 60)
    print()
    print(f"Saved to: {OUTPUT_FILE}")
    print()
    print("This exact content needs to end up in your GitHub repo at")
    print("state/saxo_token.json. Copy everything between the lines below:")
    print()
    print("-" * 60)
    print(token_json)
    print("-" * 60)
    print()
    print("Easiest path if you don't have git set up locally:")
    print("  1. Go to your repo on GitHub -> state folder (create it if it")
    print("     doesn't exist) -> Add file -> Create new file")
    print("  2. Name it: saxo_token.json")
    print("  3. Paste the JSON shown above")
    print("  4. Commit directly to the main branch")
    print()
    print("The bot takes it from there - it refreshes this token")
    print("automatically every cycle and commits the rotated token back")
    print("to the repo. You shouldn't need to run this script again unless")
    print("you see a Telegram alert saying Saxo auth needs re-bootstrapping.")


if __name__ == '__main__':
    main()

