import pytz
from datetime import datetime, timedelta
from typing import Optional

IST = pytz.timezone('Asia/Kolkata')

def get_ist_now() -> datetime:
    return datetime.now(IST)

def get_ist_date_str() -> str:
    return get_ist_now().strftime("%Y-%m-%d")

def get_ist_datetime_str() -> str:
    return get_ist_now().strftime("%Y-%m-%d %H:%M:%S")

def get_ist_iso() -> str:
    return get_ist_now().isoformat()

def get_midnight_ist_today() -> datetime:
    now = get_ist_now()
    return now.replace(hour=0, minute=0, second=0, microsecond=0)

def get_midnight_ist_tomorrow() -> datetime:
    return get_midnight_ist_today() + timedelta(days=1)

def seconds_until_midnight_ist() -> int:
    now = get_ist_now()
    next_midnight = get_midnight_ist_tomorrow()
    delta = next_midnight - now
    return int(delta.total_seconds())

def utc_to_ist(utc_dt: datetime) -> datetime:
    if utc_dt.tzinfo is None:
        utc_dt = pytz.utc.localize(utc_dt)
    return utc_dt.astimezone(IST)

def ist_to_utc(ist_dt: datetime) -> datetime:
    if ist_dt.tzinfo is None:
        ist_dt = IST.localize(ist_dt)
    return ist_dt.astimezone(pytz.utc)

