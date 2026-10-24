"""Pull activities, daily summaries and body composition from Garmin Connect
into data/garmin.json. Also writes an unencrypted docs/data.js (git-ignored) so
docs/index.html opens straight from disk; the Netlify build encrypts its own copy.

Auth, first match wins:
  1. Saved tokens in $GARMIN_TOKEN_DIR (default ~/.garminconnect)
  2. $GARMIN_TOKENS - the token JSON printed by `python fetch_garmin.py --login`
  3. $GARMIN_EMAIL + $GARMIN_PASSWORD (prompts for an MFA code when run interactively)

Usage:
  python fetch_garmin.py --login        # one-time, local: log in and print the token JSON
  python fetch_garmin.py                # incremental sync (first run pulls --days back)
  python fetch_garmin.py --days 730     # first run / full refresh of the last 730 days
"""

import argparse
import base64
import getpass
import json
import os
import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path

from garminconnect import Garmin, GarminConnectAuthenticationError

ROOT = Path(__file__).resolve().parent
DATA_JSON = ROOT / "data" / "garmin.json"
DATA_JS = ROOT / "docs" / "data.js"
TOKEN_DIR = Path(os.path.expanduser(os.getenv("GARMIN_TOKEN_DIR", "~/.garminconnect")))
# Re-fetch a few recent days every sync: today's summary is partial until the day ends.
OVERLAP_DAYS = 3


def connect(interactive: bool) -> Garmin:
    email = os.getenv("GARMIN_EMAIL")
    password = os.getenv("GARMIN_PASSWORD")
    if interactive:
        email = email or input("Garmin email: ")
        password = password or getpass.getpass("Garmin password: ")

    garmin = Garmin(
        email,
        password,
        prompt_mfa=(lambda: input("MFA code: ")) if interactive else None,
    )
    if (TOKEN_DIR / "garmin_tokens.json").exists():
        garmin.login(str(TOKEN_DIR))
    elif os.getenv("GARMIN_TOKENS", "").strip():
        tokens = check_tokens(os.environ["GARMIN_TOKENS"])
        try:
            garmin.login(tokens)
        except GarminConnectAuthenticationError:
            sys.exit(
                "GARMIN_TOKENS was rejected by Garmin (expired or revoked). "
                "Run `python fetch_garmin.py --login` again and replace the GARMIN_TOKENS secret."
            )
    else:
        garmin.login(str(TOKEN_DIR))

    # Persist (possibly refreshed) tokens so the next run skips the SSO login.
    TOKEN_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)
    garmin.client.dump(str(TOKEN_DIR))
    return garmin


def check_tokens(raw: str) -> str:
    """Validate the GARMIN_TOKENS secret and explain what is wrong without printing it."""
    tokens = raw.strip()
    if not tokens.startswith("{"):
        sys.exit(
            "GARMIN_TOKENS is not the token JSON. Paste only the line printed by "
            '`python fetch_garmin.py --login`, starting with {"di_token" and ending with }.'
        )
    try:
        data = json.loads(tokens)
    except json.JSONDecodeError:
        sys.exit("GARMIN_TOKENS is cut off or not valid JSON. Copy the whole line again, from { to }.")
    if not data.get("di_refresh_token"):
        sys.exit("GARMIN_TOKENS has no refresh token. Run `python fetch_garmin.py --login` again and copy its output.")
    try:  # the access token is a JWT; its expiry is not secret
        payload = data["di_token"].split(".")[1]
        exp = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))["exp"]
        print(f"GARMIN_TOKENS: access token expires {datetime.fromtimestamp(exp).isoformat(timespec='minutes')}")
    except Exception:
        pass
    return tokens


def iso(d: date) -> str:
    return d.isoformat()


def num(value, scale=1.0, digits=1):
    return None if value is None else round(value * scale, digits)


def fetch_activities(garmin: Garmin, start: date, end: date) -> list[dict]:
    rows = []
    for a in garmin.get_activities_by_date(iso(start), iso(end)):
        speed = a.get("averageSpeed")  # m/s
        rows.append({
            "id": a.get("activityId"),
            "date": (a.get("startTimeLocal") or "")[:10],
            "start": a.get("startTimeLocal"),
            "name": a.get("activityName"),
            "type": (a.get("activityType") or {}).get("typeKey") or "other",
            "distance_km": num(a.get("distance"), 0.001, 2),
            "duration_min": num(a.get("duration"), 1 / 60),
            "avg_hr": num(a.get("averageHR"), digits=0),
            "max_hr": num(a.get("maxHR"), digits=0),
            "calories": num(a.get("calories"), digits=0),
            "elev_gain_m": num(a.get("elevationGain"), digits=0),
            "avg_speed_kmh": num(speed, 3.6, 2),
            "training_load": num(a.get("activityTrainingLoad")),
        })
    return rows


