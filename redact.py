#!/usr/bin/env python3
"""Claude Code hooks that keep secrets away from the model.

    redact.py output   PostToolUse: if any string in `tool_response` contains a secret, prints a
                       `hookSpecificOutput.updatedToolOutput` with the same structure and the secrets
                       replaced by `[REDACTED:<kind>]`.
    redact.py prompt   UserPromptSubmit: if the prompt contains a secret (for example something pasted
                       by accident), blocks it before it reaches the model and says which kinds were
                       found, never the values. Claude Code cannot rewrite a prompt, only block it.
                       Put `[allow-secrets]` anywhere in the prompt to send it anyway.

Both read the hook event (JSON) on stdin and print nothing when there is nothing to do.
Never fails loudly: on any error it exits 0 without output, so the event passes through
unchanged (fail-open). Standard library only.
"""
from __future__ import annotations

import json
import os
import re
import sys

# Exact values to mask, one per line ('#' starts a comment). Never print this file.
DEFAULT_SECRETS_FILE = os.path.join(os.path.expanduser("~"), ".claude", "redact", "known-secrets.txt")
MIN_KNOWN_SECRET_LENGTH = 6

# (kind, pattern, replacement). Order matters: specific formats first, generic ones last.
PATTERNS: list[tuple[str, re.Pattern[str], str]] = [
    ("private-key", re.compile(r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----.*?-----END [A-Z0-9 ]*PRIVATE KEY-----", re.S),
     "[REDACTED:private-key]"),
    ("discord-webhook", re.compile(r"https://(?:ptb\.|canary\.)?discord(?:app)?\.com/api/webhooks/\d+/[\w-]+"),
     "[REDACTED:discord-webhook]"),
    ("slack-webhook", re.compile(r"https://hooks\.slack\.com/services/[\w/]+"), "[REDACTED:slack-webhook]"),
    ("url-credentials", re.compile(r"(?<=://)[^/\s:@]+:[^/\s@]+(?=@)"), "[REDACTED:url-credentials]"),
    ("jwt", re.compile(r"\beyJ[\w-]{10,}\.eyJ[\w-]{10,}\.[\w-]{10,}"), "[REDACTED:jwt]"),
    ("anthropic-key", re.compile(r"\bsk-ant-[\w-]{20,}"), "[REDACTED:anthropic-key]"),
    ("openai-key", re.compile(r"\bsk-(?:proj-)?[A-Za-z0-9_-]{32,}"), "[REDACTED:openai-key]"),
    ("github-token", re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{36,}|github_pat_[A-Za-z0-9_]{50,})"), "[REDACTED:github-token]"),
    ("gitlab-token", re.compile(r"\bglpat-[\w-]{20,}"), "[REDACTED:gitlab-token]"),
    ("aws-access-key", re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"), "[REDACTED:aws-access-key]"),
    ("google-api-key", re.compile(r"\bAIza[\w-]{35}\b"), "[REDACTED:google-api-key]"),
    ("slack-token", re.compile(r"\bxox[abprs]-[\w-]{10,}"), "[REDACTED:slack-token]"),
    ("stripe-key", re.compile(r"\b(?:sk|rk)_live_[A-Za-z0-9]{20,}"), "[REDACTED:stripe-key]"),
    ("telegram-bot-token", re.compile(r"\b\d{8,10}:[A-Za-z0-9_-]{35}\b"), "[REDACTED:telegram-bot-token]"),
    ("bearer", re.compile(r"(?i)(\bBearer\s+)[A-Za-z0-9._~+/=-]{16,}"), r"\1[REDACTED:bearer]"),
    # key=value / key: value with a secret-looking key. Skips placeholders such as $VAR, ${VAR}, <x>, ***.
    ("assignment", re.compile(
        r"(?i)(\b[\w.-]*(?:password|passwd|pwd|secret|token|api[_-]?key|access[_-]?key|private[_-]?key|client[_-]?secret)"
        r"[\w.-]*\"?\s*[:=]\s*\"?)(?![$<*{]|\[REDACTED)([^\s\"',;]{8,})"),
     r"\1[REDACTED:assignment]"),
]


def load_known_secrets(path: str) -> list[str]:
    try:
        with open(path, encoding="utf-8") as handle:
            lines = (line.rstrip("\r\n") for line in handle)
            values = {line for line in lines if len(line) >= MIN_KNOWN_SECRET_LENGTH and not line.startswith("#")}
    except OSError:
        return []
    return list(values)


def redact_text(text: str, known: list[str], counts: dict[str, int]) -> str:
    # Longest first, so a secret that contains another one is replaced whole.
    for secret in sorted(known, key=len, reverse=True):
        if secret in text:
            counts["known"] = counts.get("known", 0) + text.count(secret)
            text = text.replace(secret, "[REDACTED:known]")
    for kind, pattern, replacement in PATTERNS:
        text, hits = pattern.subn(replacement, text)
        if hits:
            counts[kind] = counts.get(kind, 0) + hits
    return text


def redact_value(value, known: list[str], counts: dict[str, int]):
    """Redact every string inside value, keeping its structure (dicts, lists, scalars)."""
    if isinstance(value, str):
        return redact_text(value, known, counts)
    if isinstance(value, dict):
        return {key: redact_value(item, known, counts) for key, item in value.items()}
    if isinstance(value, list):
        return [redact_value(item, known, counts) for item in value]
    return value


def build_output(event: dict, known: list[str]) -> dict | None:
    if "tool_response" not in event:
        return None
    counts: dict[str, int] = {}
    redacted = redact_value(event["tool_response"], known, counts)
    if not counts:
        return None
    return {
        "hookSpecificOutput": {
            "hookEventName": "PostToolUse",
            "updatedToolOutput": redacted,
            "additionalContext": f"Secret redaction hook replaced values in this tool output: {summarise(counts)}.",
        }
    }


ALLOW_MARKER = "[allow-secrets]"


def summarise(counts: dict[str, int]) -> str:
    return ", ".join(f"{kind} x{n}" for kind, n in sorted(counts.items()))


def build_prompt_block(event: dict, known: list[str]) -> dict | None:
    prompt = event.get("prompt")
    if not isinstance(prompt, str) or ALLOW_MARKER in prompt:
        return None
    counts: dict[str, int] = {}
    redact_text(prompt, known, counts)
    if not counts:
        return None
    return {
        "decision": "block",
        "reason": (f"Prompt not sent: it looks like it contains a secret ({summarise(counts)}). "
                   f"Remove it and send again, or add {ALLOW_MARKER} to the prompt to send it as it is. "
                   "The text may still be in your local prompt history and session transcript."),
        "hookSpecificOutput": {"hookEventName": "UserPromptSubmit", "suppressOriginalPrompt": True},
    }


MODES = {"output": build_output, "prompt": build_prompt_block}


def main(argv: list[str] | None = None) -> int:
    try:
        args = sys.argv[1:] if argv is None else argv
        build = MODES[args[0] if args else "output"]
        event = json.load(sys.stdin)
        known = load_known_secrets(os.environ.get("CLAUDE_REDACT_SECRETS_FILE", DEFAULT_SECRETS_FILE))
        output = build(event, known)
        if output is not None:
            sys.stdout.write(json.dumps(output))
    except Exception:  # fail-open: never break the tool call
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
