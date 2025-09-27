import json
from google.oauth2 import service_account
from dotenv import dotenv_values

def authenticate_gmail():
    creds = None
    env_values = dotenv_values(".env")
    GOOGLE_AUTH_CREDS = env_values.get("GOOGLE_AUTH_CREDS")
    print(repr(GOOGLE_AUTH_CREDS))
    print(type(GOOGLE_AUTH_CREDS))

    SCOPES = ["https://mail.google.com/", "https://www.googleapis.com/auth/drive"]
    
    creds = service_account.Credentials.from_service_account_info(
        json.loads(GOOGLE_AUTH_CREDS),
        scopes=SCOPES
    )
            
    return creds

authenticate_gmail()