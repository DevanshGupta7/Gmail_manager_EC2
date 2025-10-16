from flask import Flask, request, jsonify, g
from waitress import serve
from googleapiclient.errors import HttpError
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload
from dotenv import dotenv_values
import groq
from pymongo.mongo_client import MongoClient
from datetime import datetime, timezone, timedelta
import firebase_admin
from firebase_admin import credentials, db
from pymongo.server_api import ServerApi
from bs4 import BeautifulSoup
from apscheduler.schedulers.background import BackgroundScheduler
import base64
import json
import re
import time
import io
import logging

from oauth_mail_creds import authenticate_gmail

app = Flask(__name__)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

env_values = dotenv_values(".env")

MONGODB_URI = env_values.get("MONGODB_URI")
GROQ_API_KEY = env_values.get("GROQ_API_KEY")
FIREBASE_URL = env_values.get("FIREBASE_URL")
FIREBASE_CERTIFICATE = env_values.get("FIREBASE_CERTIFICATE")
GMAIL_ATTACHMENT_FOLDER_ID = env_values.get("GMAIL_ATTACHMENT_FOLDER_ID")

groq_client = groq.Groq(api_key=GROQ_API_KEY)

user_labels = {"Bills & Payments": "Label_2",
               "Shopping": "Label_3",
               "Finance": "Label_4",
               "Subscriptions": "Label_5",
               "Social": "Label_6",
               "Travel": "Label_7",
               "Primary": "Label_8",
               "Personal": "Label_9",
               "Reminder": "Label_10",
               "Other": "Label_11",
               "Important": "IMPORTANT"}

print("gmail authenticating")
try:
    creds = authenticate_gmail()
    print("gmail authenticated")
except Exception as e:
    print(f"An error occured in authenticating gmail: {e}")

try:
    service = build("gmail", "v1", credentials=creds)
    drive_service = build("drive", "v3", credentials=creds)

    firebase_creds = credentials.Certificate(json.loads(FIREBASE_CERTIFICATE))
    firebase_admin.initialize_app(firebase_creds, {
        "databaseURL": FIREBASE_URL
    })
    print("firebase authenticated")

    fields = "id, labelIds, snippet, payload/mimeType, payload/headers, payload/body, payload(parts(mimeType,filename,body(data,attachmentId),parts)), internalDate"
except Exception as e:
    print(f"An error occured in starting: {e}")


def get_db_emails():
    if "db" not in g:
        g.db_client = MongoClient(MONGODB_URI, server_api=ServerApi("1"), tls=True, tlsAllowInvalidCertificates=True)
        g.db_emails = g.db_client["emails"]
    return g.db_emails
    

@app.teardown_appcontext
def teardown_db(exception):
    db_client = getattr(g, "db_client", None)
    if db_client is not None:
        db_client.close()
        
        
def fetch_otp_from_email(text_content, html_content, sender, subject):
    completion = groq_client.chat.completions.create(
        model="gemma2-9b-it",
        messages=[
            {
                "role": "system",
                "content": "You are a good One time password (OTP) fetcher from given query and you only respond OTP in number extracted from given query and no other letters and symbol"
            },
            {
                "role": "user",
                "content": f"Sender: {sender}\nSubject: {subject}\n\n{text_content}\n\n{BeautifulSoup(html_content, "lxml").get_text(separator=" ", strip=True)}"
            }
        ],
        temperature=0,
        max_completion_tokens=100,
        top_p=1,
        stream=True,
    )
    
    otp = ""
    for chunk in completion:
        if chunk.choices[0].delta.content:
            otp += chunk.choices[0].delta.content
            
    return otp
           
        
