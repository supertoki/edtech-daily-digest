#!/usr/bin/env python3
"""Promote an approved weekly hero image (used by .github/workflows/receive-hero.yml).

Matilda approves a hero by committing it to
assets/illustrations/candidates/hero-<weekKey>.png. Given that file + its week,
this:
  1. optimizes it to WebP (fit within the style-guide canvas, target maxKB),
  2. writes assets/illustrations/hero-<weekKey>.webp,
  3. updates the heroes.json manifest (attaches the image to the week and
     advances the `displayed` pointer so the page flips on the next build),
  4. patches api/theme.json's heroWeek so the public endpoint reflects the new
     hero immediately.

The workflow removes the raw candidate PNG after this runs.

Usage:
  python ingest-hero.py --image assets/illustrations/candidates/hero-2026-07-06.png \
    --week-key 2026-07-06
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone

WEEK_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
STYLE_DEFAULT = {"canvasWidth": 880, "canvasHeight": 980, "maxKB": 150}


def die(msg: str) -> None:
    sys.stderr.write("ERROR: %s\n" % msg)
    sys.exit(1)


def now_z() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def load_json(path: str, default):
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (FileNotFoundError, ValueError):
        return default


def write_json(path: str, data) -> None:
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2)
        fh.write("\n")


def style_spec(assets_dir: str) -> dict:
    # hero-style.json lives in api/ at the repo root (assets/illustrations -> ../../api).
    root = os.path.dirname(os.path.dirname(assets_dir.rstrip("/\\")))
    spec = load_json(os.path.join(root, "api", "hero-style.json"), {}).get("spec", {})
    return {**STYLE_DEFAULT, **{k: spec[k] for k in STYLE_DEFAULT if k in spec}}


def optimize(src: str, dst: str, max_w: int, max_h: int, max_kb: int):
    from PIL import Image  # Pillow is installed by the workflow

    im = Image.open(src)
    im = im.convert("RGBA")
    im.thumbnail((max_w, max_h), Image.LANCZOS)
    q = 88
    while True:
        im.save(dst, "WEBP", quality=q, method=6)
        kb = os.path.getsize(dst) / 1024
        if kb <= max_kb or q <= 45:
            break
        q -= 8
    return kb, im.size, q


def main() -> int:
    ap = argparse.ArgumentParser(description="Promote an approved weekly hero image.")
    ap.add_argument("--image", required=True, help="path to the candidate image to promote")
    ap.add_argument("--week-key", required=True, help="hero week (Monday date, YYYY-MM-DD)")
    ap.add_argument("--theme-key", default="",
                    help="theme key the image depicts (default: read from theme.json)")
    ap.add_argument("--assets-dir", default="assets/illustrations")
    ap.add_argument("--theme-json", default="api/theme.json")
    args = ap.parse_args()

    wk = args.week_key.strip()
    if not WEEK_RE.match(wk):
        die("week-key must be YYYY-MM-DD, got %r" % wk)
    if not os.path.exists(args.image):
        die("image not found: %s" % args.image)

    assets_dir = args.assets_dir
    os.makedirs(assets_dir, exist_ok=True)
    spec = style_spec(assets_dir)

    # Theme metadata: prefer the arg, else the locked manifest entry, else
    # theme.json when it's the same week.
    theme = load_json(args.theme_json, None)
    hw_theme = {}
    if isinstance(theme, dict):
        hw = theme.get("heroWeek", {})
        if isinstance(hw, dict) and hw.get("weekKey") == wk:
            hw_theme = hw

    fname = "hero-%s.webp" % wk
    dst = os.path.join(assets_dir, fname)
    kb, size, q = optimize(args.image, dst, spec["canvasWidth"], spec["canvasHeight"], spec["maxKB"])
    print("Optimized -> %s (%dx%d, %.0f KB, q=%d)" % (dst, size[0], size[1], kb, q))

    approved_at = now_z()

    # Manifest: attach the image to the week (preserving the locked theme fields)
    # and advance the `displayed` pointer -- the page flips to this hero on the
    # next build. `current` stays as a legacy alias of `displayed`.
    manifest_path = os.path.join(assets_dir, "heroes.json")
    manifest = load_json(manifest_path, {"target": None, "displayed": None, "weeks": {}})
    manifest.setdefault("weeks", {})
    entry = manifest["weeks"].get(wk, {})
    theme_key = args.theme_key or entry.get("themeKey") or hw_theme.get("themeKey", "")
    entry.setdefault("themeKey", theme_key)
    if not entry.get("themeTitle") and hw_theme.get("themeTitle"):
        entry["themeTitle"] = hw_theme["themeTitle"]
    if not entry.get("themeBody") and hw_theme.get("themeBody"):
        entry["themeBody"] = hw_theme["themeBody"]
    entry.update({"file": fname, "theme": theme_key, "approvedAt": approved_at})
    manifest["weeks"][wk] = entry

    disp = manifest.get("displayed") or manifest.get("current")
    if not disp or wk >= disp:
        disp = wk
    manifest["displayed"] = disp
    manifest["current"] = disp  # legacy alias
    write_json(manifest_path, manifest)
    print("Manifest updated: displayed=%s, weeks[%s] approved (theme=%r)"
          % (disp, wk, theme_key))

    # Patch the published endpoint so the page/agent see the new hero right away.
    web = "assets/illustrations/%s" % fname
    if isinstance(theme, dict) and isinstance(theme.get("heroWeek"), dict):
        hw = theme["heroWeek"]
        hw["displayedWeek"] = disp
        hw["currentImage"] = web
        if hw.get("weekKey") == wk:
            hw["status"] = "approved"
        write_json(args.theme_json, theme)
        print("Patched %s heroWeek (displayedWeek=%s, status=%s)"
              % (args.theme_json, disp, hw.get("status")))
    return 0


if __name__ == "__main__":
    sys.exit(main())
