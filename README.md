# Terminal-Task-Tracker

A background terminal loop that pulls upcoming Google Calendar events and unread Gmails, prompting for time estimates and tracking actual completion times to improve time management.

#why i built it 
i want to a program that assist in making sure i dont forget anything and learn not to over and underestimate how long a task might take. 

## Setup

1. Install the Google API client libraries:
   `pip install google-api-python-client google-auth-httplib2 google-auth-oauthlib`
2. Create a Google Cloud project, enable the Calendar and Gmail APIs.
3. Download your OAuth Desktop client credentials and save them in the root directory as `credentials.json`.

## Usage

Run the script in the background of your terminal:
`python main.py`

On the first run, it will open a browser window to authenticate with your Google account. It generates a local `token.json` for future runs and maintains state in a local `task_log.json` file.