def categorise_email_with_label(email, text_content, html_content, sender, subject):
    found_label = False
    is_otp_email = False
    
    for label_name in user_labels.values():
        if label_name not in email.get("labelIds", []):
            found_label = False
        else:
            found_label = True
            break
        
    completion = groq_client.chat.completions.create(
        model="gemma2-9b-it",
        messages=[{"role": "user", "content": f"Is this an OTP email? Does this emaail contains OTP. Respond yes or no.\n\n {text_content}\n\n {BeautifulSoup(html_content, "lxml").get_text(separator=" ", strip=True)}"}],
        temperature=0,
        max_completion_tokens=100,
        top_p=1,
        stream=True,
        stop=None
    )

    for chunk in completion:
        if chunk.choices[0].delta.content:
            if "yes" in chunk.choices[0].delta.content.lower():
                otp = fetch_otp_from_email(text_content, html_content, sender, subject)
                logger.debug(f"OTP from email: {otp}")
                otp_ref = db.reference("otp")
                otp_ref.set(str(otp))
                is_otp_email = True
                logger.info("Fetching otp from email is running")
                break
    
    if not found_label and not is_otp_email:
        email_label = get_appropriate_label(email.get("id", ""), text_content, html_content, sender, subject)
        logger.info("Getting appropriate label is running")
        
        if email_label in user_labels.keys():
            email_data = add_appropriate_label_to_email(email.get("id", ""), user_labels[email_label])
            return email_data
    else:
        return {"Groq AI": "Label already exists"}
        
    return {"Groq AI": "No Label Found"}
        

def get_appropriate_label(email_id, text_content, html_content, sender, subject):
    emails_db = get_db_emails()
    max_retries = 5
    retry_delay = 5
    label_found = False
    
    html_content = BeautifulSoup(html_content, "lxml").get_text(separator=" ", strip=True)
    full_content = text_content + html_content
    full_content = full_content.split()
    full_content = " ".join(full_content[:500])
    
    prompt = f"""
    You are an AI assistant that categorizes emails into predefined labels.
    PLEASE DO NOT RESPOND ANY WORD OTHER THAN GIVEN LABELS (Bills & Payments, Shopping, Finance, Subscriptions, Social, Travel, Primary, Important,
    Reminder, Other)
    The categories are:
    - Bills & Payments (To track financial emails.)
    - Shopping (Amazon, Flipkart, Myntra)
    - Finance (Banks, credit cards, bills)
    - Subscriptions (For newsletters and services)
    - Social (Facebook, Instagram, LinkedIn)
    - Travel (Flight tickets, hotel bookings)
    - Primary (Important emails (boss, family, friends))
    - Personal (For personal conversations.)
    - Important (Like hackathon, Competition based on Coding skills, any results, etc)
    - Reminder (Like anything about reminding lke few days left for completing course, few days left for editing your application but not like spam)
    - Other (If you do not find appropriate labels given in this query.)
    If email sender is like Quora or other question answer website then put that email in "Other" label.
    If no appropriate label found from given labels then respond it will be 'Other' label.
    
    ***DO NOT RESPOND ANYTHING OTHER FROM LABEL***

    Classify this email into one category.

    Email Subject: {subject}
    Email Body: {full_content}
    Email Sender: {sender}

    Respond with ONLY the category name.
    """
    logger.info("Yes Groq is running to find appropriate label.")
    for attempt in range(max_retries):
        try:
            logger.info("Checking label...")
            response = groq_client.chat.completions.create(
                model="gemma2-9b-it",
                messages=[{"role": "user", "content": prompt}],
                temperature=0.2,
                top_p=0.5,
                stream=False
            )

            email_label = response.choices[0].message.content
            email_label = re.sub(r"\s+", "", email_label).strip()
            logger.debug(f"Label gets from groq: {email_label}")
            label_found = True
            break
            
        except groq.RateLimitError:
            if attempt < max_retries - 1:
                logger.warning(f"Rate limit exceeded. Retrying in {retry_delay} seconds...")
                time.sleep(retry_delay)
            else:
                logger.error("Max retries reached. Please try again later.")
                email_label = ""
                label_found = False
                break
        except groq.APIStatusError as error:
            logger.error(f"API Status Error: {error.status_code} - {error}")
            email_label = ""
            label_found = False
            break
        except groq.APIConnectionError as error:
            logger.error(f"Connection Error: {error}")
            email_label = ""
            label_found = False
            break
        except Exception as error:
            logger.error(f"Unexpected error: {error}")
            email_label = ""
            label_found = False
            break
        
    if label_found:
        with app.app_context():
            email_data_nlp = {"email_id": email_id,
                    "sender": sender,
                    "subject": subject,
                    "content": full_content,
                    "label": email_label,
                    "processed": False}
            
            emails_db.emails_nlp.update_one({"email_id": email_data_nlp["email_id"]}, {"$set": email_data_nlp}, upsert=True)

    return email_label


