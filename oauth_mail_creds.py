import json
import os
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from google_auth_oauthlib.flow import InstalledAppFlow
from dotenv import dotenv_values

env_values = dotenv_values(".env")

def authenticate_gmail():
    creds = None
    token_file = "/var/www/google_auth/token.json"
    GOOGLE_AUTH_CREDS = env_values.get("GOOGLE_AUTH_CREDS")
    print(repr(GOOGLE_AUTH_CREDS))
    print(type(GOOGLE_AUTH_CREDS))

    SCOPES = ["https://mail.google.com/", "https://www.googleapis.com/auth/drive"]

    if os.path.exists(token_file):
        creds = Credentials.from_authorized_user_file(token_file, SCOPES)
    
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_config(json.loads(GOOGLE_AUTH_CREDS), SCOPES)
            creds = flow.run_local_server(port=0)
        with open(token_file, "w") as token_file:
            token_file.write(creds.to_json())

    print(f"Creds: {creds}")

    return creds