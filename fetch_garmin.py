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
from garminconnect.activity_details import parse_activity_detail_metrics

ROOT = Path(__file__).resolve().parent
DATA_JSON = ROOT / "data" / "garmin.json"
DATA_JS = ROOT / "docs" / "data.js"
DETAILS_DIR = ROOT / "data" / "activities"
# Points kept per time series in data/activities/<id>.json (enough for a chart).
SERIES_POINTS = 500
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
            "avg_power": num(a.get("avgPower"), digits=0),
            "max_power": num(a.get("maxPower"), digits=0),
            "norm_power": num(a.get("normPower"), digits=0),
            "cadence": num(a.get("averageBikingCadenceInRevPerMinute") or a.get("averageRunningCadenceInStepsPerMinute"), digits=0),
            "te_aerobic": num(a.get("aerobicTrainingEffect")),
            "te_anaerobic": num(a.get("anaerobicTrainingEffect")),
            "te_label": a.get("trainingEffectLabel"),
        })
    return rows


def best_average(t: list[float], v: list[float | None], window: int) -> float | None:
    """Best mean of v over any `window` seconds, holding each sample until the next one."""
    if not t or t[-1] - t[0] < window:
        return None
    grid, j, last = [], 0, None
    for sec in range(int(t[0]), int(t[-1]) + 1):
        while j < len(t) and t[j] <= sec:
            last = v[j] if v[j] is not None else last
            j += 1
        grid.append(last or 0)
    csum = [0.0]
    for x in grid:
        csum.append(csum[-1] + x)
    return max(csum[i + window] - csum[i] for i in range(len(grid) - window + 1)) / window


def best_time_for(t: list[float], dist_km: list[float | None], km: float) -> float | None:
    """Fastest time (seconds) to cover `km` anywhere in the activity."""
    pts = [(ti, d) for ti, d in zip(t, dist_km) if d is not None]
    best, j = None, 0
    for i in range(len(pts)):
        while j < len(pts) and pts[j][1] - pts[i][1] < km:
            j += 1
        if j == len(pts):
            break
        best = min(best or 1e9, pts[j][0] - pts[i][0])
    return best


