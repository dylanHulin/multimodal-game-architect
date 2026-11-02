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
        import app.routers.gdd_router as router_module
        from app.agents.gdd_agent import GDDAgent

        router_module.gdd_agent = GDDAgent()
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
        self.assertEqual(body["images"], [])

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

    def test_sanitize_prompt_removes_gore_triggers(self):
        from app.agents.asset_agent import AssetAgent

        out = AssetAgent._sanitize_prompt(
            "Zombie horde, blood red sky, dismembered corpses, gore and rotting flesh, "
            "killer dead, shotgun shooting"
        )
        self.assertIn("crimson sky", out)
        self.assertIn("broken fallen figures", out)
        self.assertIn("stylized shading and weathered skin", out)
        self.assertIn("shadowy hunter ancient", out)
        self.assertIn("blaster action", out)
        self.assertIn("non-graphic", out)
        self.assertIn("Zombie", out)  # subject preserved
        self.assertNotIn("blood red", out)

    def test_generate_asset_retries_sanitized_on_policy_violation(self):
        # Regression: chained GDD style prompts trip Meta's image content
        # filter (400). The agent must retry once sanitized, not placeholder.
        import app.main as main_module
        import httpx
        from app.agents.asset_agent import AssetAgent
        from unittest.mock import AsyncMock, MagicMock, patch

        resp_400 = MagicMock()
        resp_400.status_code = 400
        resp_400.text = '{"error":{"code":"content_policy_violation","message":"filtered"}}'
        resp_400.raise_for_status = MagicMock(
            side_effect=httpx.HTTPStatusError("400", request=MagicMock(), response=resp_400)
        )
        resp_200 = MagicMock()
        resp_200.status_code = 200
        resp_200.text = "{}"
        resp_200.json = MagicMock(
            return_value={
                "status": "completed",
                "output": [
                    {
                        "type": "image_generation_call",
                        "status": "completed",
                        "result": "UklGR" + "A" * 203,
                    }
                ],
            }
        )
        resp_200.raise_for_status = MagicMock()
        posted = []

        async def fake_post(url, headers=None, json=None, **kwargs):
            posted.append(json)
            return resp_400 if len(posted) == 1 else resp_200

        client = MagicMock()
        client.__aenter__ = AsyncMock(return_value=client)
        client.__aexit__ = AsyncMock(return_value=False)
        client.post = fake_post

        agent = AssetAgent(api_key="dummy-test-key")
        old = main_module.asset_agent
        main_module.asset_agent = agent
        try:
            with patch.object(httpx, "AsyncClient", MagicMock(return_value=client)):
                resp = self.client.post(
                    "/api/v1/generate-asset",
                    json={"prompt": "blood and gore everywhere", "asset_type": "sprite"},
                )
        finally:
            main_module.asset_agent = old
        self.assertEqual(resp.status_code, 200, resp.text)
        body = resp.json()
        self.assertEqual(body["status"], "success")
        self.assertTrue(body["image_url"].startswith("data:image/"))
        self.assertEqual(len(posted), 2)
        self.assertIn("crimson mist", posted[1]["input"])
        self.assertIn("non-graphic", posted[1]["input"])

    def test_build_image_prompt_differs_by_asset_type(self):
        # Regression: sprite and ui_concept prompts collapsed into generic
        # scene descriptions, so every asset rendered as concept art.
        from app.agents.asset_agent import AssetAgent

        sprite = AssetAgent._build_image_prompt("dark cemetery scene", "sprite", "pixel art")
        ui = AssetAgent._build_image_prompt("dark cemetery scene", "ui_concept", "pixel art")
        concept = AssetAgent._build_image_prompt("dark cemetery scene", "concept_art", "pixel art")
        self.assertIn("ONE character or object only", sprite)
        self.assertIn("NO environment", sprite)
        self.assertIn("interface", ui.lower())
        self.assertIn("NO 3D scene", ui)
        self.assertIn("environment shot", concept)
        self.assertNotEqual(sprite, ui)
        self.assertNotEqual(sprite, concept)

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
        import app.routers.gdd_router as router_module
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
                old = router_module.gdd_agent
                router_module.gdd_agent = agent
                try:
                    resp = self.client.post(
                        "/api/v1/generate-gdd",
                        json={"prompt": "z", "doc_type": "full_gdd"},
                    )
                finally:
                    router_module.gdd_agent = old
                self.assertEqual(resp.status_code, 200, f"{name}: {resp.text}")
                self.assertEqual(resp.json()["status"], "mock", name)


    def test_generate_gdd_rich_payload_with_visuals_mock(self):
        # Refactor guard: the unified endpoint accepts the rich GDDForm
        # payload (overrides + sections + visual configs) with MOCK_VISUALS.
        import app.routers.gdd_router as router_module

        old_flag = router_module.MOCK_VISUALS
        router_module.MOCK_VISUALS = True
        try:
            resp = self.client.post(
                "/api/v1/generate-gdd",
                json={
                    "doc_type": "ten_pager",
                    "title": "My Game",
                    "platform": "PC",
                    "audience": "12+",
                    "pitch": "Do stuff",
                    "usp": "It is fun",
                    "camera": "top_down",
                    "character": "Hero",
                    "controls": "WASD",
                    "core_loop": "loop",
                    "menu_flow": "flow",
                    "visuals": [
                        {"asset_type": "concept_art", "enabled": True, "count": 2},
                        {"asset_type": "sprite", "enabled": False, "count": 5},
                    ],
                },
            )
        finally:
            router_module.MOCK_VISUALS = old_flag
        self.assertEqual(resp.status_code, 200, resp.text)
        body = resp.json()
        self.assertEqual(body["one_sheet"]["title"], "My Game")
        self.assertEqual(body["one_sheet"]["story_summary"], "Do stuff")
        self.assertEqual(body["one_sheet"]["target_systems"], ["PC"])
        self.assertEqual(body["ten_pager"]["camera"], "top_down")
        self.assertEqual(body["ten_pager"]["core_loop"], "loop")
        self.assertIsNone(body.get("full_gdd"))
        self.assertEqual(len(body["images"]), 2)
        self.assertTrue(all(i["status"] == "mock" for i in body["images"]))
        self.assertTrue(all(i["asset_type"] == "concept_art" for i in body["images"]))

    def test_generate_gdd_rejects_missing_content(self):
        resp = self.client.post("/api/v1/generate-gdd", json={"doc_type": "one_sheet"})
        self.assertEqual(resp.status_code, 400)


    def test_generate_code_unreal_mock(self):
        resp = self.client.post(
            "/api/v1/generate-code", json={"prompt": "double jump", "engine": "Unreal Engine"}
        )
        self.assertEqual(resp.status_code, 200, resp.text)
        body = resp.json()
        self.assertEqual(body["language"], "C++")
        self.assertEqual(body["file_name"], "PlayerCharacter.h")
        self.assertIn("ACharacter", body["code_content"])

    def test_user_bearer_key_reaches_meta_for_code(self):
        # BYOK: the user Bearer token (not the server key) must land in the
        # Authorization header of the Meta call. Env keys are empty here.
        import httpx
        from unittest.mock import AsyncMock, MagicMock, patch

        seen = {}
        resp_200 = MagicMock()
        resp_200.status_code = 200
        resp_200.json = MagicMock(
            return_value={
                "status": "completed",
                "output": [
                    {
                        "type": "message",
                        "content": [{"type": "output_text", "text": "extends CharacterBody2D"}],
                    }
                ],
            }
        )
        resp_200.raise_for_status = MagicMock()

        async def fake_post(url, headers=None, json=None, **kwargs):
            seen.update(headers or {})
            return resp_200

        client = MagicMock()
        client.__aenter__ = AsyncMock(return_value=client)
        client.__aexit__ = AsyncMock(return_value=False)
        client.post = fake_post

        with patch.object(httpx, "AsyncClient", MagicMock(return_value=client)):
            resp = self.client.post(
                "/api/v1/generate-code",
                json={"prompt": "x", "engine": "Godot 4"},
                headers={"Authorization": "Bearer user-key-abc-123"},
            )
        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertEqual(seen.get("Authorization"), "Bearer user-key-abc-123")

    def test_user_bearer_key_reaches_meta_for_asset(self):
        # Same forwarding guarantee on the image route.
        import httpx
        from unittest.mock import AsyncMock, MagicMock, patch

        seen = {}
        resp_200 = MagicMock()
        resp_200.status_code = 200
        resp_200.json = MagicMock(
            return_value={
                "status": "completed",
                "output": [
                    {
                        "type": "image_generation_call",
                        "status": "completed",
                        "result": "UklGR" + "A" * 203,
                    }
                ],
            }
        )
        resp_200.raise_for_status = MagicMock()

        async def fake_post(url, headers=None, json=None, **kwargs):
            seen.update(headers or {})
            return resp_200

        client = MagicMock()
        client.__aenter__ = AsyncMock(return_value=client)
        client.__aexit__ = AsyncMock(return_value=False)
        client.post = fake_post

        with patch.object(httpx, "AsyncClient", MagicMock(return_value=client)):
            resp = self.client.post(
                "/api/v1/generate-asset",
                json={"prompt": "slime", "asset_type": "sprite"},
                headers={"Authorization": "Bearer user-key-abc-123"},
            )
        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertEqual(seen.get("Authorization"), "Bearer user-key-abc-123")

    def test_short_or_missing_bearer_falls_back_without_401(self):
        # Optional BYOK: no 401 ever; short/absent tokens use server keys
        # (mock paths here since env keys are empty in tests).
        r1 = self.client.post(
            "/api/v1/generate-code", json={"prompt": "x", "engine": "Godot 4"}
        )
        self.assertEqual(r1.status_code, 200)
        self.assertEqual(r1.json()["status"], "mock")
        r2 = self.client.post(
            "/api/v1/generate-code",
            json={"prompt": "x", "engine": "Godot 4"},
            headers={"Authorization": "Bearer abc"},
        )
        self.assertEqual(r2.status_code, 200, r2.text)
        self.assertEqual(r2.json()["status"], "mock")

    def test_generate_gdd_one_sheet_ignores_stale_rich_fields(self):
        # Bug: ten_pager/full_gdd sections were echoed from stale request
        # fields even for doc_type=one_sheet, so downloads contained all types.
        resp = self.client.post(
            "/api/v1/generate-gdd",
            json={
                "doc_type": "one_sheet",
                "title": "T",
                "pitch": "P",
                "camera": "top_down",
                "character": "H",
                "controls": "W",
                "core_loop": "L",
                "menu_flow": "M",
                "lore": "stale",
                "level_design": "stale",
                "features": ["multiplayer"],
                "ai_type": "goap",
                "physics_engine": "box2d",
            },
        )
        self.assertEqual(resp.status_code, 200, resp.text)
        body = resp.json()
        self.assertIsNone(body.get("ten_pager"))
        self.assertIsNone(body.get("full_gdd"))
        self.assertIsNone(body.get("beat_chart"))

    def test_generate_gdd_ten_pager_ignores_stale_full_fields(self):
        resp = self.client.post(
            "/api/v1/generate-gdd",
            json={
                "doc_type": "ten_pager",
                "title": "T",
                "pitch": "P",
                "camera": "top_down",
                "core_loop": "L",
                "lore": "stale",
                "features": ["multiplayer"],
            },
        )
        self.assertEqual(resp.status_code, 200, resp.text)
        body = resp.json()
        self.assertIsNotNone(body.get("ten_pager"))
        self.assertEqual(body["ten_pager"]["camera"], "top_down")
        self.assertIsNone(body.get("full_gdd"))

    def test_generate_gdd_forwards_user_key_to_agent(self):
        # The GDD route must construct its agent with the user key.
        import app.routers.gdd_router as router_module
        from unittest.mock import patch

        real = router_module.GDDAgent
        seen = {}

        def spy(api_key=None):
            seen["api_key"] = api_key
            return real(api_key=api_key)

        with patch.object(router_module, "GDDAgent", side_effect=spy):
            resp = self.client.post(
                "/api/v1/generate-gdd",
                json={"prompt": "z", "doc_type": "one_sheet"},
                headers={"Authorization": "Bearer user-key-xyz-789"},
            )
        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertEqual(seen.get("api_key"), "user-key-xyz-789")


if __name__ == "__main__":
    unittest.main()
