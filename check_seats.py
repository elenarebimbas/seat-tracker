"""Check Northeastern Banner for open seats and send a phone notification via ntfy.sh.

Reads classes.txt (one class per line: TERM SUBJECT NUMBER CRN), e.g.
    202730 ME 3455 30428
Env vars:
    NTFY_TOPIC   the topic name you subscribed to in the ntfy app (required)
    TEST=1       send a status notification on the first check (to confirm it works)
    INTERVAL     seconds between checks (default 60, minimum 30)
    RUN_MINUTES  keep checking for this many minutes, then exit (default 0 = check once)
"""
import http.cookiejar
import json
import os
import sys
import time
import urllib.parse
import urllib.request

BASE = "https://nubanner.neu.edu/StudentRegistrationSsb/ssb"
REMIND_EVERY = 5 * 60  # while a seat stays open, re-alert every 5 minutes


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


def load_classes():
    here = os.path.dirname(os.path.abspath(__file__))
    lines = [l.split("#")[0].split() for l in open(os.path.join(here, "classes.txt"))]
    return [l for l in lines if l]


def check_once(classes):
    """Returns (status lines, open-seat lines, open-waitlist lines)."""
    status, open_seats, open_wait = [], [], []
    cache = {}  # one Banner search per course, not per CRN
    for term, subject, number, crn in classes:
        key = (term, subject.upper(), number)
        if key not in cache:
            cache[key] = fetch_sections(*key)
        sec = next((s for s in cache[key] if s["courseReferenceNumber"] == crn), None)
        label = f"{subject} {number} CRN {crn}"
        if sec is None:
            status.append(f"{label}: not found in term {term}")
            continue
        seats, cap = sec["seatsAvailable"], sec["maximumEnrollment"]
        wait = sec.get("waitAvailable", 0)
        status.append(f"{label}: {seats}/{cap} seats open, {wait} waitlist spots")
        if seats > 0:
            open_seats.append(f"{label}: {seats} seat(s)")
        elif wait > 0:
            open_wait.append(f"{label}: {wait} waitlist spot(s)")
    return status, open_seats, open_wait


def main():
    topic = os.environ["NTFY_TOPIC"]
    test = os.environ.get("TEST") == "1"
    interval = max(30, int(os.environ.get("INTERVAL") or 60))
    run_minutes = float(os.environ.get("RUN_MINUTES") or 0)
    classes = load_classes()

    end = time.time() + run_minutes * 60
    last_open, last_alert = None, 0.0
    first, failures = True, 0
    while True:
        try:
            status, open_seats, open_wait = check_once(classes)
            failures = 0
        except Exception as e:
            failures += 1
            print(f"{time.strftime('%H:%M:%S')} check failed: {e}", file=sys.stderr)
            if failures >= 10:  # Banner down for ~10 min: stop so the error shows in GitHub
                raise
        else:
            print(f"{time.strftime('%H:%M:%S')} {len(open_seats)} section(s) with seats "
                  f"({len(status)} checked)")
            if first:
                print("\n".join(status))

            now_open = tuple(open_seats + open_wait)
            changed = now_open != last_open
            # Alert right away when something new opens; remind every 5 min while open.
            if now_open and (changed or time.time() - last_alert >= REMIND_EVERY):
                if open_seats:
                    notify(topic, f"SEAT OPEN ({len(open_seats)} section(s))",
                           "Register now!\n" + "\n".join(open_seats), priority="urgent")
                if open_wait:
                    notify(topic, f"Waitlist open ({len(open_wait)} section(s))",
                           "\n".join(open_wait))
                last_alert = time.time()
            last_open = now_open

            if first and test:
                notify(topic, "Seat tracker test", "\n".join(status) or "No classes listed",
                       priority="default")
            first = False

        if time.time() + interval >= end:
            break
        time.sleep(interval)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:  # show the error in the GitHub Actions log
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
