#!/usr/bin/env python3
"""secret-scan: stop keys, tokens and passwords from being committed.

  secret-scan              scan what's staged (the global pre-commit hook runs this)
  secret-scan --all [DIR]  scan every tracked file in a repo (before publishing it)
  secret-scan --history    also every past commit (needs gitleaks)

Uses gitleaks when it's installed (hundreds of rules); until then a built-in scan catches the common ones: private keys,
AWS / GitHub / Slack / Google / OpenAI / Anthropic / Stripe tokens, and committing .env, key or credential files.
A line you know is fine: add `gitleaks:allow` to it. Skip once: `git commit --no-verify` (or SKIP_SECRET_SCAN=1).
"""
import os, re, shutil, subprocess, sys
from pathlib import Path

RULES = [
    ("private key", r"-----BEGIN (?:RSA |EC |DSA |OPENSSH |PGP |ENCRYPTED )?PRIVATE KEY(?: BLOCK)?-----"),
    ("AWS access key", r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"),
    ("GitHub token", r"\b(?:gh[pousr]_[A-Za-z0-9]{36,}|github_pat_[A-Za-z0-9_]{60,})\b"),
    ("Slack token", r"\bxox[abprs]-[A-Za-z0-9-]{10,}\b"),
    ("Google API key", r"\bAIza[0-9A-Za-z_-]{35}\b"),
    ("Anthropic key", r"\bsk-ant-[A-Za-z0-9_-]{20,}\b"),
    ("OpenAI key", r"\bsk-(?:proj-|svcacct-)?[A-Za-z0-9_-]{32,}\b"),
    ("Stripe live key", r"\b[sr]k_live_[A-Za-z0-9]{20,}\b"),
    ("password in a URL", r"\b[a-z][a-z0-9+.-]*://[^/\s:@]+:[^/\s:@]{6,}@[^\s]+"),
    ("hard-coded secret", r"(?i)\b(?:password|passwd|secret|api[_-]?key|access[_-]?token|auth[_-]?token)\b\s*[:=]\s*[\"'][^\"'\s]{12,}[\"']"),
]
PLACEHOLDER = re.compile(r"(?i)example|placeholder|changeme|your[_-]|xxxx|<[^>]+>|\$\{|\{\{|dummy|sample|fake|test")
BAD_FILES = re.compile(r"(?:^|/)(?:\.env(?:\.(?!example$|sample$|template$)[^/]+)?|id_(?:rsa|dsa|ecdsa|ed25519)|"
                       r"[^/]+\.(?:pem|key|p12|pfx|keystore|jks)|credentials\.json|\.netrc|\.pgpass|secrets?\.(?:ya?ml|json|toml))$")


def git(*a, cwd=None):
    return subprocess.run(["git", *a], cwd=cwd, capture_output=True, text=True, errors="replace", stdin=subprocess.DEVNULL)


def scan_text(text, where):
    """[(where, line_no, rule)] for lines that look like secrets (placeholders and gitleaks:allow lines are skipped)."""
    hits = []
    for n, line in enumerate(text.splitlines(), 1):
        if "gitleaks:allow" in line or len(line) > 2000: continue
        for name, rx in RULES:
            m = re.search(rx, line)
            if m and not (name in ("hard-coded secret", "password in a URL") and PLACEHOLDER.search(m.group(0))):
                hits.append((where, n, name)); break
    return hits


def staged_hits(cwd=None):
    """Hits in the lines being added, plus files that shouldn't be committed at all."""
    names = [f for f in git("diff", "--cached", "--name-only", "--diff-filter=AM", cwd=cwd).stdout.splitlines() if f]
    hits = [(f, 0, "file that usually holds secrets") for f in names if BAD_FILES.search(f)]
    diff = git("diff", "--cached", "-U0", "--no-color", "--diff-filter=AM", cwd=cwd).stdout
    cur, n = "", 0
    for line in diff.splitlines():
        if line.startswith("+++ b/"): cur = line[6:]
        elif line.startswith("@@"):
            m = re.search(r"\+(\d+)", line); n = int(m[1]) - 1 if m else 0
        elif line.startswith("+") and not line.startswith("+++"):
            n += 1
            hits += [(cur, n, r) for _, _, r in scan_text(line[1:], cur)]
    return hits


def all_hits(root):
    hits = []
    for f in git("ls-files", cwd=root).stdout.splitlines():
        p = Path(root) / f
        if BAD_FILES.search(f): hits.append((f, 0, "file that usually holds secrets"))
        try:
            if p.is_file() and p.stat().st_size < 2_000_000: hits += scan_text(p.read_text(errors="ignore"), f)
        except OSError: pass
    return hits


def report(hits):
    print("\033[31m✗ This looks like it contains a secret:\033[0m", file=sys.stderr)
    for f, n, r in hits[:20]: print(f"   {f}{':' + str(n) if n else ''}  {r}", file=sys.stderr)
    print("   Remove it (keep secrets in .env or the keyring), or if it's fine: add `gitleaks:allow` to the line,\n"
          "   or commit once with --no-verify.", file=sys.stderr)


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if argv[:1] in (["-h"], ["--help"]): print(__doc__.strip()); return 0
    if os.environ.get("SKIP_SECRET_SCAN"): return 0
    leaks = None if os.environ.get("SECRET_SCAN_BUILTIN") else shutil.which("gitleaks")   # tests: force the built-in scan
    if "--all" in argv or "--history" in argv:
        rest = [a for a in argv if not a.startswith("--")]
        root = git("rev-parse", "--show-toplevel", cwd=rest[0] if rest else None).stdout.strip()
        if not root: print("not a git repo", file=sys.stderr); return 2
        if leaks:
            args = ["detect", "--source", root, "--redact", "--no-banner"] + ([] if "--history" in argv else ["--no-git"])
            return subprocess.call([leaks, *args])
        if "--history" in argv: print("--history needs gitleaks (sudo apt install gitleaks)", file=sys.stderr); return 2
        hits = all_hits(root)
    else:
        if leaks:
            r = subprocess.run([leaks, "protect", "--staged", "--redact", "--no-banner", "--verbose"], capture_output=True, text=True, stdin=subprocess.DEVNULL)
            if r.returncode == 1: print(r.stdout + r.stderr, file=sys.stderr)
            if r.returncode in (0, 1): return r.returncode    # other codes: gitleaks itself broke; fall back below
        hits = staged_hits()
    if hits: report(hits); return 1
    if "--all" in argv: print("✓ no secrets found in tracked files")
    return 0


if __name__ == "__main__":
    sys.exit(main())