def add_appropriate_label_to_email(email_id, label_id):
    try:
        body = {"addLabelIds": [label_id],
                "removeLabelIds": []}
        
        email = service.users().messages().modify(userId="me", id=email_id, body=body).execute()
        logger.debug(f"Email after adding label: {email}")
        return email
    
    except HttpError as error:
        logger.error(f"Error while adding label to email: {error}")
        return {"error": str(error)}
    except Exception as error:
        logger.error(f"Error exception: {error}")
        return {"error": str(error)}
    

def extract_text_html(part):
    temp_text_content = ""
    temp_html_content = ""
    
    if part.get("mimeType", "") == "text/plain":
        temp_text_content = base64.urlsafe_b64decode(part["body"].get("data", "") or "").decode("utf-8", errors="ignore").strip()
    elif part.get("mimeType", "") in ["text/x-amp-html", "text/html"]:
        temp_html_content = base64.urlsafe_b64decode(part["body"].get("data", "") or "").decode("utf-8", errors="ignore")
            
    return temp_text_content, temp_html_content
    
    
def process_parts(parts):
    attachments = []
    text_content = ""
    html_content = ""
    
    for part in parts:
        if "parts" in part:
            temp_text, temp_html, temp_attachments = process_parts(part["parts"])
            text_content += temp_text
            html_content += temp_html
            attachments.extend(temp_attachments)

        else:
            temp_text_content, temp_html_content = extract_text_html(part)
            text_content += temp_text_content
            html_content += temp_html_content
            
            if part.get("filename") != "":
                attachments.append((part["filename"], part["mimeType"], part["body"].get("attachmentId", ""), part["body"].get("data", "")))
                
    return text_content, html_content, attachments


def save_attachment(email_id, filename, mimeType, attachment_id="", data="", folder_id=GMAIL_ATTACHMENT_FOLDER_ID):    
    if attachment_id:
        attachment = service.users().messages().attachments().get(userId="me", messageId=email_id, id=attachment_id).execute()
        file_data = base64.urlsafe_b64decode(attachment.get("data", "").encode("utf-8"))
    
    elif data:
        file_data = base64.urlsafe_b64decode(data.encode("utf-8"))
    else:
        raise ValueError("Either attachment_id or data must be provided")
    
    file_metadata = {"name": filename}
    
    if folder_id:
        file_metadata["parents"] = [folder_id]

    media = MediaIoBaseUpload(io.BytesIO(file_data), mimetype=mimeType, resumable=True)

    uploaded_file = drive_service.files().create(body=file_metadata, media_body=media, fields="id, webViewLink").execute()

    return uploaded_file.get("id"), uploaded_file.get("webViewLink")
    
    
def process_single_email(email):
    attachments_details = []
    payload = email.get("payload", {})
    
    if payload["mimeType"] not in ["text/plain", "text/html"]:
        text_content, html_content, attachments = process_parts(payload.get("parts", []))
        
        for attachment in attachments:
            if attachment[0] and (attachment[1] or attachment[2]):
                drive_file_id, drive_file_link = save_attachment(email["id"], f"{email["id"]}_{attachment[0]}", attachment[1], attachment[2], attachment[3])
                attachments_details.append({"filename": attachment[0],
                                            "drive_file_id": drive_file_id,
                                            "drive_file_link": drive_file_link})
                
    else:
        if payload["mimeType"] == "text/plain":
            text_content = base64.urlsafe_b64decode(payload["body"].get("data", "") or "").decode("utf-8", errors="ignore")
            html_content = ""
        elif payload["mimeType"] == "text/html":
            html_content = base64.urlsafe_b64decode(payload["body"].get("data", "") or "").decode("utf-8", errors="ignore")
            text_content = ""
    
    subject = next((header["value"] for header in email["payload"].get("headers", []) if header["name"] == "Subject"), "")
    snippet = email.get("snippet", "")
    sender = next((header["value"] for header in email["payload"].get("headers", []) if header["name"] == "From"), "")
    reciever = next((header["value"] for header in email["payload"].get("headers", []) if header["name"] == "To"), "")
    timestamp = datetime.fromtimestamp(int(email["internalDate"]) / 1000, tz=timezone.utc).astimezone(timezone(timedelta(hours=5, minutes=30))).strftime("%d %B %Y, %I:%M:%S %p")
    
    categorise_email_with_label(email, text_content, html_content, sender, subject)
    
    email_data = {"email_id": email.get("id", ""),
                  "labelIds": email.get("labelIds", []),
                  "text_content": text_content,
                  "html_content": html_content,
                  "subject": subject,
                  "snippet": snippet,
                  "sender": sender,
                  "reciever": reciever,
                  "attachments": attachments_details,
                  "timestamp": timestamp}
    
    return email_data


