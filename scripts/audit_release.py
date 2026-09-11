"""Supplementary release audit of Git blobs and metadata. Prints no matched data."""
import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PATTERNS = {
    "private_key": rb"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----",
    "github_token": rb"(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{40,})",
    "api_key": rb"\bsk-[A-Za-z0-9_-]{24,}",
    "aws_key": rb"\bAKIA[A-Z0-9]{16}\b",
    "windows_user_path": rb"[A-Za-z]:[\\/]+Users[\\/]+(?!Public\b|Default\b)[^\s\"'<>]+",
    "unix_user_path": rb"/(?:home|Users)/[A-Za-z0-9_.-]+/",
    "wechat_temporary_key": rb"[?&](?:pass_ticket|uin|key|wxtoken)=([^&\s\"<>]{12,})",
}
ALLOWED_TOP = {"SKILL.md", "README.md", "LICENSE", "pyproject.toml", ".gitignore", ".gitattributes", "agents", "references", "scripts", "tests", ".github"}


def git(*args):
    return subprocess.check_output(["git", *args], cwd=ROOT, stderr=subprocess.DEVNULL)


def scan(data):
    return [name for name, pattern in PATTERNS.items() if re.search(pattern, data)]


def audit(staged=False):
    findings = []
    if staged:
        entries = git("ls-files", "--stage", "-z").split(b"\0")
        objects = []
        for entry in entries:
            if entry:
                details, path = entry.split(b"\t", 1)
                mode, oid, _ = details.split()
                objects.append((oid, path))
                if mode == b"120000":
                    findings.append({"object": oid.decode()[:12], "rule": "symlink_in_release"})
    else:
        objects = []
        for line in git("rev-list", "--objects", "--all").splitlines():
            oid, _, path = line.partition(b" ")
            if git("cat-file", "-t", oid.decode()).strip() == b"blob":
                objects.append((oid, path))
        metadata = git("log", "--all", "--format=%an <%ae>%n%cn <%ce>%n%B")
        for rule in scan(metadata):
            findings.append({"object": "commit-metadata", "rule": rule})
        # Report addresses requiring review, without exposing them in logs.
        addresses = re.findall(rb"<([^<>\s]+@[^<>\s]+)>", metadata)
        for address in set(addresses):
            if not address.endswith((b"@example.invalid", b"@users.noreply.github.com")):
                findings.append({"object": "commit-metadata", "rule": "review_commit_email"})
    for oid, path in objects:
        label = oid.decode()[:12]
        top = path.decode("utf-8").split("/", 1)[0]
        if top not in ALLOWED_TOP:
            findings.append({"object": label, "rule": "unexpected_release_path"})
        data = git("cat-file", "blob", oid.decode())
        for rule in scan(data) + scan(path):
            findings.append({"object": label, "rule": rule})
    return {"status": "failed" if findings else "success", "scope": "index" if staged else "all_history", "blobs_checked": len(objects), "findings": findings}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--staged", action="store_true")
    args = parser.parse_args()
    try:
        result = audit(args.staged)
    except Exception:
        result = {"status": "failed", "error": "audit_failed"}
    print(json.dumps(result))
    sys.exit(result["status"] != "success")
