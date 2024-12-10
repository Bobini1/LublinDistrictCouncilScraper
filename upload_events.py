from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
import datetime
import pytz
from zoneinfo import ZoneInfo
from event import Event

# If modifying these SCOPES, delete the token.json file.
SCOPES = ['https://www.googleapis.com/auth/calendar']
time_zone = 'Europe/Warsaw'


class Calendar:
    EVENT_LENGTH = 2  # Event length in hours

    def __init__(self, calendar_id):
        self.calendar_id = calendar_id
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
        if self._check_duplicate_event(event.title, dt_tz, dt_tz + datetime.timedelta(days=2)):
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
            'transparency': 'transparent'
        }

        # Insert the event
        created_event = self.service.events().insert(calendarId=self.calendar_id, body=event).execute()
        print(f"Event created: {created_event.get('htmlLink')}")


    def _check_duplicate_event(self, event_summary, start_datetime, end_datetime):
        """Checks if an event with the same summary exists in the given time range."""
        start_time = start_datetime.isoformat()
        end_time = end_datetime.isoformat()

        # Fetch events within the time range
        events_result = self.service.events().list(
            calendarId=self.calendar_id,
            timeMin=start_time,
            timeMax=end_time,
            singleEvents=True,
            orderBy='startTime'
        ).execute()

        events = events_result.get('items', [])

        # Check if any event matches the summary
        for event in events:
            if event.get('summary') == event_summary:
                if datetime.datetime.fromisoformat(event.get('start').get('dateTime')) != start_datetime:
                    # change the event time
                    event['start']['dateTime'] = start_datetime.isoformat()
                    event['end']['dateTime'] = (start_datetime + datetime.timedelta(hours=Calendar.EVENT_LENGTH)).isoformat()
                    self.service.events().update(calendarId=self.calendar_id, eventId=event['id'], body=event).execute()
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
