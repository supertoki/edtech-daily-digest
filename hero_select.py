#!/usr/bin/env python3
"""Weekly hero-illustration selection + weekly-theme locking.

The hero illustration changes at most once per week, anchored to MONDAY: a
"hero week" runs Monday -> Sunday, keyed by that Monday's ISO date.

Two ideas are deliberately DECOUPLED so a late/absent illustration never breaks
the page (the "planned overlap"):

  * The week's THEME is *locked* on Monday (the first run of a new week) from the
    trailing-7-day dominant theme and written to heroes.json. This is the agent's
    (Matilda's) work order and is what api/theme.json exposes for her to GET.
    Locking it also freezes the label so it can't drift mid-week.
  * The DISPLAYED hero on the page only advances when a week's illustration is
    actually approved/promoted. Until then the previous approved hero keeps
    showing. `target` tracks the locked week Matilda is working on; `displayed`
    tracks the week currently rendered on the page (the newest approved image).

Manifest format (assets/illustrations/heroes.json):
  {
    "target":    "2026-07-13",   # locked Monday; the agent's current work order
    "displayed": "2026-07-06",   # Monday shown on the page (has an approved image)
    "current":   "2026-07-06",   # legacy alias == displayed
    "weeks": {
      "2026-07-06": {
        "themeKey": "foundations", "themeTitle": "...", "themeBody": "...",
        "lockedAt": "2026-07-06T12:00:00Z",
        "file": "hero-2026-07-06.webp", "theme": "foundations",
        "approvedAt": "2026-07-07T18:00:00Z"   # present once art is promoted
      }
    }
  }
A week is displayable once it has "approvedAt" + a "file" that exists on disk.
"""
from __future__ import annotations

import glob
import json
import os
import re
from datetime import date, datetime, timedelta, timezone

WEB_DIR = "assets/illustrations"
DEFAULT_HERO = "assets/illustrations/hero.png"
MONDAY = 0  # date.weekday(): Mon=0 .. Sun=6

DATA_RE = re.compile(r"data-(\d{4}-\d{2}-\d{2})\.json$")
BOLD_RE = re.compile(r"</?b>")
TAG_RE = re.compile(r"<[^>]*>")


# --------------------------------------------------------------------------- #
# Week math
# --------------------------------------------------------------------------- #
def most_recent_monday(iso: str) -> date:
    """The Monday that starts the hero-week containing `iso` (Mon->Sun)."""
    d = date.fromisoformat(iso)
    return d - timedelta(days=(d.weekday() - MONDAY) % 7)


def week_key(iso: str) -> str:
    return most_recent_monday(iso).isoformat()


def week_range_label(week_key_iso: str) -> str:
    """'M/D-M/D' for the Mon->Sun span of a week key, e.g. '7/6-7/12'."""
    start = date.fromisoformat(week_key_iso)
    end = start + timedelta(days=6)
    return "%d/%d-%d/%d" % (start.month, start.day, end.month, end.day)


def _now_z() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# --------------------------------------------------------------------------- #
# Theme aggregation (shared with publish-theme.py)
# --------------------------------------------------------------------------- #
def strip_html(s: str) -> str:
    return TAG_RE.sub("", BOLD_RE.sub("", s or "")).strip()


def theme_weights(data: dict) -> dict:
    counts = {t["k"]: 0 for t in data.get("themes", [])}
    for s in data.get("sources", []):
        for a in s.get("arts", []):
            for k in a.get("th", []):
                if k in counts:
                    counts[k] += 1
    return counts


def trailing_days(data_dir: str, ref_iso: str, span: int = 7):
    """Return [(iso, data)] for data-*.json within the `span`-day window ending ref_iso."""
    ref = date.fromisoformat(ref_iso)
    out = []
    for path in glob.glob(os.path.join(data_dir, "data-*.json")):
        m = DATA_RE.search(path.replace("\\", "/"))
        if not m:
            continue
        iso = m.group(1)
        d = date.fromisoformat(iso)
        if 0 <= (ref - d).days < span:
            try:
                with open(path, encoding="utf-8") as fh:
                    out.append((iso, json.load(fh)))
            except ValueError:
                continue
    out.sort(key=lambda x: x[0], reverse=True)  # newest first
    return out


