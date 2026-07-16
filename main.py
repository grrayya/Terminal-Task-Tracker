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

# NOTICE: Scope changed from calendar.readonly to calendar.events
# DELETE YOUR token.json FILE SO IT CAN RE-AUTHENTICATE!
SCOPES = [
    'https://www.googleapis.com/auth/calendar.events',
    'https://www.googleapis.com/auth/gmail.readonly'
]

CATEGORIES = {
    'g': 'GitHub',
    'p': 'Pengwins',
    'u': 'Uni',
    'o': 'Other'
}

class JsonStorage:
    def __init__(self, filepath):
        self.filepath = filepath

    def load(self):
        if not os.path.exists(self.filepath):
            return {"tasks": {}}
        with open(self.filepath, 'r') as f:
            return json.load(f)

    def save(self, data):
        with open(self.filepath, 'w') as f:
            json.dump(data, f, indent=4)


class GoogleAPI:
    def __init__(self, scopes):
        self.scopes = scopes
        self.creds = self._get_credentials()

    def _get_credentials(self):
        creds = None
        if os.path.exists('token.json'):
            creds = Credentials.from_authorized_user_file('token.json', self.scopes)
            
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                flow = InstalledAppFlow.from_client_secrets_file('credentials.json', self.scopes)
                creds = flow.run_local_server(port=0)
                
            with open('token.json', 'w') as token:
                token.write(creds.to_json())
        return creds

    def fetch_tasks(self):
        pending_todos = []

        try:
            cal_service = build('calendar', 'v3', credentials=self.creds)
            now_utc = datetime.datetime.utcnow().isoformat() + 'Z' 
            cal_response = cal_service.events().list(
                calendarId='primary', timeMin=now_utc,
                maxResults=5, singleEvents=True,
                orderBy='startTime'
            ).execute()
            
            for meeting in cal_response.get('items', []):
                title = meeting.get('summary', 'Blocked Time')
                pending_todos.append({
                    "id": f"cal_{meeting['id']}",
                    "title": f"Meeting: {title}",
                    "source": "Calendar"
                })
        except HttpError as err:
            print(f"Calendar API choked: {err}")

        try:
            gmail_service = build('gmail', 'v1', credentials=self.creds)
            inbox_query = gmail_service.users().messages().list(
                userId='me', q='is:unread in:inbox', maxResults=5
            ).execute()
            
            for thread in inbox_query.get('messages', []):
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

    def create_calendar_event(self, title, duration_mins):
        try:
            cal_service = build('calendar', 'v3', credentials=self.creds)
            
            start_time = datetime.datetime.utcnow()
            end_time = start_time + datetime.timedelta(minutes=duration_mins)
            
            event_body = {
                'summary': title,
                'start': {
                    'dateTime': start_time.isoformat() + 'Z',
                    'timeZone': 'UTC',
                },
                'end': {
                    'dateTime': end_time.isoformat() + 'Z',
                    'timeZone': 'UTC',
                },
            }
            
            event_result = cal_service.events().insert(calendarId='primary', body=event_body).execute()
            print(f"✅ Synced to Google Calendar! ({event_result.get('htmlLink')})")
        except HttpError as err:
            print(f"Failed to create calendar event: {err}")


