from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
import datetime
import pytz
from zoneinfo import ZoneInfo
from event import Event

# If modifying these SCOPES, delete the token.json file.
SCOPES = ['https://www.googleapis.com/auth/calendar']
calendar_id = "ef0984b0b800fa348809b14eacf2a0b274a8aaf1954794a39f84ffb93e04952c@group.calendar.google.com"
time_zone = 'Europe/Warsaw'


class Calendar:
    EVENT_LENGTH = 2  # Event length in hours

    def __init__(self):
        # Authenticate and create the service
        creds = None
        if creds := load_credentials():
            print("Using existing credentials.")
        else:
            print("No existing credentials. Running authentication flow.")
            creds = authenticate_user()

        self.service = build('calendar', 'v3', credentials=creds)

    def send_event(self, event: Event):
        dt_tz = event.datetime.replace(tzinfo=ZoneInfo(time_zone))
        if check_duplicate_event(self.service, event.title, dt_tz, dt_tz + datetime.timedelta(days=2)):
            return
        # Event details
        event = {
            'summary': event.title,
            'location': event.place,
            'description': event.description,
            'start': {
                'dateTime': dt_tz.isoformat(),
                'timeZone': time_zone,
            },
            'end': {
                'dateTime': (dt_tz + datetime.timedelta(hours=Calendar.EVENT_LENGTH)).isoformat(),
                'timeZone': time_zone,
            },
        }

        # Insert the event
        created_event = self.service.events().insert(calendarId=calendar_id, body=event).execute()
        print(f"Event created: {created_event.get('htmlLink')}")


def check_duplicate_event(service, event_summary, start_datetime, end_datetime):
    """Checks if an event with the same summary exists in the given time range."""
    start_time = start_datetime.isoformat()
    end_time = end_datetime.isoformat()

    # Fetch events within the time range
    events_result = service.events().list(
        calendarId=calendar_id,
        timeMin=start_time,
        timeMax=end_time,
        singleEvents=True,
        orderBy='startTime'
    ).execute()

    events = events_result.get('items', [])

    # Check if any event matches the summary
    for event in events:
        if event.get('summary') == event_summary:
            start = event.get('start').get('dateTime')
            if datetime.datetime.fromisoformat(event.get('start').get('dateTime')) != start_datetime:
                # change the event time
                event['start']['dateTime'] = start_datetime.isoformat()
                event['end']['dateTime'] = (start_datetime + datetime.timedelta(hours=Calendar.EVENT_LENGTH)).isoformat()
                service.events().update(calendarId=calendar_id, eventId=event['id'], body=event).execute()
                print(f"Event '{event_summary}' time changed.")
            return True  # Duplicate found
    return False


def authenticate_user():
    """Runs the OAuth 2.0 flow to authenticate the user."""
    flow = InstalledAppFlow.from_client_secrets_file(
        'credentials.json', SCOPES)
    creds = flow.run_local_server(port=0)
    save_credentials(creds)
    return creds


def save_credentials(creds):
    """Save the credentials to a file."""
    with open('token.json', 'w') as token_file:
        token_file.write(creds.to_json())


def load_credentials():
    """Load saved credentials from file."""
    try:
        creds = Credentials.from_authorized_user_file('token.json', SCOPES)
        return creds
    except FileNotFoundError:
        return None