def weekly_theme(days):
    """Aggregate theme weights across trailing days; return (key, title, body)."""
    agg = {}
    meta = {}  # key -> (title, body), preferring the newest day's copy
    for iso, data in days:  # newest first
        for t in data.get("themes", []):
            meta.setdefault(t["k"], (t.get("title", t["k"]), strip_html(t.get("body", ""))))
        for k, w in theme_weights(data).items():
            agg[k] = agg.get(k, 0) + w
    if not agg:
        return None
    key = max(agg, key=lambda k: agg[k])
    title, body = meta.get(key, (key, ""))
    return key, title, body


# --------------------------------------------------------------------------- #
# Manifest
# --------------------------------------------------------------------------- #
def load_manifest(path: str) -> dict:
    """Load the heroes manifest, tolerating a missing/invalid file."""
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except (FileNotFoundError, ValueError):
        data = {}
    data.setdefault("weeks", {})
    data.setdefault("target", None)
    # `current` is the legacy name for the displayed pointer.
    data.setdefault("displayed", data.get("current"))
    return data


def save_manifest(path: str, manifest: dict) -> None:
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(manifest, fh, ensure_ascii=False, indent=2)
        fh.write("\n")


def _image_ok(week_entry: dict, assets_dir: str) -> bool:
    f = (week_entry or {}).get("file")
    return bool(
        (week_entry or {}).get("approvedAt")
        and f
        and os.path.exists(os.path.join(assets_dir, f))
    )


def lock_week(iso: str, data_dir: str, assets_dir: str, manifest: dict = None):
    """Ensure the Monday-week containing `iso` has a locked theme in heroes.json.

    Idempotent: computes the trailing-7-day theme only if the week isn't locked
    yet, then points `target` at this week. Persists the manifest if it changed.
    Returns (manifest, week_key).
    """
    path = os.path.join(assets_dir, "heroes.json")
    if manifest is None:
        manifest = load_manifest(path)
    wk = week_key(iso)
    entry = manifest["weeks"].get(wk, {})
    changed = False
    if not entry.get("themeKey"):
        wt = weekly_theme(trailing_days(data_dir, iso))
        if wt:
            key, title, body = wt
            entry.update({
                "themeKey": key,
                "themeTitle": title,
                "themeBody": body,
                "lockedAt": _now_z(),
            })
            manifest["weeks"][wk] = entry
            changed = True
    if manifest.get("target") != wk:
        manifest["target"] = wk
        changed = True
    if changed:
        save_manifest(path, manifest)
    return manifest, wk


def week_status_for(week_key_iso: str, manifest: dict, assets_dir: str) -> str:
    """'needed' (no theme locked) | 'pending' (locked, awaiting art) | 'approved'."""
    entry = (manifest.get("weeks") or {}).get(week_key_iso)
    if not entry or not entry.get("themeKey"):
        return "needed"
    return "approved" if _image_ok(entry, assets_dir) else "pending"


def displayed_week(manifest: dict, assets_dir: str):
    """The Monday week currently shown: newest week with an approved, existing image.

    Prefers the manifest's `displayed` pointer when it's still valid.
    """
    weeks = manifest.get("weeks", {})
    disp = manifest.get("displayed")
    if disp and _image_ok(weeks.get(disp), assets_dir):
        return disp
    approved = sorted((k for k in weeks if _image_ok(weeks[k], assets_dir)), reverse=True)
    return approved[0] if approved else None


def hero_for_page(iso: str, manifest: dict, assets_dir: str) -> dict:
    """The hero to render on the digest page for date `iso`.

    Returns {weekKey, rangeLabel, title, body, image(or None)}.
      * If any week is displayable (approved image), use it. Because of the
        overlap this may be a *prior* week: the newest week's theme/art only
        appears once its illustration is promoted.
      * Cold start (nothing approved yet): fall back to the current locked
        week's theme with the template's default image.
    """
    weeks = manifest.get("weeks", {})
    disp = displayed_week(manifest, assets_dir)
    wk = disp or week_key(iso)
    entry = weeks.get(wk, {})
    return {
        "weekKey": wk,
        "rangeLabel": week_range_label(wk),
        "title": entry.get("themeTitle", ""),
        "body": entry.get("themeBody", ""),
        "image": ("%s/%s" % (WEB_DIR, entry["file"])) if disp else None,
    }
