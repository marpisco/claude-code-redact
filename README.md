# claude-code-redact

[Claude Code](https://code.claude.com) hooks that keep secrets away from the model:

- **`output`** redacts secrets from tool output **before the model sees it**.
- **`prompt`** stops a prompt that contains a secret (pasted by accident) **before it is sent**.

## Tool output (`redact.py output`)

Run a command that prints a token, a webhook URL or a private key, and Claude receives
`[REDACTED:<kind>]` instead of the value. It works on the output of `Bash`, `PowerShell`, `Read`, `Grep`,
`WebFetch` and MCP tools, through a `PostToolUse` hook that returns `updatedToolOutput`.

```
$ echo "webhook: https://discord.com/api/webhooks/1234/abcd…"
webhook: [REDACTED:discord-webhook]          ← what Claude sees
```

## Pasted secrets in prompts (`redact.py prompt`)

A `UserPromptSubmit` hook. If your prompt contains anything from the table below (or a confidential term from
your known-secrets file), the prompt is **not sent** and you get a message naming the kinds found, never the values:

```
Prompt not sent: it looks like it contains a secret (discord-webhook x1). Remove it and send again,
or add [allow-secrets] to the prompt to send it as it is.
```

Claude Code cannot rewrite a prompt, only block it, so the hook blocks rather than redacts. Add `[allow-secrets]`
anywhere in a prompt to send it on purpose (for example a fake token you are testing with).

One file, `redact.py`, standard library only, no dependencies.

## What it catches

| Kind | Example shape |
|---|---|
| `private-key` | `-----BEGIN … PRIVATE KEY----- … -----END … PRIVATE KEY-----` |
| `discord-webhook`, `slack-webhook` | `https://discord.com/api/webhooks/<id>/<token>`, `https://hooks.slack.com/services/…` |
| `url-credentials` | the `user:password` part of `https://user:password@host/…` |
| `jwt` | `eyJ….eyJ….…` |
| `anthropic-key`, `openai-key` | `sk-ant-…`, `sk-…` / `sk-proj-…` |
| `github-token`, `gitlab-token` | `ghp_…`, `gho_…`, `github_pat_…`, `glpat-…` |
| `aws-access-key`, `google-api-key` | `AKIA…`, `ASIA…`, `AIza…` |
| `slack-token`, `stripe-key`, `telegram-bot-token` | `xoxb-…`, `sk_live_…`, `123456789:AA…` |
| `bearer` | `Bearer <token>` |
| `assignment` | `PASSWORD=…`, `api_key: …`, `"client_secret": "…"` (values of 8+ characters; `$VAR`, `${VAR}`, `<x>` are left alone) |
| `known` | any exact value you list in a local file (see below) |

When something is redacted, the hook also tells Claude which kinds it replaced (via `additionalContext`),
so the model knows the output was changed and doesn't try to "fix" it.

## Install

Requires Python 3.9+ on `PATH` and a Claude Code version whose hooks support `updatedToolOutput`.

1. Copy `redact.py` to `~/.claude/hooks/redact.py`.
2. Add the hooks to `~/.claude/settings.json` (merge with any `hooks` you already have):

   ```json
   {
     "hooks": {
       "PostToolUse": [
         {
           "matcher": "Bash|PowerShell|Read|Grep|WebFetch|mcp__.*",
           "hooks": [
             {
               "type": "command",
               "command": "python3 -I ~/.claude/hooks/redact.py output",
               "timeout": 10
             }
           ]
         }
       ],
       "UserPromptSubmit": [
         {
           "hooks": [
             {
               "type": "command",
               "command": "python3 -I ~/.claude/hooks/redact.py prompt",
               "timeout": 10
             }
           ]
         }
       ]
     }
   }
   ```

   On Windows use the full path, e.g. `python -I "C:/Users/<you>/.claude/hooks/redact.py" output`.
3. Start a new Claude Code session (settings are read at start).

### Known secrets (optional)

Put exact values you never want the model to see (secrets, or confidential terms such as project codenames), one per line, in `~/.claude/redact/known-secrets.txt`
(or point `CLAUDE_REDACT_SECRETS_FILE` at another file). Lines starting with `#` and values shorter than
6 characters are ignored. Write this file yourself and keep it out of every repository; it is the one place
the secrets stay in clear text. Consider a deny rule so the model can't read it with the `Read` tool:

```json
{ "permissions": { "deny": ["Read(~/.claude/redact/**)"] } }
```

## Test it

```bash
python3 -m unittest discover -s tests
```

Then, in a Claude Code session, ask Claude to run a command that prints a fake secret, for example
`echo "token: ghp_$(printf 'Z%.0s' $(seq 1 36))"`. Claude should get `[REDACTED:github-token]`.
To test the prompt hook, send a prompt containing a fake token such as `AKIA` followed by 16 capital letters:
it should be refused.

## Limits

- **Fail-open.** If the script crashes, gets bad input, or Claude Code ignores an output of the wrong shape,
  the original output passes through. The hook never blocks a tool call.
- **Pattern-based.** A random password with no recognisable label or format is not caught; add such values to
  the known-secrets file.
- **Blocked prompts stay on your machine.** Claude Code still writes a blocked prompt to your local prompt
  history and session transcript; it just never reaches the model.
- **Only tool output and prompts.** The command text Claude writes (`tool_input`), files Claude writes, and
  anything already in the conversation are not changed. Encoded (base64) or line-split secrets are not caught.
- **False positives.** The `assignment` rule also masks harmless values that happen to sit after words like
  `token=` or `password:`. Tune `PATTERNS` in the script if that gets in your way.
- In our tests the local session transcript kept only the redacted output, not the original.

## How it works

`output`: Claude Code passes the hook a JSON event with `tool_response` (the tool's result). The script walks every
string in it, replaces matches, and if anything changed prints:

```json
{"hookSpecificOutput": {"hookEventName": "PostToolUse", "updatedToolOutput": { … same shape … },
 "additionalContext": "Secret redaction hook replaced values in this tool output: github-token x1."}}
```

The structure (keys, types, non-string values) is kept as it was, so Claude Code accepts the replacement.

`prompt`: the hook reads `prompt` from the event and, if it finds a secret, prints `{"decision": "block", "reason": …}`
with `suppressOriginalPrompt: true`, so the block message does not repeat your text.

## License

MIT
