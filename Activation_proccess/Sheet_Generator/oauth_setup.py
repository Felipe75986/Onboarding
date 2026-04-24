import os
import sys

from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = [
    "https://www.googleapis.com/auth/drive",
    "https://www.googleapis.com/auth/spreadsheets",
]

CLIENT_SECRET = os.environ.get("OAUTH_CLIENT_SECRET", "client_secret.json")
TOKEN_OUT = os.environ.get("OAUTH_TOKEN_OUT", "token.json")


def main():
    if not os.path.exists(CLIENT_SECRET):
        sys.exit(
            f"Missing {CLIENT_SECRET}. "
            "Download OAuth client JSON from GCP Console and place it here."
        )
    flow = InstalledAppFlow.from_client_secrets_file(CLIENT_SECRET, SCOPES)
    creds = flow.run_local_server(port=0)
    with open(TOKEN_OUT, "w") as f:
        f.write(creds.to_json())
    print(f"Token saved to {TOKEN_OUT}")


if __name__ == "__main__":
    main()
