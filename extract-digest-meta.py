#!/usr/bin/env python3
"""Extract fields from a digest HTML's JSON data island.

Usage:
  python extract-digest-meta.py <digest.html> <field>

Fields:
  summary    -> executive summary, HTML tags stripped
  themes     -> theme titles joined with ' . '
  headline   -> cover headline, tags stripped
  dateLabel  -> human date label (e.g. "JULY 2, 2026")
  <other>    -> raw top-level string value from the data island
"""
import re
import json
import sys

TAG_RE = re.compile(r"<[^>]*>")


def strip_tags(s: str) -> str:
    return TAG_RE.sub("", s or "").strip()


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", newline="\n")
    except (AttributeError, TypeError):
        pass
    if len(sys.argv) < 2:
        sys.stderr.write("usage: extract-digest-meta.py <digest.html> [field]\n")
        return 2
    path = sys.argv[1]
    field = sys.argv[2] if len(sys.argv) > 2 else "summary"

    with open(path, encoding="utf-8") as fh:
        html = fh.read()

    m = re.search(
        r'<script id="digest-data" type="application/json">(.*?)</script>',
        html,
        re.S,
    )
    if not m:
        sys.stderr.write("ERROR: digest-data island not found in %s\n" % path)
        return 1

    data = json.loads(m.group(1))

    if field == "summary":
        print(strip_tags(data.get("summary", "")))
    elif field == "themes":
        print(" \u00b7 ".join(t.get("title", "") for t in data.get("themes", [])))
    elif field == "headline":
        print(strip_tags(data.get("headline", "")))
    else:
        print(data.get(field, ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
