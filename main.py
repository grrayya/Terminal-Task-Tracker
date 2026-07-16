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
SNOOZE_TIME_SECONDS = 14400 

SCOPES = [
    'https://www.googleapis.com/auth/calendar.readonly',
    'https://www.googleapis.com/auth/gmail.readonly'
]

def load_db():
    if not os.path.exists(DB_PATH):
        return {"tasks": {}}
    with open(DB_PATH, 'r') as f:
        return json.load(f)

def save_db(db):
    with open(DB_PATH, 'w') as f:
        json.dump(db, f, indent=4)

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
            subject_line = next((h['value'] for h in headers if h['name'] == 'Subject'), "No Subject")
            
            pending_todos.append({
                "id": f"mail_{thread['id']}",
                "title": f"Email: {subject_line}",
                "source": "Gmail"
            })

    except HttpError as err:
        print(f"Skipping emails, Gmail API failed: {err}")

    return pending_todos

def process_tasks():
    db = load_db()
    current_time = time.time()
    
    incoming_tasks = fetch_external_tasks()
    for task in incoming_tasks:
        if task["id"] not in db["tasks"]:
            db["tasks"][task["id"]] = {
                "title": task["title"],
                "source": task["source"],
                "status": "new",
                "estimated_mins": 0,
                "actual_mins": 0,
                "ping_time": 0
            }

    for task_id, data in db["tasks"].items():
        if data["status"] == "new" or (data["status"] == "snoozed" and current_time >= data["ping_time"]):
            print(f"\n🔔 NEW TASK: {data['title']} ({data['source']})")
            user_input = input("How many minutes will this take? (Enter number, or type 'later'): ").strip().lower()
            
            if user_input == 'later':
                data["status"] = "snoozed"
                data["ping_time"] = current_time + SNOOZE_TIME_SECONDS
                print("Got it. I'll ping you about this again later.")
            elif user_input.isdigit():
                data["status"] = "active"
                data["estimated_mins"] = int(user_input)
                print(f"Tracked! Estimated: {data['estimated_mins']} mins. Get to work!")
            else:
                print("Invalid input. Skipping for now.")

        elif data["status"] == "active":
            print(f"\n✅ ACTIVE TASK: {data['title']}")
            is_done = input("Did you finish this? (y/n): ").strip().lower()
            
            if is_done == 'y':
                actual_time = input("Awesome. How many minutes did it *actually* take?: ").strip()
                if actual_time.isdigit():
                    data["status"] = "completed"
                    data["actual_mins"] = int(actual_time)
                    data["date_finished"] = datetime.datetime.now().strftime("%Y-%m-%d")
                    print("Data logged. Great job!")
                else:
                    print("Please enter a valid number next time.")

    save_db(db)

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
    if daily_drift > 0:
        drift_text = f"took {daily_drift}m longer than expected" 
    elif daily_drift < 0:
        drift_text = f"finished {abs(daily_drift)}m faster than expected"
    else:
        drift_text = "hit your estimates perfectly"
    
    print("-" * 35)
    print(f"Total Est: {total_est}m | Total Actual: {total_actual}m")
    print(f"Verdict: You {drift_text} overall.\n")


if __name__ == "__main__":
    print("Tracker active. (Press Ctrl+C to print daily summary and exit)")
    try:
        while True:
            process_tasks()
            time.sleep(300) 
    except KeyboardInterrupt:
        print("\nWrapping up...")
        db = load_db()
        print_end_of_day_report(db)
        print("Shutting down tracker.")
