"""Regression tests for the generate-gdd 500 and the CORS configuration.

Run from backend/:  python -m unittest discover -s tests -t .
No third-party test framework needed (stdlib unittest + FastAPI TestClient).
"""
import asyncio
import os
import sys
import unittest
from unittest.mock import patch

if sys.platform == "win32":
    # The default ProactorEventLoop opens a socketpair at construction, which
    # fails in locked-down environments. The selector loop is enough for tests.
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient


class PipelineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Force the mock GDD path so tests never hit the Meta network API.
        # Patched BEFORE importing app.main: load_dotenv() won't override it.
        cls._env = patch.dict(os.environ, {"META_LLAMA_API_KEY": ""})
        cls._env.start()
        import app.main as main_module
        from app.agents.gdd_agent import GDDAgent

        main_module.gdd_agent = GDDAgent()
        cls.client = TestClient(main_module.app)

    @classmethod
    def tearDownClass(cls):
        cls._env.stop()

    def test_generate_gdd_returns_valid_document(self):
        # Regression: endpoint once returned None -> ResponseValidationError 500.
        resp = self.client.post(
            "/api/v1/generate-gdd",
            json={"prompt": "zombies", "doc_type": "beat_chart", "engine": "Godot 4"},
        )
        self.assertEqual(resp.status_code, 200, resp.text)
        body = resp.json()
        self.assertEqual(body["document_type"], "beat_chart")
        self.assertIn("title", body["one_sheet"])
        self.assertIn("story_summary", body["one_sheet"])
        self.assertIsInstance(body["beat_chart"], list)
        self.assertIn("visual_style_prompt", body)

    def test_generate_gdd_one_sheet_has_no_beat_chart(self):
        resp = self.client.post(
            "/api/v1/generate-gdd", json={"prompt": "zombies", "doc_type": "one_sheet"}
        )
        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertIsNone(resp.json()["beat_chart"])

    def test_generate_gdd_rejects_empty_prompt(self):
        resp = self.client.post("/api/v1/generate-gdd", json={"prompt": ""})
        self.assertEqual(resp.status_code, 400)

    def test_cors_preflight_echoes_dashboard_origin(self):
        # Regression: allow_origins contained "*" with allow_credentials=True,
        # an invalid combination browsers reject.
        resp = self.client.options(
            "/api/v1/generate-gdd",
            headers={
                "Origin": "http://localhost:3000",
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "Content-Type",
            },
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(
            resp.headers.get("access-control-allow-origin"), "http://localhost:3000"
        )

    def test_generate_code_and_asset(self):
        r1 = self.client.post(
            "/api/v1/generate-code", json={"prompt": "player", "engine": "Godot 4"}
        )
        self.assertEqual(r1.status_code, 200, r1.text)
        self.assertIn("code_content", r1.json())
        r2 = self.client.post(
            "/api/v1/generate-asset", json={"prompt": "slime", "asset_type": "sprite_sheet"}
        )
        self.assertEqual(r2.status_code, 200, r2.text)
        self.assertIn("image_url", r2.json())


if __name__ == "__main__":
    unittest.main()
