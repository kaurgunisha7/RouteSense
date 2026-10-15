"""Turn a free-text prompt into trip parameters with plain Python (no LLM).

    parse_prompt("3 days in Delhi, budget 9k, love history and street food, relaxed")
    -> ParsedTrip(city='delhi', days=3, budget_total_inr=9000, interests=[...], pace='relaxed', ...)

Anything not found is left None / default and listed in `.missing` so the API can ask a follow-up.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date as Date, timedelta

from .cities import find_city
from .scoring import GROUPS

WORDS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7,
         "eight": 8, "nine": 9, "ten": 10, "a": 1}
MONTHS = {m: i + 1 for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"])}
WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
NUM = r"(\d+|one|two|three|four|five|six|seven|eight|nine|ten|a)"


@dataclass
class ParsedTrip:
    city: str | None = None
    days: int | None = None
    budget_total_inr: float | None = None
    start_date: Date | None = None
    start_time: str | None = None
    interests: list[str] = field(default_factory=list)
    travellers: int = 1
    pace: str = "normal"
    missing: list[str] = field(default_factory=list)


def _n(tok: str) -> int:
    return int(tok) if tok.isdigit() else WORDS[tok]


def _days(t: str) -> int | None:
    m = re.search(rf"\b{NUM}[\s-]*(?:days?|nights?)\b", t)
    if m:
        return max(1, min(14, _n(m.group(1))))
    if re.search(r"\bweekend\b", t):
        return 2
    if re.search(r"\b(a|one)\s+week\b", t) or "week long" in t or "weeklong" in t:
        return 7
    m = re.search(rf"\b{NUM}\s+weeks?\b", t)
    return min(14, _n(m.group(1)) * 7) if m else None


def _money(num: str, suffix: str | None) -> float:
    v = float(num.replace(",", ""))
    s = (suffix or "").lower()
    if s in ("k", "thousand"):
        v *= 1000
    elif s in ("l", "lac", "lakh", "lakhs"):
        v *= 100000
    return v


def _budget(t: str, days: int | None) -> float | None:
    amt = r"(\d[\d,]*(?:\.\d+)?)\s*(k|thousand|lakhs?|lacs?|l)?"
    pats = [
        rf"(?:₹|rs\.?|inr)\s*{amt}",                               # ₹9000, rs 9000
        rf"{amt}\s*(?:rupees|rs\b|inr\b|₹)",                       # 9000 rupees
        rf"budget\s*(?:is|of|:|around|about|approx\.?|under|upto|up to)?\s*{amt}",
        rf"(?:under|within|upto|up to|max(?:imum)?)\s+{amt}\b",
        rf"\b(\d+(?:\.\d+)?)\s*(k|lakhs?|lacs?)\b",                # 9k, 1 lakh
    ]
    for p in pats:
        m = re.search(p, t)
        if m:
            val = _money(m.group(1), m.group(2) if m.lastindex and m.lastindex >= 2 else None)
            if val < 100:                      # "budget 3 days"-style false hits
                continue
            tail = t[m.end(): m.end() + 25]
            if days and re.match(r"\s*(?:/|per|a|each|every)\s*(?:day|night)|\s*daily", tail):
                val *= days                    # per-day budget -> total
            return val
    return None


def _date(t: str, today: Date) -> Date | None:
    m = re.search(r"\b(20\d\d)-(\d\d)-(\d\d)\b", t)
    if m:
        try:
            return Date(int(m[1]), int(m[2]), int(m[3]))
        except ValueError:
            return None
    if "day after tomorrow" in t:
        return today + timedelta(days=2)
    if re.search(r"\btomorrow\b", t):
        return today + timedelta(days=1)
    m = re.search(r"\bnext\s+(" + "|".join(WEEKDAYS) + r")\b", t)
    if m:
        ahead = (WEEKDAYS.index(m[1]) - today.weekday()) % 7 or 7
        return today + timedelta(days=ahead)
    m = re.search(r"\b(\d{1,2})(?:st|nd|rd|th)?\s+(" + "|".join(MONTHS) + r")[a-z]*\b", t) or None
    if m:
        d, mon = int(m[1]), MONTHS[m[2]]
    else:
        m2 = re.search(r"\b(" + "|".join(MONTHS) + r")[a-z]*\s+(\d{1,2})(?:st|nd|rd|th)?\b", t)
        if not m2:
            return None
        d, mon = int(m2[2]), MONTHS[m2[1]]
    try:
        out = Date(today.year, mon, d)
    except ValueError:
        return None
    return out if out >= today else Date(today.year + 1, mon, d)


def _travellers(t: str) -> int:
    if re.search(r"\b(couple|honeymoon|my (wife|husband|girlfriend|boyfriend|partner))\b", t):
        return 2
    m = re.search(rf"\b(?:family of|group of)\s+{NUM}\b", t) or re.search(rf"\b{NUM}\s+(?:people|persons|adults|of us|friends|travell?ers)\b", t)
    if m and m.group(1) != "a":
        return max(1, min(20, _n(m.group(1))))
    return 1


def _interests(t: str) -> list[str]:
    """Names of interest groups whose keywords appear (word-start match, so 'eat' != 'great')."""
    found = []
    for name, (keys, _c, _t) in GROUPS.items():
        if any(re.search(r"\b" + re.escape(k), t) for k in keys):
            found.append(name)
    return found





def _start_time(text: str) -> str | None:
    t = text.lower()

    if not re.search(r"\b(start|starting|begin|beginning|from)\b", t):
        return None

    match = re.search(
        r"\b(\d{1,2})(?::(\d{2}))?\s*(am|pm)\b",
        t,
    )
    if not match:
        return None

    hour = int(match.group(1))
    minute = int(match.group(2) or 0)
    period = match.group(3)

    if not 1 <= hour <= 12 or not 0 <= minute <= 59:
        return None

    hour = hour % 12
    if period == "pm":
        hour += 12

    return f"{hour:02d}:{minute:02d}"




def parse_prompt(text: str, today: Date | None = None) -> ParsedTrip:
    t = " ".join(text.lower().replace("₹", " ₹").split())
    today = today or Date.today()
    p = ParsedTrip(city=find_city(t), days=_days(t))
    p.start_time = _start_time(t)
    p.budget_total_inr = _budget(t, p.days)
    p.start_date = _date(t, today)
    p.interests = _interests(t)
    p.travellers = _travellers(t)
    if re.search(r"\b(relax|slow|chill|leisure|laid.?back|easy)", t):
        p.pace = "relaxed"
    elif re.search(r"\b(packed|busy|as much as|cover everything|fast.?paced)", t):
        p.pace = "packed"
    for f, v in (("city", p.city), ("days", p.days), ("budget", p.budget_total_inr)):
        if v is None:
            p.missing.append(f)
    return p
