#!/usr/bin/env python3
"""Convert supported Inbox files into Markdown without overwriting notes or source files."""
import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

HOME = Path.home()
CONVERTER = HOME / "Tools/markitdown/.venv/bin/markitdown"
EXTENSIONS = {".pdf", ".docx", ".pptx", ".xlsx", ".html", ".htm", ".csv", ".json", ".xml", ".epub", ".zip", ".png", ".jpg", ".jpeg", ".mp3", ".wav"}


def slug(value):
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-") or "note"


def processed_path(directory, source, digest):
    target = directory / source.name
    if target.exists():
        target = directory / f"{source.stem}-{digest[:12]}{source.suffix}"
    if target.exists():
        raise FileExistsError(f"Processed source already exists: {target}")
    return target


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--inbox", type=Path, default=HOME / "Ingest/Inbox")
    parser.add_argument("--vault", type=Path, default=HOME / "DocsVault/03 Research")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    if not args.inbox.is_dir():
        print(f"Inbox does not exist: {args.inbox}", file=sys.stderr)
        return 1
    if not args.dry_run and not CONVERTER.is_file():
        print(f"Converter is missing: {CONVERTER}", file=sys.stderr)
        return 1
    ingest = args.inbox.parent
    manifest = []
    failures = 0
    for source in sorted(args.inbox.iterdir()):
        if not source.is_file() or source.suffix.lower() not in EXTENSIONS:
            continue
        digest = hashlib.sha256(source.read_bytes()).hexdigest()
        output = args.vault / f"{slug(source.stem)}-{digest[:12]}.md"
        processed = ingest / "Processed"
        try:
            target = processed_path(processed, source, digest)
            if args.dry_run:
                print(f"[dry] {source} -> {output}; archive -> {target}")
                continue
            if not output.exists():
                result = subprocess.run([str(CONVERTER), str(source)], capture_output=True, text=True)
                if result.returncode:
                    raise RuntimeError(result.stderr[:300] or "conversion failed")
                now = datetime.now(timezone.utc).isoformat()
                frontmatter = f"---\ntype: research\nsource: {json.dumps(source.name)}\nsha256: {digest}\ncreated: {now}\ntags: [imported]\n---\n\n"
                output.parent.mkdir(parents=True, exist_ok=True)
                with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=output.parent, prefix=".import-", delete=False) as temporary:
                    temporary.write(frontmatter + result.stdout)
                    temporary_path = Path(temporary.name)
                try:
                    if output.exists():
                        temporary_path.unlink()
                    else:
                        os.link(temporary_path, output)
                        temporary_path.unlink()
                finally:
                    temporary_path.unlink(missing_ok=True)
            processed.mkdir(parents=True, exist_ok=True)
            source.rename(target)
            manifest.append({"source": source.name, "sha256": digest, "note": str(output), "archived": str(target)})
            print(f"imported {source.name} -> {output}")
        except (OSError, RuntimeError) as error:
            failures += 1
            print(f"FAILED {source}: {error}", file=sys.stderr)
    if manifest:
        directory = ingest / "Manifests"
        directory.mkdir(parents=True, exist_ok=True)
        name = datetime.now().strftime("%Y%m%d-%H%M%S-%f") + ".json"
        (directory / name).write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
