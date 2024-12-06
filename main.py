from scrape import get_all_future_events
from upload_events import Calendar


def main():
    # Get all future events
    events = get_all_future_events()

    # Upload events to the calendar
    calendar = Calendar("ef0984b0b800fa348809b14eacf2a0b274a8aaf1954794a39f84ffb93e04952c@group.calendar.google.com")
    for event in events:
        calendar.send_event(event)


if __name__ == "__main__":
    main()
