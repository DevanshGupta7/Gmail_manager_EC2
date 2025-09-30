
# from waitress import serve
# from oauth_mail_creds import authenticate_gmail
# from googleapiclient.errors import HttpError
# from googleapiclient.discovery import build
# from googleapiclient.http import MediaIoBaseUpload
# from dotenv import dotenv_values
# import groq
# from pymongo.mongo_client import MongoClient
# from datetime import datetime, timezone, timedelta
# from pymongo.server_api import ServerApi
# from bs4 import BeautifulSoup
# import base64
# import re
# import time
# import io
# import json

# env_values = dotenv_values(".env")

# MONGODB_URI = env_values.get("MONGODB_URI")

# GROQ_API_KEY = env_values.get("GROQ_API_KEY")
# groq_client = groq.Groq(api_key=GROQ_API_KEY)

# user_labels = {"Bills & Payments": "Label_2",
#                "Shopping": "Label_3",
#                "Finance": "Label_4",
#                "Subscriptions": "Label_5",
#                "Social": "Label_6",
#                "Travel": "Label_7",
#                "Primary": "Label_8",
#                "Personal": "Label_9",
#                "Reminder": "Label_10",
#                "Other": "Label_11",
#                "Important": "IMPORTANT"}

# creds = authenticate_gmail()
# service = build("gmail", "v1", credentials=creds)
# drive_service = build("drive", "v3", credentials=creds)

# fields = "id, labelIds, snippet, payload/mimeType, payload/headers, payload/body, payload(parts(mimeType,filename,body(data,attachmentId),parts)), internalDate"


# def get_db_emails():
#     db_client = MongoClient(MONGODB_URI, server_api=ServerApi("1"), tls=True, tlsAllowInvalidCertificates=True)
#     db_emails = db_client["emails"]
#     return db_emails
           
        
# def categorise_email_with_label(email, text_content, html_content, sender, subject):
#     found_label = False
    
#     for label_name in user_labels.values():
#         if label_name not in email.get("labelIds", []):
#             found_label = False
#         else:
#             found_label = True
#             break
    
#     if not found_label:
#         email_label = get_appropriate_label(email.get("id", ""), text_content, html_content, sender, subject)
        
#         if email_label in user_labels.keys():
#             email_data = add_appropriate_label_to_email(email.get("id", ""), user_labels[email_label])
#             return email_data
#     else:
#         return {"Groq AI": "Label already exists"}
        
#     return {"Groq AI": "No Label Found"}
        

# def get_appropriate_label(email_id, text_content, html_content, sender, subject):
#     emails_db = get_db_emails()
#     max_retries = 5
#     retry_delay = 5
#     label_found = False
    
#     html_content = BeautifulSoup(html_content, "lxml").get_text(separator=" ", strip=True)
#     full_content = text_content + html_content
#     full_content = full_content.split()
#     full_content = " ".join(full_content[:500])
    
#     prompt = f"""
#     You are an AI assistant that categorizes emails into predefined labels.
#     PLEASE DO NOT RESPOND ANY WORD OTHER THAN GIVEN LABELS (Bills & Payments, Shopping, Finance, Subscriptions, Social, Travel, Primary, Important,
#     Reminder, Other)
#     The categories are:
#     - Bills & Payments (To track financial emails.)
#     - Shopping (Amazon, Flipkart, Myntra)
#     - Finance (Banks, credit cards, bills)
#     - Subscriptions (For newsletters and services)
#     - Social (Facebook, Instagram, LinkedIn)
#     - Travel (Flight tickets, hotel bookings)
#     - Primary (Important emails (boss, family, friends))
#     - Personal (For personal conversations.)
#     - Important (Like hackathon, Competition based on Coding skills, any results, etc)
#     - Reminder (Like anything about reminding lke few days left for completing course, few days left for editing your application but not like spam)
#     - Other (If you do not find appropriate labels given in this query.)
#     If email sender is like Quora or other question answer website then put that email in "Other" label.
#     If no appropriate label found from given labels then respond it will be 'Other' label.
    
#     ***DO NOT RESPOND ANYTHING OTHER FROM LABEL***

#     Classify this email into one category.

#     Email Subject: {subject}
#     Email Body: {full_content}
#     Email Sender: {sender}

#     Respond with ONLY the category name.
#     """
#     print("Yes Groq is running to find appropriate label.")
#     for attempt in range(max_retries):
#         try:
#             print("Checking label...")
#             response = groq_client.chat.completions.create(
#                 model="gemma2-9b-it",
#                 messages=[{"role": "user", "content": prompt}],
#                 temperature=0.2,
#                 top_p=0.5,
#                 stream=False
#             )

