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
        # Force the mock paths so tests never hit the Meta network API.
        # Patched BEFORE importing app.main: load_dotenv() won't override it.
        cls._env = patch.dict(os.environ, {"META_LLAMA_API_KEY": "", "MUSE_IMAGE_API_KEY": ""})
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
        self.assertIn("extends CharacterBody2D", r1.json()["code_content"])
        self.assertEqual(r1.json()["status"], "mock")
        r2 = self.client.post(
            "/api/v1/generate-asset",
            json={"prompt": "slime", "asset_type": "concept_art", "style": "watercolor"},
        )
        self.assertEqual(r2.status_code, 200, r2.text)
        self.assertIn("image_url", r2.json())
        self.assertEqual(r2.json()["status"], "placeholder")
        self.assertIn("watercolor", r2.json()["prompt_used"])
        self.assertIn("concept art", r2.json()["prompt_used"])

    def test_generate_code_success_path_strips_fences(self):
        import app.main as main_module
        from app.agents.code_agent import CodeGenAgent
        from unittest.mock import AsyncMock

        agent = CodeGenAgent(api_key="dummy-test-key")
        agent._call_meta_api = AsyncMock(
            return_value={
                "status": "completed",
                "output": [
                    {
                        "type": "message",
                        "content": [
                            {
                                "type": "output_text",
                                "text": "```gdscript\nextends CharacterBody2D\n\n@export var speed := 200.0\n```",
                            }
                        ],
                    }
                ],
            }
        )
        old = main_module.code_agent
        main_module.code_agent = agent
        try:
            resp = self.client.post(
                "/api/v1/generate-code", json={"prompt": "double jump", "engine": "Godot 4"}
            )
        finally:
            main_module.code_agent = old
        self.assertEqual(resp.status_code, 200, resp.text)
        body = resp.json()
        self.assertEqual(body["status"], "success")
        self.assertEqual(body["code_content"], "extends CharacterBody2D\n\n@export var speed := 200.0")
        self.assertEqual(body["language"], "GDScript")

    def test_build_prompt_varies_by_doc_type(self):
        # Regression: doc_type was plumbed through but never reached the Meta prompt,
        # so every format returned similar content.
        from app.agents.gdd_agent import GDDAgent, GDDType

        agent = GDDAgent(api_key="dummy-test-key")
        one = agent._build_prompt("x", "g", "e", GDDType.ONE_SHEET)
        full = agent._build_prompt("x", "g", "e", GDDType.FULL_GDD)
        beat = agent._build_prompt("x", "g", "e", GDDType.BEAT_CHART)
        self.assertNotEqual(one, full)
        self.assertIn("ONE-SHEET", one)
        self.assertIn("FULL GAME DESIGN", full)
        self.assertIn('"beat_chart"', beat)
        self.assertNotIn('"beat_chart"', one)

    def test_generate_gdd_malformed_meta_output_falls_back_to_mock(self):
        # Regression: off-schema Meta output (common on big full_gdd answers) once
        # raised an uncaught TypeError -> HTTP 500. It must fall back to mock 200.
        import app.main as main_module
        from app.agents.gdd_agent import GDDAgent
        from unittest.mock import AsyncMock

        one_sheet = (
            '"one_sheet": {"title": "t", "target_systems": ["PC"], "target_age": "12+",'
            ' "esrb_rating": "E", "story_summary": "s", "gameplay_modes": ["Solo"],'
            ' "usps": ["u"], "competitive_products": ["c"]}'
        )
        shapes = {
            "beat_chart as object": "{" + one_sheet + ', "beat_chart": {"lvl": "x"}, "visual_style_prompt": "v"}',
            "level as string": "{" + one_sheet + ', "beat_chart": ["nope"], "visual_style_prompt": "v"}',
            "one_sheet as list": '{"one_sheet": [], "visual_style_prompt": "v"}',
            "top-level list": '["nope"]',
        }
        for name, text in shapes.items():
            with self.subTest(name):
                agent = GDDAgent(api_key="dummy-test-key")
                agent._call_meta_api = AsyncMock(
                    return_value={
                        "status": "completed",
                        "output": [
                            {
                                "type": "message",
                                "content": [{"type": "output_text", "text": text}],
                            }
                        ],
                    }
                )
                old = main_module.gdd_agent
                main_module.gdd_agent = agent
                try:
                    resp = self.client.post(
                        "/api/v1/generate-gdd",
                        json={"prompt": "z", "doc_type": "full_gdd"},
                    )
                finally:
                    main_module.gdd_agent = old
                self.assertEqual(resp.status_code, 200, f"{name}: {resp.text}")
                self.assertEqual(resp.json()["status"], "mock", name)


if __name__ == "__main__":
    unittest.main()