def downsample(t: list[float], cols: dict[str, list], points: int) -> dict[str, list]:
    """Average each column into at most `points` equal-count buckets."""
    size = max(1, -(-len(t) // points))
    out = {"t": []} | {k: [] for k in cols}
    for i in range(0, len(t), size):
        out["t"].append(round(t[i]))
        for k, col in cols.items():
            vals = [x for x in col[i:i + size] if x is not None]
            out[k].append(round(sum(vals) / len(vals), 2) if vals else None)
    return out


def fetch_details(garmin: Garmin, activity: dict) -> dict:
    """Time series, laps, HR zones and peak efforts for one activity."""
    samples = parse_activity_detail_metrics(garmin.get_activity_details(activity["id"], maxchart=4000, maxpoly=0) or {})
    samples = [s for s in samples if s.get("directTimestamp") is not None]
    samples.sort(key=lambda s: s["directTimestamp"])
    t0 = samples[0]["directTimestamp"] if samples else 0
    t = [(s["directTimestamp"] - t0) / 1000 for s in samples]

    def col(*keys, scale=1.0):
        out = []
        for s in samples:
            v = next((s[k] for k in keys if s.get(k) is not None), None)
            out.append(None if v is None else v * scale)
        return out

    cols = {
        "hr": col("directHeartRate"),
        "speed": col("directSpeed", "directEnhancedSpeed", scale=3.6),
        "power": col("directPower"),
        "cadence": col("directBikeCadence", "directDoubleCadence", "directRunCadence"),
        "elev": col("directElevation", "directEnhancedElevation"),
        "dist": col("sumDistance", scale=0.001),
    }
    cols = {k: v for k, v in cols.items() if any(x not in (None, 0) for x in v)}

    peaks = {}
    for key in ("power", "hr"):
        if key in cols:
            for window in (60, 300, 1200, 3600):
                best = best_average(t, cols[key], window)
                if best:
                    peaks[f"{key}_{window // 60}m"] = round(best)
    if "dist" in cols and not activity["type"].endswith(("cycling", "biking", "ride")):
        for km in (1, 5, 10):
            best = best_time_for(t, cols["dist"], km)
            if best:
                peaks[f"time_{km}km"] = round(best)

    laps = []
    for lap in (garmin.get_activity_splits(activity["id"]) or {}).get("lapDTOs") or []:
        laps.append({
            "distance_km": num(lap.get("distance"), 0.001, 2),
            "duration_min": num(lap.get("duration"), 1 / 60, 2),
            "avg_speed_kmh": num(lap.get("averageSpeed"), 3.6, 2),
            "avg_hr": num(lap.get("averageHR"), digits=0),
            "max_hr": num(lap.get("maxHR"), digits=0),
            "avg_power": num(lap.get("averagePower"), digits=0),
            "cadence": num(lap.get("averageBikeCadence") or lap.get("averageRunCadence"), digits=0),
            "elev_gain_m": num(lap.get("elevationGain"), digits=0),
        })

    zones = [
        {"zone": z.get("zoneNumber"), "secs": round(z.get("secsInZone") or 0), "low": z.get("zoneLowBoundary")}
        for z in garmin.get_activity_hr_in_timezones(activity["id"]) or []
    ]
    return {"id": activity["id"], "v": 1, "series": downsample(t, cols, SERIES_POINTS) if samples else None,
            "peaks": peaks, "laps": laps, "zones": zones}


def sync_details(garmin: Garmin, activities: list[dict], limit: int) -> int:
    """Write data/activities/<id>.json for the newest activities that don't have one yet."""
    DETAILS_DIR.mkdir(parents=True, exist_ok=True)
    missing = [a for a in sorted(activities, key=lambda a: a.get("start") or a["date"], reverse=True)
               if not (DETAILS_DIR / f"{a['id']}.json").exists()]
    for a in missing[:limit]:
        try:
            detail = fetch_details(garmin, a)
        except Exception as e:  # manual entries and some indoor types have no detail data
            print(f"  no details for activity {a['id']} ({type(e).__name__})")
            detail = {"id": a["id"], "v": 1, "unavailable": True}
        (DETAILS_DIR / f"{a['id']}.json").write_text(json.dumps(detail, separators=(",", ":")) + "\n", encoding="utf-8")
        time.sleep(0.5)
    return min(len(missing), limit)


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
    parser.add_argument("--details-limit", type=int, default=100,
                        help="max activities to fetch per-activity analysis for in one run (default 100)")
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

    # The activity list is cheap (20 per request), so re-read all of it: older rows pick up new fields.
    first_activity = min((r["date"] for r in data["activities"]), default=iso(start))
    activities = fetch_activities(garmin, min(start, datetime.strptime(first_activity, "%Y-%m-%d").date()), end)
    daily = fetch_daily(garmin, start, end)
    body = fetch_body(garmin, start, end)
    print(f"  {len(activities)} activities, {len(daily)} days, {len(body)} weigh-ins")

    data["activities"] = merge(data["activities"], activities, lambda r: r["id"])
    data["daily"] = merge(data["daily"], daily, lambda r: r["date"])
    data["body"] = merge(data["body"], body, lambda r: (r["date"], r.get("ts")))
    data["updated"] = datetime.now().astimezone().isoformat(timespec="minutes")
    detailed = sync_details(garmin, data["activities"], args.details_limit)
    print(f"  analysis for {detailed} activities")

    DATA_JSON.parent.mkdir(exist_ok=True)
    DATA_JS.parent.mkdir(exist_ok=True)
    payload = json.dumps(data, ensure_ascii=False, indent=1)
    DATA_JSON.write_text(payload + "\n", encoding="utf-8")
    DATA_JS.write_text(f"window.GARMIN_DATA = {payload};\n", encoding="utf-8")
    print(f"Wrote {DATA_JSON.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
