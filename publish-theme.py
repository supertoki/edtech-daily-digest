#!/usr/bin/env python3
"""Publish the theme endpoint (api/theme.json) served statically by GitHub Pages.

The Hermes agent (Matilda) GETs this file to learn (a) today's dominant theme
and (b) the current hero-week's theme + status, so she can decide when to
generate a new weekly hero and what it should depict.

  - daily:    top theme for the reference day (by number of tagged articles).
  - heroWeek: the Wed-anchored week key, its status (needed|pending|approved),
              and its theme computed from the *trailing 7 days* (more stable and
              gives the review loop lead time), plus a promptSeed and the last
              approved image for reference/fallback.

Usage:
  python publish-theme.py data-2026-07-07.json
  python publish-theme.py data-2026-07-07.json --pages-url https://user.github.io/repo
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import re
import sys
from datetime import datetime, timezone

import hero_select

DATA_RE = re.compile(r"data-(\d{4}-\d{2}-\d{2})\.json$")
BOLD_RE = re.compile(r"</?b>")
TAG_RE = re.compile(r"<[^>]*>")


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


def top_theme(data: dict):
    themes = data.get("themes", [])
    if not themes:
        return None
    counts = theme_weights(data)
    order = {t["k"]: i for i, t in enumerate(themes)}
    best = max(themes, key=lambda t: (counts.get(t["k"], 0), -order[t["k"]]))
    return best, counts


def trailing_days(data_dir: str, ref_iso: str, span: int = 7):
    """Return [(iso, data)] for data-*.json within the `span`-day window ending ref_iso."""
    ref = hero_select.date.fromisoformat(ref_iso)
    out = []
    for path in glob.glob(os.path.join(data_dir, "data-*.json")):
        m = DATA_RE.search(path.replace("\\", "/"))
        if not m:
            continue
        iso = m.group(1)
        d = hero_select.date.fromisoformat(iso)
        if 0 <= (ref - d).days < span:
            try:
                with open(path, encoding="utf-8") as fh:
                    out.append((iso, json.load(fh)))
            except ValueError:
                continue
    out.sort(key=lambda x: x[0], reverse=True)  # newest first
    return out


def load_theme_props(out_path: str, script_dir: str) -> dict:
    """Read themeProps from hero-style.json (next to theme.json, else script dir)."""
    for p in (
        os.path.join(os.path.dirname(os.path.abspath(out_path)), "hero-style.json"),
        os.path.join(script_dir, "api", "hero-style.json"),
    ):
        try:
            with open(p, encoding="utf-8") as fh:
                return json.load(fh).get("themeProps", {})
        except (FileNotFoundError, ValueError):
            continue
    return {}


def weekly_theme(days):
    """Aggregate theme weights across trailing days; return (key, title, body)."""
    agg = {}
    meta = {}  # key -> (title, body) preferring newest day
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


def main() -> int:
    ap = argparse.ArgumentParser(description="Emit api/theme.json for the Hermes agent.")
    ap.add_argument("data", help="reference day's data-<date>.json")
    ap.add_argument("--data-dir", default=None, help="dir of data-*.json (default: alongside data)")
    ap.add_argument("--assets-dir", default=None, help="assets/illustrations dir (default: <data-dir>/assets/illustrations)")
    ap.add_argument("--pages-url", default="", help="site base URL to absolutize styleGuideUrl (optional)")
    ap.add_argument("--out", default=None, help="output path (default: <data-dir>/api/theme.json)")
    args = ap.parse_args()

    with open(args.data, encoding="utf-8") as fh:
        data = json.load(fh)
    date_iso = data["date"]

    data_dir = args.data_dir or (os.path.dirname(os.path.abspath(args.data)))
    assets_dir = args.assets_dir or os.path.join(data_dir, "assets", "illustrations")
    out = args.out or os.path.join(data_dir, "api", "theme.json")

    manifest = hero_select.load_manifest(os.path.join(assets_dir, "heroes.json"))
    wk = hero_select.week_key(date_iso)
    status = hero_select.week_status(date_iso, manifest, assets_dir)
    cur_web, _, _ = hero_select.select_hero(date_iso, manifest, assets_dir)

    tt = top_theme(data)
    daily = {}
    if tt:
        best, counts = tt
        order = {t["k"]: i for i, t in enumerate(data["themes"])}
        daily = {
            "date": date_iso,
            "topThemeKey": best["k"],
            "topThemeTitle": best.get("title", best["k"]),
            "topThemeBody": strip_html(best.get("body", "")),
            "themes": sorted(
                ({"k": t["k"], "title": t.get("title", t["k"]), "weight": counts.get(t["k"], 0)}
                 for t in data["themes"]),
                key=lambda x: (-x["weight"], order[x["k"]]),
            ),
        }

    wt = weekly_theme(trailing_days(data_dir, date_iso))
    hero_week = {
        "weekKey": wk,
        "status": status,
        "currentImage": cur_web or hero_select.DEFAULT_HERO,
    }
    style_path = "api/hero-style.json"
    hero_week["styleGuideUrl"] = (
        args.pages_url.rstrip("/") + "/" + style_path if args.pages_url else style_path
    )
    if wt:
        key, title, body = wt
        theme_props = load_theme_props(out, os.path.dirname(os.path.abspath(__file__)))
        prop = theme_props.get(key) or theme_props.get("default")
        hero_week["themeKey"] = key
        hero_week["themeTitle"] = title
        hero_week["themeBody"] = body
        if prop:
            hero_week["themeProp"] = prop
        hero_week["promptSeed"] = (
            "Flat minimal editorial vector illustration for an EdTech digest hero. "
            "Theme: %s - %s. Follow the published style guide (palette, composition, "
            "negative prompt). Centered graduated-AI network mascot on a soft teal disc; "
            "one theme prop: %s; airy with negative space; no text."
            % (title, body, prop or "none")
        )

    payload = {
        "generatedAt": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "daily": daily,
        "heroWeek": hero_week,
    }

    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    with open(out, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)
        fh.write("\n")
    print("Wrote %s (daily=%s, heroWeek=%s/%s)"
          % (out, daily.get("topThemeKey"), wk, status))
    return 0


if __name__ == "__main__":
    sys.exit(main())
