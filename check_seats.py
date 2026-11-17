"""Check Northeastern Banner for open seats and send a phone notification via ntfy.sh.

Reads classes.txt (one class per line: TERM SUBJECT NUMBER CRN), e.g.
    202730 ME 3455 30428
Needs env var NTFY_TOPIC (the topic name you subscribed to in the ntfy app).
Set TEST=1 to always send a status notification (to check it works).
"""
import http.cookiejar
import json
import os
import sys
import urllib.parse
import urllib.request

BASE = "https://nubanner.neu.edu/StudentRegistrationSsb/ssb"


def fetch_sections(term, subject, number):
    # Fresh session per search: Banner remembers the last search per session.
    jar = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
    opener.addheaders = [("User-Agent", "seat-tracker")]
    opener.open(f"{BASE}/term/search?mode=search",
                data=urllib.parse.urlencode({"term": term}).encode(), timeout=30)
    q = urllib.parse.urlencode({
        "txt_term": term, "txt_subject": subject, "txt_courseNumber": number,
        "pageOffset": 0, "pageMaxSize": 100,
    })
    with opener.open(f"{BASE}/searchResults/searchResults?{q}", timeout=30) as r:
        return json.load(r).get("data") or []


def notify(topic, title, message, priority="high"):
    req = urllib.request.Request(
        f"https://ntfy.sh/{topic}", data=message.encode(),
        headers={"Title": title, "Priority": priority, "Tags": "rotating_light",
                 "Click": "https://nubanner.neu.edu/StudentRegistrationSsb/ssb/registration"})
    urllib.request.urlopen(req, timeout=30)


def main():
    topic = os.environ["NTFY_TOPIC"]
    test = os.environ.get("TEST") == "1"
    here = os.path.dirname(os.path.abspath(__file__))
    lines = [l.split("#")[0].split() for l in open(os.path.join(here, "classes.txt"))]
    classes = [l for l in lines if l]

    status, open_seats, open_wait = [], [], []
    cache = {}  # one Banner search per course, not per CRN
    for term, subject, number, crn in classes:
        key = (term, subject.upper(), number)
        if key not in cache:
            cache[key] = fetch_sections(*key)
        sec = next((s for s in cache[key] if s["courseReferenceNumber"] == crn), None)
        if sec is None:
            msg = f"{subject} {number} CRN {crn}: not found in term {term}"
            print(msg)
            status.append(msg)
            continue
        seats, cap = sec["seatsAvailable"], sec["maximumEnrollment"]
        wait = sec.get("waitAvailable", 0)
        label = f"{subject} {number} CRN {crn}"
        msg = f"{label}: {seats}/{cap} seats open, {wait} waitlist spots"
        print(msg)
        status.append(msg)
        if seats > 0:
            open_seats.append(f"{label}: {seats} seat(s)")
        elif wait > 0:
            open_wait.append(f"{label}: {wait} waitlist spot(s)")

    # One combined notification instead of one per section
    if open_seats:
        notify(topic, f"SEAT OPEN ({len(open_seats)} section(s))",
               "Register now!\n" + "\n".join(open_seats), priority="urgent")
    if open_wait:
        notify(topic, f"Waitlist open ({len(open_wait)} section(s))", "\n".join(open_wait))

    if test:
        notify(topic, "Seat tracker test", "\n".join(status) or "No classes listed", priority="default")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:  # show the error in the GitHub Actions log
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
