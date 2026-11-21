import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import redact as r  # noqa: E402

# Test values are assembled at runtime so this file itself trips no secret scanner.
WEBHOOK = "https://discord.com/api/webhooks/" + "123456789012345678/" + "AbCdEf_GhIjKlMnOpQrStUvWxYz0123456789"
GITHUB = "ghp" + "_" + "A" * 36
AWS = "AKIA" + "ABCDEFGHIJKLMNOP"
JWT = "eyJ" + "hbGciOiJIUzI1NiJ9" + ".eyJ" + "zdWIiOiIxMjM0NTY3ODkwIn0" + ".SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV"
PEM = "-----BEGIN OPENSSH " + "PRIVATE KEY-----\nabc\ndef\n-----END OPENSSH " + "PRIVATE KEY-----"


def redact(text, known=()):
    counts = {}
    return r.redact_text(text, list(known), counts), counts


class PatternTests(unittest.TestCase):
    def test_formats(self):
        cases = {
            WEBHOOK: "discord-webhook",
            GITHUB: "github-token",
            AWS: "aws-access-key",
            "cfut" + "_" + "Ab1" * 16: "cloudflare-token",
            JWT: "jwt",
            PEM: "private-key",
            "Authorization: Bearer " + "x" * 30: "bearer",
            "https://admin:" + "hunter2hunter2" + "@db.example.com/x": "url-credentials",
        }
        for text, kind in cases.items():
            out, counts = redact(f"before {text} after")
            self.assertIn(kind, counts, text)
            self.assertNotIn(text, out)
            self.assertTrue(out.startswith("before ") and out.endswith(" after"), out)

    def test_assignment(self):
        out, counts = redact("DB_PASSWORD=" + "s3cr3t-value-123")
        self.assertEqual(out, "DB_PASSWORD=[REDACTED:assignment]")
        out, _ = redact('{"api_key": "' + "abcd1234efgh5678" + '"}')
        self.assertNotIn("abcd1234efgh5678", out)

    def test_placeholders_and_short_values_kept(self):
        for text in ("PASSWORD=${DB_PASSWORD}", "token: $TOKEN", "secret=<x>", "password=short", "no secrets here"):
            out, counts = redact(text)
            self.assertEqual(out, text)
            self.assertEqual(counts, {})

    def test_known_secrets_longest_first(self):
        out, counts = redact("a correcthorse b correcthorsebattery c", ["correcthorse", "correcthorsebattery"])
        self.assertEqual(out, "a [REDACTED:known] b [REDACTED:known] c")
        self.assertEqual(counts["known"], 2)


class StructureTests(unittest.TestCase):
    def test_shape_preserved(self):
        response = {"stdout": "ok " + GITHUB, "stderr": "", "interrupted": False, "isImage": False, "lines": [AWS, 3]}
        output = r.build_output({"tool_response": response}, [])
        updated = output["hookSpecificOutput"]["updatedToolOutput"]
        self.assertEqual(set(updated), set(response))
        self.assertIs(updated["interrupted"], False)
        self.assertEqual(updated["lines"][1], 3)
        self.assertNotIn(GITHUB, json.dumps(updated))
        self.assertNotIn(AWS, json.dumps(updated))
        self.assertEqual(output["hookSpecificOutput"]["hookEventName"], "PostToolUse")

    def test_string_response(self):
        output = r.build_output({"tool_response": "x " + WEBHOOK}, [])
        self.assertEqual(output["hookSpecificOutput"]["updatedToolOutput"], "x [REDACTED:discord-webhook]")

    def test_nothing_to_redact(self):
        self.assertIsNone(r.build_output({"tool_response": {"stdout": "hello"}}, []))
        self.assertIsNone(r.build_output({"tool_name": "Bash"}, []))


class MainTests(unittest.TestCase):
    def run_main(self, stdin_text, secrets=None, mode=("output",)):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "known.txt")
            with open(path, "w", encoding="utf-8") as handle:
                handle.write("\n".join(secrets or []))
            old_env, old_stdin = os.environ.get("CLAUDE_REDACT_SECRETS_FILE"), sys.stdin
            os.environ["CLAUDE_REDACT_SECRETS_FILE"] = path
            sys.stdin, buffer = io.StringIO(stdin_text), io.StringIO()
            try:
                with redirect_stdout(buffer):
                    code = r.main(mode)
            finally:
                sys.stdin = old_stdin
                if old_env is None:
                    os.environ.pop("CLAUDE_REDACT_SECRETS_FILE", None)
                else:
                    os.environ["CLAUDE_REDACT_SECRETS_FILE"] = old_env
        return code, buffer.getvalue()

    def test_known_secret_from_file(self):
        event = {"tool_name": "Bash", "tool_response": {"stdout": "pw is MyLocalSecret42"}}
        code, out = self.run_main(json.dumps(event), ["MyLocalSecret42", "# comment", "tiny"])
        self.assertEqual(code, 0)
        self.assertIn("[REDACTED:known]", out)
        self.assertNotIn("MyLocalSecret42", out)

    def test_bad_input_fails_open(self):
        self.assertEqual(self.run_main("not json"), (0, ""))
        self.assertEqual(self.run_main("{}", mode=("unknown-mode",)), (0, ""))


class PromptTests(unittest.TestCase):
    def test_blocks_pasted_secret_without_echoing_it(self):
        out = r.build_prompt_block({"prompt": "here is my config:\n" + WEBHOOK}, [])
        self.assertEqual(out["decision"], "block")
        self.assertIn("discord-webhook", out["reason"])
        self.assertNotIn(WEBHOOK, json.dumps(out))
        self.assertTrue(out["hookSpecificOutput"]["suppressOriginalPrompt"])
        self.assertEqual(out["hookSpecificOutput"]["hookEventName"], "UserPromptSubmit")

    def test_known_confidential_term(self):
        out = r.build_prompt_block({"prompt": "the codename is ProjectBluebird"}, ["ProjectBluebird"])
        self.assertIn("known x1", out["reason"])

    def test_clean_prompt_and_allow_marker_pass(self):
        self.assertIsNone(r.build_prompt_block({"prompt": "upgrade the caddy build"}, []))
        self.assertIsNone(r.build_prompt_block({"prompt": "[allow-secrets] test with " + GITHUB}, []))
        self.assertIsNone(r.build_prompt_block({}, []))

    def test_prompt_mode_via_main(self):
        code, out = MainTests().run_main(json.dumps({"prompt": "key " + AWS}), mode=("prompt",))
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)["decision"], "block")


if __name__ == "__main__":
    unittest.main()