def get_fetch_email_with_content(email_id: str):
     try:
         email = service.users().messages().get(userId="me", id=email_id, fields=fields).execute()
         logger.info(f"Using get_fetch_email_with_content: {email}")
         email_data = process_single_email(email)
         logger.debug(f"Email_data from process_single_email: {email_data}")
         return email_data
     
     except HttpError as error:
         logger.error(f"Error fetching email: {error}")
         return {"error": str(error)}, {"email": "empty"}
     except Exception as error:
         logger.error(f"Error Exception: {error}")
         return {"error": str(error)}, {"email": "empty"}
     
     
def get_fetch_email(email_id: str):
     try:
         email = service.users().messages().get(userId="me", id=email_id, fields=fields).execute()
         logger.info(f"Using get_fetch_email: {email}")
         return email
     
     except HttpError as error:
         logger.error(f"Error fetching email: {error}")
         return {"email": "empty", "error": error}
     except Exception as error:
         logger.error(f"Error Exception: {error}")
         return {"email": "empty", "error": error}
    

def get_new_emails(history_id):
    emails_db = get_db_emails()
    
    try:
        with app.app_context():
            last_history = emails_db.history.find_one({"_id": "latest"}, max_time_ms=5000)
            
        if last_history is None:
            if not history_id:
                profile = service.users().getProfile(userId="me").execute()
                last_history_id = profile.get("historyId")
            else:
                last_history_id = history_id
        else:
            last_history_id = last_history.get("historyId")
            
        if not last_history_id:
            return []
            
        response = service.users().history().list(userId="me", startHistoryId=last_history_id).execute()
        logger.debug(f"Response in get_new_emails: {response}")

        success = True
        
        if "history" in response:
            logger.debug("Yes history in response")
            emails = []
            for history in response.get("history", []):
                try:
                    if "messagesAdded" in history:
                        logger.info("Messages are added in history")
                        for messageAdded in history.get("messagesAdded", []):
                            partial_msg = messageAdded.get("message", {})
                            logger.debug(f"partial msg in messagesAdded: {partial_msg}")
                            msg_id = partial_msg.get("id", "")
                            logger.debug(f"message id when messageAdded called: {msg_id}")
                            email_data = get_fetch_email_with_content(msg_id)
                            logger.debug(f"full msg in messagesAdded: {email_data}")
                            emails.append(email_data)

                            if isinstance(email_data, dict) and "error" in email_data:
                                logger.error(f"Failed to fetch email {msg_id}, skipping history update")
                                success = False
                                continue
                             
                            with app.app_context():
                                logger.info("adding to all_emails database")
                                if "UNREAD" not in email_data.get("labelIds", []):
                                    data = {"email_id": email_data.get("email_id", ""),
                                            "full_email": email_data,
                                            "is_unread": False}
                                else:
                                    data = {"email_id": email_data.get("email_id", ""),
                                            "full_email": email_data,
                                            "is_unread": True}

                                logger.info(f"Data to append in database: {data}")
                                logger.info("next step of adding to all_emails database")
                                emails_db.all_emails.update_one({"email_id": data["email_id"]}, {"$set": data}, upsert=True)
                                
                    if "messagesDeleted" in history:
                        logger.info("Messages are removed from database")
                        for messageDeleted in history.get("messagesDeleted", []):
                            partial_msg = messageDeleted.get("message", {})
                            msg_id = partial_msg.get("id", "")
                            
                            if msg_id:
                                msg_deleted = emails_db.all_emails.delete_one({"email_id": msg_id})
                                
                                if msg_deleted.deleted_count == 1:
                                    logger.info(f"Email with id: {msg_id} is deleted from database")
                                else:
                                    logger.warning(f"Email with id: {msg_id} does not exists in database")
                                    
                            else:
                                logger.warning("No email id found in messagesDeleted's particular message")
                                
                    if "labelsAdded" in history:
                        logger.info("Labels are added from history")
                        for labelAdded in history.get("labelsAdded", []):
                            partial_msg = labelAdded.get("message", {})
                            labelIds = labelAdded.get("labelIds", [])
                            msg_id = partial_msg.get("id", "")
                            full_msg = get_fetch_email(msg_id)
                            
                            fetch_label_id = emails_db.all_emails.find_one({"email_id": msg_id},
                                                                           {"full_email.labelIds": 1, "_id": 0})

                            if isinstance(full_msg, dict) and "error" in full_msg:
                                logger.error(f"Failed to fetch email {msg_id}, skipping history update")
                                success = False
                                continue
                            
                            if "UNREAD" in labelIds:
                                existing_labels = fetch_label_id.get("full_email", {}).get("labelIds", [])
                                
                                updated_labels = list(set(existing_labels + labelIds))
                                
                                with app.app_context():
                                    emails_db.all_emails.update_one({"email_id": msg_id},
                                                                    {"$set": {
                                                                            "full_email.labelIds": updated_labels, 
                                                                            "is_unread": True}})
                                
                            else:
                                if "UNREAD" not in full_msg.get("labelIds", []):
                                    existing_labels = fetch_label_id.get("full_email", {}).get("labelIds", [])
                                
                                    updated_labels = list(set(existing_labels + labelIds))
                                    
                                    with app.app_context():
                                        emails_db.all_emails.update_one({"email_id": msg_id},
                                                                        {"$set": {
                                                                                "full_email.labelIds": updated_labels, 
                                                                                "is_unread": False}})
                                    
                                else:
                                    existing_labels = fetch_label_id.get("full_email", {}).get("labelIds", [])
                                
                                    updated_labels = list(set(existing_labels + labelIds))
                                    
                                    with app.app_context():
                                        emails_db.all_emails.update_one({"email_id": msg_id},
                                                                        {"$set": {
                                                                                "full_email.labelIds": updated_labels, 
                                                                                "is_unread": True}})

                    if "labelsRemoved" in history:
                        logger.info("Labels are removed from history")
                        for labelRemoved in history.get("labelsRemoved", []):
                            partial_msg = labelRemoved.get("message", {})
                            labelIds = labelRemoved.get("labelIds", [])
                            msg_id = partial_msg.get("id", "")
                            full_msg = get_fetch_email(msg_id)
                            
                            fetch_label_id = emails_db.all_emails.find_one({"email_id": msg_id},
                                                                           {"full_email.labelIds": 1, "_id": 0})

                            if isinstance(full_msg, dict) and "error" in full_msg:
                                logger.error(f"Failed to fetch email {msg_id}, skipping history update")
                                success = False
                                continue
                            
                            if "UNREAD" in labelIds:
                                existing_labels = fetch_label_id.get("full_email", {}).get("labelIds", [])
                                
                                updated_labels = list(set(existing_labels) - set(labelIds))
                                
                                with app.app_context():
                                    emails_db.all_emails.update_one({"email_id": msg_id},
                                                                    {"$set": {
                                                                            "full_email.labelIds": updated_labels, 
                                                                            "is_unread": False}})
                                
                            else:
                                if "UNREAD" not in full_msg.get("labelIds", []):
                                    existing_labels = fetch_label_id.get("full_email", {}).get("labelIds", [])
                                
                                    updated_labels = list(set(existing_labels) - set(labelIds))
                                    
                                    with app.app_context():
                                        emails_db.all_emails.update_one({"email_id": msg_id},
                                                                        {"$set": {
                                                                                "full_email.labelIds": updated_labels, 
                                                                                "is_unread": False}})
                                    
                                else:
                                    existing_labels = fetch_label_id.get("full_email", {}).get("labelIds", [])
                                
                                    updated_labels = list(set(existing_labels) - set(labelIds))
                                    
                                    with app.app_context():
                                        emails_db.all_emails.update_one({"email_id": msg_id},
                                                                        {"$set": {
                                                                                "full_email.labelIds": updated_labels, 
                                                                                "is_unread": True}})
                                
                except Exception as error:
                    logger.error(f"Error in fetching emails from history list. Continuing to next email. {error}")
                            
            latest_history_id = response.get("historyId") or last_history_id
            if latest_history_id:
                with app.app_context():
                    emails_db.history.update_one({"_id": "latest"}, {"$set": {"historyId": latest_history_id}}, upsert=True)
            if not success:
                logger.warning("Some emails failed, logged for retry, but historyId still advanced.")
                                
            return emails
        
        else:
            logger.warning("No history in response")
            with app.app_context():
                emails_db.history.update_one({"_id": "latest"}, {"$set": {"historyId": last_history_id}}, upsert=True)
            
        return []
                        
    except HttpError as error:
        logger.error(f"Error fetching email (get_new_emails): {error}")
        return []
    except Exception as error:
        logger.error(f"Error Exception: {error}")
        return []
    
    
