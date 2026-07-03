#!/usr/bin/env python3
"""Build a daily digest (HTML + Markdown) from a single JSON data file.

The JSON is the single source of truth. This script:
  1. validates the data,
  2. injects it into template.html's <script id="digest-data"> island to
     produce digest-<date>.html,
  3. renders a matching digest-<date>.md.

Usage:
  python build-digest.py data.json
  python build-digest.py data.json --template template.html --outdir .

Data schema (see template.html for the full contract):
  {
    "date": "YYYY-MM-DD",
    "dateLabel": "JULY 2, 2026",
    "headline": "...",
    "thesis": "... may contain <b> ...",
    "summary": "... may contain <b> ...",
    "footnote": "...",
    "themes":  [ {"k","icon","title","body"} , ... ],
    "sources": [ {"name","dom","icon","note"?, "arts":[ {"t","u","s","d"?,"tag"?,"lvl"?,"th"?} ]} ]
  }
"""
import argparse
import json
import os
import re
import sys
from datetime import date as _date

ISLAND_RE = re.compile(
    r'(<script id="digest-data" type="application/json">)(.*?)(</script>)',
    re.S,
)
TAG_RE = re.compile(r"<[^>]*>")
BOLD_RE = re.compile(r"</?b>")

REQUIRED_TOP = ["date", "dateLabel", "headline", "thesis", "summary", "footnote", "themes", "sources"]
MONTHS = ["", "January", "February", "March", "April", "May", "June",
          "July", "August", "September", "October", "November", "December"]


def die(msg: str) -> None:
    sys.stderr.write("ERROR: %s\n" % msg)
    sys.exit(1)


def to_md_inline(s: str) -> str:
    """Convert the limited inline HTML we allow (<b>) to Markdown, strip the rest."""
    s = BOLD_RE.sub("**", s or "")
    s = TAG_RE.sub("", s)
    return s.strip()


def long_date(iso: str) -> str:
    y, m, d = (int(x) for x in iso.split("-"))
    return "%s %d, %d" % (MONTHS[m], d, y)


def validate(data: dict) -> None:
    missing = [k for k in REQUIRED_TOP if k not in data]
    if missing:
        die("missing required fields: %s" % ", ".join(missing))
    try:
        _date.fromisoformat(data["date"])
    except ValueError:
        die("date must be ISO YYYY-MM-DD, got %r" % data["date"])
    theme_keys = {t.get("k") for t in data["themes"]}
    if None in theme_keys:
        die("every theme needs a 'k' key")
    for s in data["sources"]:
        for req in ("name", "dom", "icon", "arts"):
            if req not in s:
                die("source %r missing %r" % (s.get("name", "?"), req))
        for a in s["arts"]:
            for req in ("t", "u", "s"):
                if req not in a:
                    die("article %r missing %r" % (a.get("t", "?"), req))
            for k in a.get("th", []):
                if k not in theme_keys:
                    die("article %r references unknown theme %r" % (a["t"], k))


def build_html(data: dict, template: str) -> str:
    payload = json.dumps(data, ensure_ascii=False, indent=2)
    if not ISLAND_RE.search(template):
        die("template is missing the <script id=\"digest-data\"> island")
    return ISLAND_RE.sub(
        lambda m: m.group(1) + "\n" + payload + "\n" + m.group(3),
        template,
        count=1,
    )


def build_md(data: dict) -> str:
    out = []
    out.append("# EdTech Daily Digest \u2014 %s" % long_date(data["date"]))
    out.append("")
    out.append("## Executive Summary")
    out.append("")
    out.append(to_md_inline(data["summary"]))
    out.append("")
    out.append("## Source-by-Source Breakdown")
    out.append("")
    for i, s in enumerate(data["sources"], 1):
        out.append("### %d. %s \u2014 %s" % (i, s["name"], s["dom"]))
        if s.get("note"):
            out.append(to_md_inline(s["note"]))
        for a in s["arts"]:
            date_bit = " *(%s)*" % a["d"] if a.get("d") else ""
            tag_bit = ""
            if a.get("tag") == "new":
                tag_bit = " `NEW`"
            elif a.get("tag") == "old":
                tag_bit = " `CONCLUDED`"
            lvl_bit = " `%s`" % a["lvl"] if a.get("lvl") else ""
            out.append(
                "- **%s**%s%s%s \u2014 %s [link](%s)"
                % (a["t"], date_bit, lvl_bit, tag_bit, to_md_inline(a["s"]), a["u"])
            )
        out.append("")
    out.append("## Key Themes & Trends")
    out.append("")
    for i, t in enumerate(data["themes"], 1):
        out.append("**%d. %s.** %s" % (i, t["title"], to_md_inline(t["body"])))
        out.append("")
    out.append("---")
    out.append("*%s*" % to_md_inline(data["footnote"]))
    out.append("")
    return "\n".join(out)


def main() -> int:
    ap = argparse.ArgumentParser(description="Build a daily digest from a JSON data file.")
    ap.add_argument("data", help="path to the digest data JSON file")
    ap.add_argument("--template", default="template.html", help="template HTML (default: template.html)")
    ap.add_argument("--outdir", default=".", help="output directory (default: current dir)")
    args = ap.parse_args()

    with open(args.data, encoding="utf-8") as fh:
        data = json.load(fh)
    validate(data)

    with open(args.template, encoding="utf-8") as fh:
        template = fh.read()

    date = data["date"]
    os.makedirs(args.outdir, exist_ok=True)
    html_path = "%s/digest-%s.html" % (args.outdir.rstrip("/"), date)
    md_path = "%s/digest-%s.md" % (args.outdir.rstrip("/"), date)

    with open(html_path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(build_html(data, template))
    with open(md_path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(build_md(data))

    arts = sum(len(s["arts"]) for s in data["sources"])
    print("Built %s (%d sources, %d articles, %d themes)"
          % (html_path, len(data["sources"]), arts, len(data["themes"])))
    print("Built %s" % md_path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
