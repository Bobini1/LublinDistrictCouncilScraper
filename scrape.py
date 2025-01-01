import datetime

from bs4 import BeautifulSoup
import requests

from event import Event

base_url = "https://lublin.eu/"
start_month = datetime.datetime.now().month
start_year = datetime.datetime.now().year
headers = {'User-Agent': 'Mozilla/5.0'}


def get_description_and_place(href):
    soup = BeautifulSoup(requests.get(f"{base_url}{href}", headers=headers).content, "html.parser")
    title = soup.select_one(".title").text.strip()
    # module-section bizcard-details
    header = soup.find("div", class_="module-section bizcard-details")
    place = ""
    for label in header.find_all("span", class_="label"):
        if "Miejsce" in label.text:
            place = label.find_next_sibling("span").text.strip()
    container = soup.find("div", class_="bizcard-module bizcard-single module-calendar-events")
    paragraphs = container.find_all("p")
    description = "".join([p.text for p in paragraphs])
    description = description.replace(title, "").replace("\r\n", "\n").strip()
    return description, place


def get_events(month, year):
    url = f"{base_url}rady-dzielnic/posiedzenia/{month:02}-{year},miesiac.html"
    soup = BeautifulSoup(requests.get(url, headers=headers).content, "html.parser")
    events = soup.find_all("div", class_="event")
    while next_page := soup.find("a", text="następna strona"):
        url = f"{base_url}{next_page['href']}"
        soup = BeautifulSoup(requests.get(url, headers=headers).content, "html.parser")
        events.extend(soup.find_all("div", class_="event"))
    event_objects = []
    for event in events:
        date = event.select_one(".event-date").text.strip()
        time = event.select_one(".event-time").text.strip()
        dt = datetime.datetime.strptime(f"{date} {time}", "%d-%m-%Y %H:%M")
        title = event.select_one(".event-title").text.split(" - ")[0].strip()
        href = event.select_one(".event-title a")["href"]
        description, place = get_description_and_place(href)
        event_objects.append(Event(dt, title, description, place))
    return event_objects


def increment_month(month, year):
    month += 1
    if month == 13:
        month = 1
        year += 1
    return month, year


def get_all_future_events():
    events = []
    month, year = start_month, start_year
    while month_events := get_events(month, year):
        events.extend(month_events)
        month, year = increment_month(month, year)
    return events


def main():
    events = get_all_future_events()
    for event in events:
        print(event)
        print()


if __name__ == "__main__":
    main()