def fetch_daily(garmin: Garmin, start: date, end: date) -> list[dict]:
    rows = []
    day = start
    while day <= end:
        s = garmin.get_user_summary(iso(day)) or {}
        if s.get("totalSteps") is not None or s.get("restingHeartRate") is not None:
            rows.append({
                "date": iso(day),
                "steps": s.get("totalSteps"),
                "step_goal": s.get("dailyStepGoal"),
                "distance_km": num(s.get("totalDistanceMeters"), 0.001, 2),
                "calories_total": num(s.get("totalKilocalories"), digits=0),
                "calories_active": num(s.get("activeKilocalories"), digits=0),
                "resting_hr": s.get("restingHeartRate"),
                "intensity_moderate": s.get("moderateIntensityMinutes"),
                "intensity_vigorous": s.get("vigorousIntensityMinutes"),
                "floors": num(s.get("floorsAscended"), digits=0),
                "avg_stress": s.get("averageStressLevel"),
            })
        day += timedelta(days=1)
        time.sleep(0.3)  # be gentle with Garmin's rate limits
    return rows


def fetch_body(garmin: Garmin, start: date, end: date) -> list[dict]:
    rows = []
    chunk_start = start
    while chunk_start <= end:
        chunk_end = min(chunk_start + timedelta(days=180), end)
        data = garmin.get_body_composition(iso(chunk_start), iso(chunk_end)) or {}
        for w in data.get("dateWeightList") or []:
            if w.get("weight") is None:
                continue
            rows.append({
                "date": w.get("calendarDate"),
                "ts": w.get("date") or w.get("timestampGMT"),
                "weight_kg": num(w.get("weight"), 0.001, 2),  # grams -> kg
                "bmi": num(w.get("bmi")),
                "body_fat_pct": num(w.get("bodyFat")),
                "body_water_pct": num(w.get("bodyWater")),
                "muscle_kg": num(w.get("muscleMass"), 0.001, 2),
                "bone_kg": num(w.get("boneMass"), 0.001, 2),
            })
        chunk_start = chunk_end + timedelta(days=1)
    return rows


def merge(old: list[dict], new: list[dict], key) -> list[dict]:
    merged = {key(r): r for r in old}
    merged.update({key(r): r for r in new})
    return sorted(merged.values(), key=lambda r: (r.get("date") or "", str(key(r))))


def load_existing() -> dict:
    if DATA_JSON.exists():
        return json.loads(DATA_JSON.read_text(encoding="utf-8"))
    return {"activities": [], "daily": [], "body": []}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--login", action="store_true", help="log in interactively and print the token JSON")
    parser.add_argument("--days", type=int, default=365, help="history to pull on the first run (default 365)")
    parser.add_argument("--full", action="store_true", help="ignore existing data and re-pull --days")
    args = parser.parse_args()

    interactive = sys.stdin.isatty()
    garmin = connect(interactive or args.login)

    if args.login:
        print("\nLogin OK. Save the line below as the GitHub secret GARMIN_TOKENS:\n")
        print(garmin.client.dumps())
        return 0

    data = {"activities": [], "daily": [], "body": []} if args.full else load_existing()
    end = date.today()
    last = max((r["date"] for r in data["daily"]), default=None)
    start = (
        datetime.strptime(last, "%Y-%m-%d").date() - timedelta(days=OVERLAP_DAYS)
        if last
        else end - timedelta(days=args.days)
    )
    print(f"Syncing {start} .. {end}")

    activities = fetch_activities(garmin, start, end)
    daily = fetch_daily(garmin, start, end)
    body = fetch_body(garmin, start, end)
    print(f"  {len(activities)} activities, {len(daily)} days, {len(body)} weigh-ins")

    data["activities"] = merge(data["activities"], activities, lambda r: r["id"])
    data["daily"] = merge(data["daily"], daily, lambda r: r["date"])
    data["body"] = merge(data["body"], body, lambda r: (r["date"], r.get("ts")))
    data["updated"] = datetime.now().astimezone().isoformat(timespec="minutes")

    DATA_JSON.parent.mkdir(exist_ok=True)
    DATA_JS.parent.mkdir(exist_ok=True)
    payload = json.dumps(data, ensure_ascii=False, indent=1)
    DATA_JSON.write_text(payload + "\n", encoding="utf-8")
    DATA_JS.write_text(f"window.GARMIN_DATA = {payload};\n", encoding="utf-8")
    print(f"Wrote {DATA_JSON.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
