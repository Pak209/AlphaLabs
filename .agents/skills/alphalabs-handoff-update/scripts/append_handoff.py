#!/usr/bin/env python3
"""Append a structured, secret-safe entry to the AlphaLabs handoff."""

from __future__ import annotations

import argparse
import re
import subprocess
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo


AGENTS = ("Codex", "Claude", "Lex", "Human")
SECRET_PATTERNS = (
    re.compile(r"(?i)\b(api[_-]?key|token|secret|password|passwd|cookie)\s*[:=]\s*\S+"),
    re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]{8,}"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b"),
    re.compile(r"\b(?:sk|xox[baprs])-[A-Za-z0-9_-]{12,}\b"),
)


def run_git(repo: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


def reject_secrets(values: list[str]) -> None:
    for value in values:
        if any(pattern.search(value) for pattern in SECRET_PATTERNS):
            raise SystemExit(
                "Refusing to append text that resembles a credential or secret value. "
                "Replace it with a generic verification statement."
            )


def bullets(values: list[str], empty: str) -> str:
    selected = values or [empty]
    return "\n".join(f"- {value}" for value in selected)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--agent", choices=AGENTS, required=True)
    parser.add_argument("--summary", required=True)
    parser.add_argument("--file", action="append", default=[])
    parser.add_argument("--command", action="append", default=[])
    parser.add_argument("--result", action="append", default=[])
    parser.add_argument("--risk", action="append", default=[])
    parser.add_argument("--next", dest="next_task", required=True)
    parser.add_argument(
        "--commit",
        default="none",
        help="Commit created by this task, or 'none' (default).",
    )
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=Path.cwd(),
        help="Repository root; defaults to the current directory.",
    )
    return parser.parse_args()


LOG_HEADING = "## Agent Activity Log"


def main() -> None:
    args = parse_args()
    repo = args.repo_root.resolve()
    handoff = repo / ".ai" / "LEX_REVIEW_HANDOFF.md"
    if not handoff.is_file():
        raise SystemExit(f"Handoff file not found: {handoff}")

    # The handoff is two-part: a refreshable "Current State Summary" on top and an
    # append-only "Agent Activity Log" below. New entries belong ONLY in the log, so
    # require its heading and append within that section (it runs to end of file).
    existing = handoff.read_text(encoding="utf-8")
    if LOG_HEADING not in existing:
        raise SystemExit(
            f"Missing '{LOG_HEADING}' heading in {handoff}. Add the Agent Activity Log "
            "section before appending entries."
        )

    all_text = [
        args.summary,
        *args.file,
        *args.command,
        *args.result,
        *args.risk,
        args.next_task,
        args.commit,
    ]
    reject_secrets(all_text)

    try:
        branch = run_git(repo, "branch", "--show-current") or "detached HEAD"
        dirty = bool(run_git(repo, "status", "--porcelain"))
    except (FileNotFoundError, subprocess.CalledProcessError) as exc:
        raise SystemExit(f"Unable to inspect git state: {exc}") from exc

    timestamp = datetime.now(ZoneInfo("America/Los_Angeles")).strftime("%Y-%m-%d %H:%M PT")
    entry = f"""

## {timestamp} — {args.agent}

Branch: {branch}
Commit: {args.commit}
Working Tree: {"modified" if dirty else "clean"}

### Summary
{args.summary}

### Files Modified
{bullets(args.file, "None (audit only).")}

### Commands / Tests Run
{bullets(args.command, "None.")}

### Results
{bullets(args.result, "No verification result recorded.")}

### Risks / Blockers
{bullets(args.risk, "None identified.")}

### Next Recommended Task
{args.next_task}
"""
    with handoff.open("a", encoding="utf-8") as stream:
        stream.write(entry)

    print(f"Appended {args.agent} handoff entry to {handoff}")


if __name__ == "__main__":
    main()
