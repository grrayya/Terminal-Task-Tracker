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
def print_end_of_day_report(db):
    today_str = datetime.datetime.now().strftime("%Y-%m-%d")
    
    finished_today = {k: v for k, v in db["tasks"].items() 
                      if v.get("status") == "completed" and v.get("date_finished") == today_str}
    
    if not finished_today:
        print("\nNo tasks wrapped up today.")
        return

    print(f"\n--- End of Day Summary ({today_str}) ---")
    total_est = 0
    total_actual = 0
    
    for tid, info in finished_today.items():
        est = info['estimated_mins']
        act = info['actual_mins']
        drift = act - est
        
        trend = f"+{drift}m over" if drift > 0 else f"{abs(drift)}m under" if drift < 0 else "spot on"
        
        print(f"• {info['title']}")
        print(f"  Est: {est}m | Actual: {act}m ({trend})")
        
        total_est += est
        total_actual += act

    daily_drift = total_actual - total_est
    drift_text = f"took {daily_drift}m longer than expected" if daily_drift > 0 else f"finished {abs(daily_drift)}m faster than expected"
    
    print("-" * 35)
    print(f"Total Est: {total_est}m | Total Actual: {total_actual}m")
    print(f"Verdict: You {drift_text} overall.\n")