def setup_gmail_watch():
    try:
        creds = authenticate_gmail()
        service = build("gmail", "v1", credentials=creds)
        
        request_body = {
            "topicName": "projects/email-oauth2-app/topics/gmail-manager",
        }
        
        response = service.users().watch(userId="me", body=request_body).execute()
        
        watch_request = {
        "labelIds": ["INBOX"],
        "topicName": "projects/email-oauth2-app/topics/gmail-manager"
        }
        
        response = service.users().watch(userId="me", body=watch_request).execute()
        logger.debug(f"Response from setup_gmail_watch: {response}")
        logger.debug(f"Watch Request: {watch_request}")
        return response

    except Exception as e:
        logger.error(f"Error setuping up gmail watch: {e}")
        return ""
    
    
@app.route("/")
def home():
    emails_db = get_db_emails()
    return "Gmail webhook is running and Connected to MongoDB"

@app.route("/get-gmails", methods=["POST"])
def get_email_history_id():
    try:
        logger.info("Recieved Gmail notification")
        data = request.get_json()
        logger.debug(f"Recieved Gmail notification: {json.dumps(data, indent=4)}")
        
        if "message" in data:
            message_data = base64.urlsafe_b64decode(data["message"]["data"]).decode("utf-8")
            history_id = json.loads(message_data).get("historyId", "")
        
        if history_id:
            logger.debug(f"History ID: {history_id}")
            emails = get_new_emails(history_id)
            return jsonify({"status": "success", "emails": emails}), 200
        
        return jsonify({"status": "no historyId found"}), 400
    
    except Exception as error:
        logger.error(f"Error: {error}")
        return jsonify({"error": str(error)}), 500
    
    
@app.route("/health-check")
def health_check():
    return "Health Checked!", 200


with app.app_context():
    try:
        logger.info("Setting up Gmail watch")
        scheduler = BackgroundScheduler()
        scheduler.add_job(func=setup_gmail_watch, trigger="interval", hours=6)
        scheduler.start()

        setup_gmail_watch()
    except Exception as error:
        logger.critical(f"Failed to setup Gmail watch: {error}")

if __name__ == '__main__':
    serve(app, host="0.0.0.0", port=6000, channel_timeout=60)


# if not working then run this in cmd    curl -X POST "https://gmail-notifications.onrender.com/get-gmails" -H "Content-Type: application/json" -d "{\"message\": {\"data\": \"eyJoaXN0b3J5SWQiOiAiMTIzNDU2In0=\"}}"