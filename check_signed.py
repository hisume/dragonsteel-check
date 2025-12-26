#!/usr/bin/env python3
import argparse
import json
import re
import sys
from datetime import datetime, timezone
from html import unescape
from html.parser import HTMLParser
from pathlib import Path
from urllib.request import Request, urlopen

SOURCE_URL = "https://www.dragonsteelbooks.com/search?q=signed"
SIGNED_RE = re.compile(r"\bElantris\b", re.IGNORECASE)
WHITESPACE_RE = re.compile(r"\s+")


class ProductTitleParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.titles = []

    def handle_starttag(self, tag, attrs):
        if tag != "a":
            return
        attr_map = dict(attrs)
        href = attr_map.get("href", "")
        title = attr_map.get("title")
        if not title or not href:
            return
        if href.startswith("/products/"):
            self.titles.append(title)


def fetch_html(url):
    req = Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (compatible; dragonsteel-check/1.0)"
        },
    )
    with urlopen(req, timeout=30) as response:
        return response.read().decode("utf-8", "ignore")


def normalize_title(title):
    text = unescape(title)
    text = WHITESPACE_RE.sub(" ", text).strip()
    return text


def extract_titles(html_text):
    parser = ProductTitleParser()
    parser.feed(html_text)
    seen = set()
    titles = []
    for raw_title in parser.titles:
        title = normalize_title(raw_title)
        if not title:
            continue
        if not SIGNED_RE.search(title):
            continue
        key = title.casefold()
        if key in seen:
            continue
        seen.add(key)
        titles.append(title)
    titles.sort(key=str.casefold)
    return titles


def write_json(path, payload):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, sort_keys=True, ensure_ascii=True)
        handle.write("\n")


def load_titles(path):
    path = Path(path)
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    titles = data.get("titles", [])
    if not isinstance(titles, list):
        return []
    return [str(title) for title in titles]


def diff_titles(previous, current):
    previous_keys = {title.casefold() for title in previous}
    current_keys = {title.casefold() for title in current}
    added = [title for title in current if title.casefold() not in previous_keys]
    removed = [title for title in previous if title.casefold() not in current_keys]
    added.sort(key=str.casefold)
    removed.sort(key=str.casefold)
    return added, removed


def escape_markdown(text):
    replacements = [
        ("\\", "\\\\"),
        ("*", "\\*"),
        ("_", "\\_"),
        ("`", "\\`"),
        ("[", "\\["),
        ("]", "\\]"),
    ]
    for before, after in replacements:
        text = text.replace(before, after)
    return text


def format_issue_body(current, added, removed):
    lines = []
    if added:
        lines.append("Added:")
        for title in added:
            lines.append(f"- **{escape_markdown(title)}**")
        lines.append("")
    if removed:
        lines.append("Removed:")
        for title in removed:
            lines.append(f"- {escape_markdown(title)}")
        lines.append("")

    lines.append("Current signed titles:")
    added_keys = {title.casefold() for title in added}
    for title in current:
        safe_title = escape_markdown(title)
        if title.casefold() in added_keys:
            safe_title = f"**{safe_title}**"
        lines.append(f"- {safe_title}")

    return "\n".join(lines).rstrip() + "\n"


def format_issue_title(added, removed):
    total_changes = len(added) + len(removed)
    if total_changes == 0:
        return ""
    if total_changes > 1:
        return "New signed book - multiple"
    if added:
        return f"New signed book - {added[0]}"
    return f"Removed signed book - {removed[0]}"


def build_arg_parser():
    parser = argparse.ArgumentParser(
        description="Check Dragonsteel signed books and write a snapshot."
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--output", help="Snapshot output path.")
    group.add_argument(
        "--output-dir",
        help="Directory for timestamped snapshots.",
    )
    parser.add_argument(
        "--latest",
        help="Optional path to write a copy as the latest snapshot.",
    )
    parser.add_argument(
        "--previous",
        help="Optional path to the previous snapshot for diffing.",
    )
    parser.add_argument("--diff", help="Optional path to write diff JSON.")
    parser.add_argument(
        "--issue-body",
        help="Optional path to write issue markdown body.",
    )
    parser.add_argument(
        "--issue-title",
        help="Optional path to write issue title text.",
    )
    return parser


def main():
    args = build_arg_parser().parse_args()
    now = datetime.now(timezone.utc)
    timestamp = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    file_timestamp = now.strftime("%Y-%m-%dT%H-%M-%SZ")

    html_text = fetch_html(SOURCE_URL)
    titles = extract_titles(html_text)
    if not titles:
        print("No signed titles found; refusing to write empty snapshot.", file=sys.stderr)
        return 2

    payload = {
        "timestamp": timestamp,
        "source_url": SOURCE_URL,
        "titles": titles,
    }

    if args.output_dir:
        output_path = Path(args.output_dir) / f"{file_timestamp}.json"
    else:
        output_path = Path(args.output)

    write_json(output_path, payload)

    if args.latest:
        write_json(args.latest, payload)

    previous_titles = []
    if args.previous:
        previous_titles = load_titles(args.previous)

    if args.diff or args.issue_body or args.issue_title:
        added, removed = diff_titles(previous_titles, titles)
        diff_payload = {
            "timestamp": timestamp,
            "added": added,
            "removed": removed,
            "current": titles,
            "previous": previous_titles,
        }
        if args.diff:
            write_json(args.diff, diff_payload)
        if args.issue_body:
            body = format_issue_body(titles, added, removed)
            Path(args.issue_body).parent.mkdir(parents=True, exist_ok=True)
            Path(args.issue_body).write_text(body, encoding="utf-8")
        if args.issue_title:
            title = format_issue_title(added, removed)
            Path(args.issue_title).parent.mkdir(parents=True, exist_ok=True)
            Path(args.issue_title).write_text(title + "\n", encoding="utf-8")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
