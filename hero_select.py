#!/usr/bin/env python3
"""Weekly hero-illustration selection (shared by build-digest.py and publish-theme.py).

The hero image changes at most once per week, anchored to Wednesday:
a "hero week" runs Wednesday -> Tuesday. For any digest date we compute the
week key (the ISO date of that week's Wednesday) and pick the approved image
for that week. If this week's image isn't approved yet, we fall back to the
most recent previously-approved week, and finally to the built-in default hero.
This guarantees the daily digest is never blocked on hero generation.

Manifest format (assets/illustrations/heroes.json):
  {
    "current": "2026-07-08",
    "weeks": {
      "2026-07-01": { "file": "hero-2026-07-01.webp", "theme": "human",
                       "approvedAt": "2026-06-30T18:00:00Z" }
    }
  }
A week is only usable once it has an "approvedAt" value and its file exists.
"""
from __future__ import annotations

import json
import os
from datetime import date, timedelta

WEB_DIR = "assets/illustrations"
DEFAULT_HERO = "assets/illustrations/hero.png"
WEDNESDAY = 2  # date.weekday(): Mon=0 .. Sun=6


def most_recent_wednesday(iso: str) -> date:
    """The Wednesday that starts the hero-week containing `iso` (Wed->Tue)."""
    d = date.fromisoformat(iso)
    return d - timedelta(days=(d.weekday() - WEDNESDAY) % 7)


def week_key(iso: str) -> str:
    return most_recent_wednesday(iso).isoformat()


def load_manifest(path: str) -> dict:
    """Load the heroes manifest, tolerating a missing/invalid file."""
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except (FileNotFoundError, ValueError):
        return {"current": None, "weeks": {}}
    data.setdefault("weeks", {})
    return data


def select_hero(iso: str, manifest: dict, assets_dir: str):
    """Pick the hero for a digest date.

    Returns (web_path_or_None, week_key, used_week_key_or_None):
      - web_path: site-relative path to the image, or None to use the default.
      - week_key: the target week for `iso`.
      - used_week_key: which approved week actually supplied the image.
    """
    wk = week_key(iso)
    weeks = manifest.get("weeks", {})
    usable = sorted(
        (k for k, v in weeks.items() if v.get("approvedAt") and k <= wk),
        reverse=True,
    )
    for k in usable:
        fname = weeks[k].get("file")
        if fname and os.path.exists(os.path.join(assets_dir, fname)):
            return ("%s/%s" % (WEB_DIR, fname), wk, k)
    return (None, wk, None)


def week_status(iso: str, manifest: dict, assets_dir: str) -> str:
    """'approved' | 'pending' | 'needed' for the week containing `iso`."""
    wk = week_key(iso)
    entry = manifest.get("weeks", {}).get(wk)
    if not entry:
        return "needed"
    if entry.get("approvedAt") and entry.get("file") \
            and os.path.exists(os.path.join(assets_dir, entry["file"])):
        return "approved"
    return "pending"