class DailyReport:
    @staticmethod
    def generate(db_state):
        today_str = datetime.datetime.now().strftime("%Y-%m-%d")
        
        finished_today = [task for task in db_state["tasks"].values() 
                          if task.get("status") == "completed" and task.get("date_finished") == today_str]
        
        if not finished_today:
            print("\nNo tasks wrapped up today.")
            return

        print(f"\n--- End of Day Summary ({today_str}) ---")
        
        categorized_tasks = {}
        for task in finished_today:
            cat = task.get("category", "Other")
            if cat not in categorized_tasks:
                categorized_tasks[cat] = []
            categorized_tasks[cat].append(task)

        grand_est = 0
        grand_actual = 0

        for cat_name, tasks in categorized_tasks.items():
            print(f"\n[{cat_name.upper()}]")
            cat_est = 0
            cat_actual = 0
            
            for info in tasks:
                est = info['estimated_mins']
                act = info['actual_mins']
                drift = act - est
                trend = f"+{drift}m over" if drift > 0 else f"{abs(drift)}m under" if drift < 0 else "spot on"
                
                print(f"  • {info['title']} | Est: {est}m -> Actual: {act}m ({trend})")
                cat_est += est
                cat_actual += act
            
            print(f"  > {cat_name} Totals: {cat_est}m estimated vs {cat_actual}m actual.")
            grand_est += cat_est
            grand_actual += cat_actual

        daily_drift = grand_actual - grand_est
        if daily_drift > 0:
            drift_text = f"took {daily_drift}m longer than expected" 
        elif daily_drift < 0:
            drift_text = f"finished {abs(daily_drift)}m faster than expected"
        else:
            drift_text = "hit your estimates perfectly"
        
        print("\n" + "-" * 40)
        print(f"GRAND TOTAL: {grand_est}m Est | {grand_actual}m Actual")
        print(f"Verdict: You {drift_text} overall.\n")


class TaskTracker:
    def __init__(self, storage, api):
        self.storage = storage
        self.api = api

    def run_cycle(self):
        db = self.storage.load()
        current_time = time.time()
        
        incoming_tasks = self.api.fetch_tasks()
        for task in incoming_tasks:
            if task["id"] not in db["tasks"]:
                db["tasks"][task["id"]] = {
                    "title": task["title"],
                    "source": task["source"],
                    "status": "new",
                    "category": "Other",
                    "estimated_mins": 0,
                    "actual_mins": 0,
                    "ping_time": 0
                }

        for task_id, data in db["tasks"].items():
            if data["status"] == "new" or (data["status"] == "snoozed" and current_time >= data["ping_time"]):
                print(f"\n🔔 NEW TASK: {data['title']} ({data['source']})")
                
                if data["status"] == "new":
                    cat_input = input("Category - [G]itHub, [P]engwins, [U]ni, or [O]ther?: ").strip().lower()
                    data["category"] = CATEGORIES.get(cat_input, "Other")

                user_input = input("How many minutes will this take? (Enter number, or type 'later'): ").strip().lower()
                
                if user_input == 'later':
                    data["status"] = "snoozed"
                    data["ping_time"] = current_time + SNOOZE_TIME_SECONDS
                    print("Got it. I'll ping you about this again later.")
                elif user_input.isdigit():
                    data["status"] = "active"
                    data["estimated_mins"] = int(user_input)
                    print(f"[{data['category']}] Tracked! Estimated: {data['estimated_mins']} mins. Get to work!")
                else:
                    print("Invalid input. Skipping for now.")

            elif data["status"] == "active":
                print(f"\n✅ ACTIVE TASK: [{data['category']}] {data['title']}")
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

        self.storage.save(db)


if __name__ == "__main__":
    storage_engine = JsonStorage(DB_PATH)
    google_api = GoogleAPI(SCOPES)
    app = TaskTracker(storage_engine, google_api)

    try:
        while True:
            app.run_cycle()
            
            print("\n" + "="*40)
            print("Action Menu:")
            print("  [Enter] Refresh APIs & check tasks")
            print("  [a]     Add new task to Google Calendar")
            print("  [q]     Quit and print daily summary")
            print("="*40)
            
            cmd = input("> ").strip().lower()
            
            if cmd == 'a':
                new_title = input("Task title: ").strip()
                new_duration = input("Expected duration in minutes (default 30): ").strip()
                parsed_duration = int(new_duration) if new_duration.isdigit() else 30
                
                print("Sending to Google...")
                google_api.create_calendar_event(new_title, parsed_duration)
                print("Done. It will appear in your queue on the next refresh.")
                
            elif cmd == 'q':
                raise KeyboardInterrupt
                
    except KeyboardInterrupt:
        print("\nWrapping up...")
        final_state = storage_engine.load()
        DailyReport.generate(final_state)
        print("Shutting down tracker.")
