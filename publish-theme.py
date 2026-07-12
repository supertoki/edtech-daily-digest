#!/usr/bin/env python3
"""Publish the theme endpoint (api/theme.json) served statically by GitHub Pages.

The Hermes agent (Matilda) GETs this file to learn (a) today's dominant theme
and (b) the locked hero-week's theme + status, so she can decide when to
generate a new weekly hero and what it should depict.

  - daily:    top theme for the reference day (by number of tagged articles).
  - heroWeek: the Monday-anchored `target` week key (the work order), its status
              (needed|pending|approved), its frozen theme (locked Monday from the
              trailing 7 days so it can't drift mid-week), a promptSeed, and the
              image currently displayed on the page for reference/fallback. Note
              the displayed image lags `target` during a review handoff.

Usage:
  python publish-theme.py data-2026-07-07.json
  python publish-theme.py data-2026-07-07.json --pages-url https://user.github.io/repo
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone

import hero_select

strip_html = hero_select.strip_html
theme_weights = hero_select.theme_weights


def top_theme(data: dict):
    themes = data.get("themes", [])
    if not themes:
        return None
    counts = theme_weights(data)
    order = {t["k"]: i for i, t in enumerate(themes)}
    best = max(themes, key=lambda t: (counts.get(t["k"], 0), -order[t["k"]]))
    return best, counts


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

    # Lock this week's theme on its first run (Monday), then read the locked
    # `target` week -- that's the work order the agent designs to.
    manifest, _ = hero_select.lock_week(date_iso, data_dir, assets_dir)
    target = manifest.get("target") or hero_select.week_key(date_iso)
    tw = manifest["weeks"].get(target, {})
    status = hero_select.week_status_for(target, manifest, assets_dir)

    # The image currently ON the page (the newest approved week) -- for the
    # agent's reference and as the fallback. This lags `target` during handoff.
    disp = hero_select.displayed_week(manifest, assets_dir)
    disp_img = (
        "%s/%s" % (hero_select.WEB_DIR, manifest["weeks"][disp]["file"])
        if disp else None
    )

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

    hero_week = {
        "weekKey": target,
        "weekRange": hero_select.week_range_label(target),
        "status": status,
        "displayedWeek": disp,
        "currentImage": disp_img or hero_select.DEFAULT_HERO,
    }
    style_path = "api/hero-style.json"
    hero_week["styleGuideUrl"] = (
        args.pages_url.rstrip("/") + "/" + style_path if args.pages_url else style_path
    )
    key = tw.get("themeKey")
    if key:
        title = tw.get("themeTitle", key)
        body = tw.get("themeBody", "")
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
    print("Wrote %s (daily=%s, target=%s/%s, displayed=%s)"
          % (out, daily.get("topThemeKey"), target, status, disp))
    return 0


if __name__ == "__main__":
    sys.exit(main())
