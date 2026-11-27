#!/usr/bin/env python3
"""Copy curated project Markdown into a vault while preserving edits in existing notes."""
import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", required=True, type=Path, help="project docs root")
    parser.add_argument("--project", required=True)
    parser.add_argument("--agent", default="shared")
    parser.add_argument("--vault", type=Path, default=Path.home() / "DocsVault/01 Projects")
    args = parser.parse_args()
    source = args.source.resolve()
    if not source.is_dir() or not args.project or args.project in {".", ".."} or "/" in args.project:
        print("Source directory or project name is invalid", file=sys.stderr)
        return 2
    destination = (args.vault / args.project).resolve()
    if destination == source or source in destination.parents or destination in source.parents:
        print("Source and destination must be separate", file=sys.stderr)
        return 2
    destination.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc).isoformat()
    copied = 0
    conflicts = 0
    for file in sorted(source.rglob("*.md")):
        relative = file.relative_to(source)
        body = file.read_text(encoding="utf-8")
        digest = hashlib.sha256(body.encode()).hexdigest()[:12]
        output = destination / relative
        if output.exists():
            current = output.read_text(encoding="utf-8")
            if f"sha: {digest}\n" in current[:1000]:
                continue
            output = output.with_name(f"{output.stem}.incoming-{digest}.md")
            if output.exists():
                continue
            conflicts += 1
        output.parent.mkdir(parents=True, exist_ok=True)
        frontmatter = (f"---\nagent: {json.dumps(args.agent)}\nproject: {json.dumps(args.project)}\n"
                       f"type: doc\ncreated: {now}\nsource: {json.dumps(str(file))}\n"
                       f"sha: {digest}\ntags: [synced]\n---\n\n")
        output.write_text(frontmatter + body, encoding="utf-8")
        copied += 1
    print(f"copied {copied}; incoming revisions {conflicts}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