#             email_label = response.choices[0].message.content
#             email_label = email_label.strip().strip()
#             if email_label not in user_labels.keys():
#                 email_label = "Other"
#             print(f"Label gets from groq: {email_label}")
#             label_found = True
#             break
            
#         except groq.RateLimitError:
#             if attempt < max_retries - 1:
#                 print(f"Rate limit exceeded. Retrying in {retry_delay} seconds...")
#                 time.sleep(retry_delay)
#             else:
#                 print("Max retries reached. Please try again later.")
#                 email_label = ""
#                 label_found = False
#                 break
#         except groq.APIStatusError as error:
#             print(f"API Status Error: {error.status_code} - {error}")
#             email_label = ""
#             label_found = False
#             break
#         except groq.APIConnectionError as error:
#             print(f"Connection Error: {error}")
#             email_label = ""
#             label_found = False
#             break
#         except Exception as error:
#             print(f"Unexpected error: {error}")
#             email_label = ""
#             label_found = False
#             break

#     return email_label


# def add_appropriate_label_to_email(email_id, label_id):
#     try:
#         body = {"addLabelIds": [label_id],
#                 "removeLabelIds": []}
        
#         email = service.users().messages().modify(userId="me", id=email_id, body=body).execute()
#         print(f"Email after adding label: {email}")
#         return email
    
#     except HttpError as error:
#         print(f"Error while adding label to email: {error}")
#         return {"error": str(error)}
#     except Exception as error:
#         print(f"Error exception: {error}")
#         return {"error": str(error)}
    
    
# def extract_text_html(part):
#     temp_text_content = ""
#     temp_html_content = ""
    
#     if part.get("mimeType", "") == "text/plain":
#         temp_text_content = base64.urlsafe_b64decode(part["body"].get("data", "") or "").decode("utf-8", errors="ignore").strip()
#     elif part.get("mimeType", "") in ["text/x-amp-html", "text/html"]:
#         temp_html_content = base64.urlsafe_b64decode(part["body"].get("data", "") or "").decode("utf-8", errors="ignore")
            
#     return temp_text_content, temp_html_content
    
    
# def process_parts(parts):
#     attachments = []
#     text_content = ""
#     html_content = ""
    
#     for part in parts:
#         if "parts" in part:
#             temp_text, temp_html, temp_attachments = process_parts(part["parts"])
#             text_content += temp_text
#             html_content += temp_html
#             attachments.extend(temp_attachments)

#         else:
#             temp_text_content, temp_html_content = extract_text_html(part)
#             text_content += temp_text_content
#             html_content += temp_html_content
            
#             if part.get("filename") != "" and (part.get("body", {}).get("attachmentId", "") or part.get("body", {}).get("data", "")):
#                 attachments.append((part["filename"], part["mimeType"], part["body"].get("attachmentId", ""), part["body"].get("data", "")))
                
#     return text_content, html_content, attachments


# def save_attachment(email_id, filename, mimeType, attachment_id="", data="", folder_id="1gWXNr5EYPqyV3RMRDE2wOL5i7VSrtt4a"):    
#     if attachment_id:
#         attachment = service.users().messages().attachments().get(userId="me", messageId=email_id, id=attachment_id).execute()
#         file_data = base64.urlsafe_b64decode(attachment.get("data", "").encode("utf-8"))
    
#     elif data:
#         file_data = base64.urlsafe_b64decode(data.encode("utf-8"))
#     else:
#         raise ValueError("Either attachment_id or data must be provided")
    
#     file_metadata = {"name": filename}
    
#     if folder_id:
#         file_metadata["parents"] = [folder_id]

#     media = MediaIoBaseUpload(io.BytesIO(file_data), mimetype=mimeType, resumable=True)

#     uploaded_file = drive_service.files().create(body=file_metadata, media_body=media, fields="id, webViewLink").execute()

#     return uploaded_file.get("id"), uploaded_file.get("webViewLink")
    
    
# def process_single_email(email):
#     attachments_details = []
#     payload = email.get("payload", {})
    
#     if payload["mimeType"] not in ["text/plain", "text/html"]:
#         text_content, html_content, attachments = process_parts(payload.get("parts", []))
        
#         for attachment in attachments:
#             if attachment[0] and (attachment[1] or attachment[2]):
#                 drive_file_id, drive_file_link = save_attachment(email["id"], f"{email["id"]}_{attachment[0]}", attachment[1], attachment[2], attachment[3])
#                 attachments_details.append({"filename": attachment[0],
#                                             "drive_file_id": drive_file_id,
#                                             "drive_file_link": drive_file_link})
                
