from scrape import get_all_future_events
from upload_events import Calendar


def main():
    # Get all future events
    events = get_all_future_events()

    # Upload events to the calendar
    calendar = Calendar()
    for event in events:
        calendar.send_event(event)


if __name__ == "__main__":
    main()
