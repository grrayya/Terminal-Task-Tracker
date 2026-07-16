import time
import json
import os
import datetime
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

DB_PATH = "task_log.json"

SCOPES = [
    'https://www.googleapis.com/auth/calendar.readonly',
    'https://www.googleapis.com/auth/gmail.readonly'
]

def get_credentials():
    creds = None
    if os.path.exists('token.json'):
        creds = Credentials.from_authorized_user_file('token.json', SCOPES)
        
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file('credentials.json', SCOPES)
            creds = flow.run_local_server(port=0)
            
        with open('token.json', 'w') as token:
            token.write(creds.to_json())
    return creds

def fetch_external_tasks():
    creds = get_credentials()
    pending_todos = []

    try:
        cal_service = build('calendar', 'v3', credentials=creds)
        now_utc = datetime.datetime.utcnow().isoformat() + 'Z' 
        
        cal_response = cal_service.events().list(
            calendarId='primary', timeMin=now_utc,
            maxResults=5, singleEvents=True,
            orderBy='startTime'
        ).execute()
        
        upcoming_meetings = cal_response.get('items', [])
        for meeting in upcoming_meetings:
            # sometimes meetings don't have a summary if the time is just blocked off
            title = meeting.get('summary', 'Blocked Time')
            pending_todos.append({
                "id": f"cal_{meeting['id']}",
                "title": f"Meeting: {title}",
                "source": "Calendar"
            })

    except HttpError as err:
        print(f"Calendar API choked: {err}")


    try:
        gmail_service = build('gmail', 'v1', credentials=creds)
        inbox_query = gmail_service.users().messages().list(
            userId='me', q='is:unread in:inbox', maxResults=5
        ).execute()
        
        unread_threads = inbox_query.get('messages', [])

        for thread in unread_threads:
            thread_meta = gmail_service.users().messages().get(
                userId='me', id=thread['id'], format='metadata', 
                metadataHeaders=['Subject']
            ).execute()
            
            headers = thread_meta.get('payload', {}).get('headers', [])
            
            # hack to pull out just the subject string from the headers array
            subject_line = next((h['value'] for h in headers if h['name'] == 'Subject'), "No Subject")
            
            pending_todos.append({
                "id": f"mail_{thread['id']}",
                "title": f"Email: {subject_line}",
                "source": "Gmail"
            })

    except HttpError as err:
        print(f"Skipping emails, Gmail API failed: {err}")

    return pending_todos
