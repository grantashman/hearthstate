import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from hearthstate.agentmail import build_message, send_message


class AgentMailSenderTests(unittest.TestCase):
    def test_build_message_uses_absolute_public_link_without_exposing_token_in_subject(self):
        message = build_message(
            {
                "email": "billie@example.test",
                "url": "/login?token=secret-token",
            },
            kind="sign_in",
            public_url="https://hearthstate.example.test",
        )
        self.assertEqual(message["to"], "billie@example.test")
        self.assertEqual(message["subject"], "Your Hearthstate sign-in link")
        self.assertIn("https://hearthstate.example.test/login?token=secret-token", message["text"])
        self.assertNotIn("secret-token", message["subject"])

    def test_build_message_supports_briefing_without_a_bearer_token_in_metadata(self):
        message = build_message(
            {
                "email": "grant@example.test",
                "text": "Good morning — Hearthstate briefing: Tasks: school form.",
            },
            kind="briefing",
        )
        self.assertEqual(message["to"], "grant@example.test")
        self.assertEqual(message["subject"], "Your Hearthstate morning briefing")
        self.assertIn("school form", message["text"])

    def test_send_message_reads_protected_secrets_and_posts_to_agentmail(self):
        with tempfile.TemporaryDirectory() as directory:
            secret_dir = Path(directory)
            (secret_dir / "agentmail_api_key").write_text("test-api-key")
            (secret_dir / "agentmail_inbox_id").write_text("inbox-123")
            captured = {}

            class Response:
                def __enter__(self):
                    return self

                def __exit__(self, *_):
                    return False

                def read(self):
                    return b'{"message_id":"msg-123"}'

            def fake_urlopen(request, timeout):
                captured["url"] = request.full_url
                captured["headers"] = dict(request.headers)
                captured["body"] = json.loads(request.data.decode())
                captured["timeout"] = timeout
                return Response()

            with patch("hearthstate.agentmail.urlopen", fake_urlopen):
                result = send_message(
                    {"to": "billie@example.test", "subject": "Test", "text": "Hello"},
                    secret_dir=secret_dir,
                )

            self.assertEqual(result["message_id"], "msg-123")
            self.assertEqual(captured["url"], "https://api.agentmail.to/v0/inboxes/inbox-123/messages/send")
            self.assertEqual(captured["body"]["to"], "billie@example.test")
            self.assertEqual(captured["timeout"], 30)


if __name__ == "__main__":
    unittest.main()