#     else:
#         if payload["mimeType"] == "text/plain":
#             text_content = base64.urlsafe_b64decode(payload["body"].get("data", "") or "").decode("utf-8", errors="ignore")
#             html_content = ""
#         elif payload["mimeType"] == "text/html":
#             html_content = base64.urlsafe_b64decode(payload["body"].get("data", "") or "").decode("utf-8", errors="ignore")
#             text_content = ""
    
#     subject = next((header["value"] for header in email["payload"].get("headers", []) if header["name"] == "Subject"), "")
#     snippet = email.get("snippet", "")
#     sender = next((header["value"] for header in email["payload"].get("headers", []) if header["name"] == "From"), "")
#     reciever = next((header["value"] for header in email["payload"].get("headers", []) if header["name"] == "To"), "")
#     timestamp = datetime.fromtimestamp(int(email["internalDate"]) / 1000, tz=timezone.utc).astimezone(timezone(timedelta(hours=5, minutes=30))).strftime("%d %B %Y, %I:%M:%S %p")
    
#     categorise_email_with_label(email, text_content, html_content, sender, subject)
    
#     email_data = {"email_id": email.get("id", ""),
#                   "labelIds": email.get("labelIds", []),
#                   "text_content": text_content,
#                   "html_content": html_content,
#                   "subject": subject,
#                   "snippet": snippet,
#                   "sender": sender,
#                   "reciever": reciever,
#                   "attachments": attachments_details,
#                   "timestamp": timestamp}
    
#     return email_data


# def get_fetch_email_with_content(email_id: str):
#      try:
#          email = service.users().messages().get(userId="me", id=email_id, fields=fields).execute()
#          print(f"Using get_fetch_email_with_content: {email}")
#          email_data = process_single_email(email)
#          print(f"Email_data from process_single_email: {email_data}")
#          return email_data
     
#      except HttpError as error:
#          print(f"Error fetching email: {error}")
#          return {"error": str(error)}
#      except Exception as error:
#          print(f"Error Exception: {error}")
#          return {"error": str(error)}
     
     
# def get_fetch_email(email_id: str):
#      try:
#          email = service.users().messages().get(userId="me", id=email_id, fields=fields).execute()
#          print(f"Using get_fetch_email: {email}")
#          return email
     
#      except HttpError as error:
#          print(f"Error fetching email: {error}")
#          return {"email": "empty", "error": error}
#      except Exception as error:
#          print(f"Error Exception: {error}")
#          return {"email": "empty", "error": error}

    
# def get_new_emails_from_gmail(email_id: str):
#     emails_db = get_db_emails()

#     email_data = get_fetch_email_with_content(email_id)
    
#     print("adding to all_emails database")

#     print("\n\n\n\n\n")
#     print(f"Email data: {email_data}")

#     if not email_data.get("error"):
#         if "UNREAD" not in email_data.get("labelIds", []):
#             data = {"email_id": email_data.get("email_id", ""),
#                     "full_email": email_data,
#                     "is_unread": False}
#         else:
#             data = {"email_id": email_data.get("email_id", ""),
#                     "full_email": email_data,
#                     "is_unread": True}

#     print(f"Data to append in database: {data}")
#     print("next step of adding to all_emails database")
#     emails_db.all_emails.update_one({"email_id": data["email_id"]}, {"$set": data}, upsert=True)


# def fetch_emails():
#     email_ids = service.users().messages().list(userId="me", maxResults=3000).execute()
#     print(f"Email ids: {email_ids}")
#     with open("email_ids.json", "w") as f:
#         json.dump(email_ids, f, indent=4)
#     for email_id in email_ids["messages"]:
#         get_new_emails_from_gmail(email_id["id"])

# fetch_emails()
# import firebase_admin
# from firebase_admin import credentials, db
# firebase_creds = credentials.Certificate("savingotps-firebase-adminsdk-fbsvc-6175414d56.json")
# firebase_admin.initialize_app(firebase_creds, {
#     "databaseURL": "https://savingotps-default-rtdb.asia-southeast1.firebasedatabase.app"
# })
# otp_ref = db.reference("otp")
# otp_ref.set("1253456")

# import base64

# print(base64.urlsafe_b64decode("VGVzdCBtZXNzYWdl").decode("utf-8"))

# from googleapiclient.discovery import build
# from oauth_mail_creds import authenticate_gmail

# def get_latest_history_id():
#     creds = authenticate_gmail()
#     service = build("gmail", "v1", credentials=creds)

#     profile = service.users().getProfile(userId="me").execute()
#     history_id = profile.get("historyId")
#     print("Latest historyId:", history_id)
#     return history_id

# # Run this once before setting up Gmail watch
# latest_id = get_latest_history_id()

import json
import pickle

with open("token.json", "r") as token_file:
    print(json.load(token_file))