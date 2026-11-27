#!/usr/bin/env python3
"""Copy project docs into a vault without changing or deleting project files."""
import hashlib
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def copy_atomic(source, target):
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=target.parent, prefix=".vault-copy-", delete=False) as tmp:
        temporary = Path(tmp.name)
    try:
        shutil.copy2(source, temporary)
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)


def sync(source, destination):
    source, destination = Path(source).resolve(), Path(destination).resolve()
    if not source.is_dir() or source == destination or source in destination.parents or destination in source.parents:
        raise ValueError("source and vault destination must be separate directories")
    destination.mkdir(parents=True, exist_ok=True)
    state_file = destination / ".vault-copy-state.json"
    try:
        old_state = json.loads(state_file.read_text())
        if not isinstance(old_state, dict):
            old_state = {}
    except (OSError, ValueError):
        old_state = {}
    state = dict(old_state)
    files = [source / name for name in ("README.md", "AGENTS.md")]
    docs = source / "docs"
    vault_docs = destination / "docs"
    if vault_docs.is_symlink():
        vault_docs.unlink()
        vault_docs.mkdir()
    for name in ("README.md", "AGENTS.md"):
        linked = destination / name
        if linked.is_symlink() and not (source / name).is_file():
            linked.unlink()
    if docs.is_dir():
        files.extend(path for path in docs.rglob("*") if path.is_file() and not path.is_symlink())
    for item in files:
        if not item.is_file() or item.is_symlink():
            continue
        relative = item.relative_to(source)
        target = destination / relative
        # Old vaults used links. Remove only vault-side links, never their targets.
        for parent in reversed(target.parents):
            if parent == destination.parent:
                break
            if parent.is_symlink():
                parent.unlink()
                parent.mkdir()
        if target.is_symlink():
            target.unlink()
        new_hash = digest(item)
        key = str(relative)
        if not target.exists():
            copy_atomic(item, target)
            state[key] = new_hash
        elif not target.is_file():
            continue
        elif digest(target) == new_hash:
            state[key] = new_hash
        elif old_state.get(key) == digest(target):
            copy_atomic(item, target)
            state[key] = new_hash
        elif old_state.get(key) != new_hash:
            incoming = target.with_name(f"{target.stem}.incoming-{new_hash[:12]}{target.suffix}")
            if not incoming.exists():
                copy_atomic(item, incoming)
            # The vault copy changed independently; keep it and the source revision.
    with tempfile.NamedTemporaryFile(mode="w", dir=destination, prefix=".vault-state-", delete=False) as tmp:
        json.dump(state, tmp, indent=2, sort_keys=True)
        tmp.write("\n")
        temporary = Path(tmp.name)
    os.replace(temporary, state_file)


if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit("usage: vault-copy.py PROJECT VAULT_PROJECT")
    sync(sys.argv[1], sys.argv[2])
