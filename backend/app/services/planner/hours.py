"""Parse OSM-style opening_hours (the subset used in delhi_pois.csv) and check
whether a visit fits.

Supported:  "Mo-Su 09:00-18:00"  "Tu-Su 09:30-16:30"  "Sa-Th 08:30-16:30"
            "Mo-Su 07:00-12:00,13:30-18:30"  "Mo-Su 12:00-01:00" (closes after midnight)
            "24/7"  "Mo off"  rules separated by ";"
Times are minutes since midnight; a closing time past midnight is > 1440.
"""
from __future__ import annotations

import re

DAYS = ["Mo", "Tu", "We", "Th", "Fr", "Sa", "Su"]
_TIME = re.compile(r"(\d{1,2}):(\d{2})\s*-\s*(\d{1,2}):(\d{2})")


def _mins(h: str, m: str) -> int:
    return int(h) * 60 + int(m)


def _expand_days(part: str) -> list[int]:
    part = part.strip()
    if not part:
        return list(range(7))
    out: list[int] = []
    for tok in part.split(","):
        tok = tok.strip()
        if not tok:
            continue
        if "-" in tok:
            a, b = [t.strip()[:2].title() for t in tok.split("-", 1)]
            if a not in DAYS or b not in DAYS:
                continue
            i, j = DAYS.index(a), DAYS.index(b)
            out += [d % 7 for d in range(i, j + 1 if j >= i else j + 8)]
        elif tok[:2].title() in DAYS:
            out.append(DAYS.index(tok[:2].title()))
    return sorted(set(out))


def parse_hours(raw: str | None) -> dict[int, list[tuple[int, int]]] | None:
    """Return {weekday(0=Mon): [(open, close), ...]} or None if unknown."""
    if not raw or not raw.strip():
        return None
    raw = raw.strip()
    if raw == "24/7":
        return {d: [(0, 1440)] for d in range(7)}
    table: dict[int, list[tuple[int, int]]] = {}
    for rule in raw.split(";"):
        rule = rule.strip()
        if not rule:
            continue
        m = re.search(r"\d|off|closed", rule, re.I)
        if not m:
            continue
        days = _expand_days(rule[: m.start()])
        rest = rule[m.start():]
        if rest.lower().startswith(("off", "closed")):
            for d in days:
                table[d] = []
            continue
        wins = []
        for h1, m1, h2, m2 in _TIME.findall(rest):
            o, c = _mins(h1, m1), _mins(h2, m2)
            if c <= o:          # 12:00-01:00 or 00:00-00:00 style
                c += 1440
            wins.append((o, c))
        if wins:
            for d in days:
                table[d] = wins
    return table or None


def windows(table, weekday: int) -> list[tuple[int, int]]:
    if table is None:
        return [(540, 1080)]    # unknown hours: assume 09:00-18:00 (caller should flag)
    return table.get(weekday, [])


def is_open_on(table, weekday: int) -> bool:
    return bool(windows(table, weekday))


def fit_visit(table, weekday: int, arrive: int, duration: int,
              max_wait: int = 45, min_frac: float = 0.6):
    """Try to fit a visit of `duration` min arriving at `arrive`.

    Returns (start, end) or None. If the place closes before the full
    duration, the visit is shortened but must still be at least
    max(30, min_frac * duration) minutes. Waiting for opening is capped at max_wait.
    """
    need = min(duration, max(30, int(min_frac * duration)))
    for o, c in windows(table, weekday):
        start = max(arrive, o)
        if start - arrive > max_wait:
            continue
        avail = c - start
        if avail >= need:
            return start, start + min(duration, avail)
    return None
