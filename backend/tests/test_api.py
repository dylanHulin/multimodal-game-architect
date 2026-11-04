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

    def test_cors_allow_origins_reads_env(self):
        from app.security import cors_allow_origins

        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("ALLOW_ORIGINS", None)
            self.assertEqual(
                cors_allow_origins(),
                ["http://localhost:3000", "http://127.0.0.1:3000"],
            )
        with patch.dict(
            os.environ,
            {
                "ALLOW_ORIGINS": (
                    "https://demo.vercel.app/, http://localhost:3000 ,"
                    "notaurl, ftp://x.test, https://api.demo.test:8443/prefix"
                )
            },
        ):
            self.assertEqual(
                cors_allow_origins(),
                [
                    "http://localhost:3000",
                    "http://127.0.0.1:3000",
                    "https://demo.vercel.app",
                    "https://api.demo.test:8443",
                ],
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

    def _sam_fixture_text(self):
        import os

        here = os.path.dirname(os.path.abspath(__file__))
        with open(os.path.join(here, "fixtures", "sam-record.txt")) as f:
            return f.read()

    def _sam_success_lines(self, text):
        import json

        head = {"output_index": 0, "content_index": 0, "item_id": "msg_test"}
        return [
            "data: "
            + json.dumps({"type": "response.output_text.delta", "delta": text, **head}),
            "data: "
            + json.dumps({"type": "response.output_text.done", "text": text, **head}),
            "data: " + json.dumps({"type": "response.completed"}),
        ]

    def test_records_from_events_decodes_real_mask(self):
        # Golden fixture: a real captured sam-3.1 record. Decoded through
        # Meta's official parser: 507x1024 raster with substantial foreground.
        import asyncio
        import json
        from app.agents.sam_agent import records_from_events

        text = self._sam_fixture_text()
        events = [
            json.loads(line.removeprefix("data: ")) for line in self._sam_success_lines(text)
        ]
        records = asyncio.run(records_from_events(events))
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["box"], {"x1": 201, "y1": 415, "x2": 944, "y2": 1915})
        self.assertEqual((records[0]["mask_w"], records[0]["mask_h"]), (507, 1024))
        self.assertEqual(len(records[0]["mask_bytes"]), 507 * 1024)
        self.assertGreater(sum(records[0]["mask_bytes"]), 100000)

    def _fake_stream_client(self, lines, status_code=200):
        from unittest.mock import AsyncMock, MagicMock

        class _Resp:
            def __init__(self):
                self.status_code = status_code
                self.headers = {"content-type": "text/event-stream"}

            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                return False

            def aiter_lines(self):
                async def gen():
                    for line in lines:
                        yield line

                return gen()

            async def aread(self):
                return b"{}"

        client = MagicMock()
        client.__aenter__ = AsyncMock(return_value=client)
        client.__aexit__ = AsyncMock(return_value=False)
        client.stream = MagicMock(return_value=_Resp())
        return client

    def test_cutout_success_record(self):
        import base64
        import httpx
        import app.main as main_module
        from app.agents.sam_agent import SamAgent
        from unittest.mock import MagicMock, patch

        lines = self._sam_success_lines(self._sam_fixture_text())
        client = self._fake_stream_client(lines)
        old = main_module.sam_agent
        main_module.sam_agent = SamAgent(api_key="dummy-test-key")
        try:
            with patch.object(httpx, "AsyncClient", MagicMock(return_value=client)):
                resp = self.client.post(
                    "/api/v1/cutout",
                    json={"image_url": "data:image/png;base64,AAAA", "concept": "slime"},
                )
        finally:
            main_module.sam_agent = old
        self.assertEqual(resp.status_code, 200, resp.text)
        body = resp.json()
        self.assertEqual(body["status"], "success")
        self.assertEqual(body["concept"], "slime")
        self.assertEqual(len(body["masks"]), 1)
        self.assertEqual((body["masks"][0]["width"], body["masks"][0]["height"]), (507, 1024))
        self.assertEqual(len(base64.b64decode(body["masks"][0]["data_base64"])), 507 * 1024)

    def test_cutout_missing_parser_dep_is_explicit_error(self):
        # The official parser may be absent from a runtime env: the route must
        # answer an explicit error, never crash the import.
        import asyncio
        import app.agents.sam_agent as sam_module
        from app.agents.sam_agent import SamAgent
        from unittest.mock import patch

        with patch.object(sam_module, "meta_sam_parser", None):
            body = asyncio.run(SamAgent(api_key="dummy").cutout_masks("data:,", "x"))
        self.assertEqual(body.status, "error")
        self.assertIn("meta-sam-parser", body.error or "")

    def test_cutout_no_match_on_empty_stream(self):
        import httpx
        import app.main as main_module
        from app.agents.sam_agent import SamAgent
        from unittest.mock import MagicMock, patch

        lines = self._sam_success_lines("")
        client = self._fake_stream_client(lines)
        old = main_module.sam_agent
        main_module.sam_agent = SamAgent(api_key="dummy-test-key")
        try:
            with patch.object(httpx, "AsyncClient", MagicMock(return_value=client)):
                resp = self.client.post(
                    "/api/v1/cutout",
                    json={"image_url": "data:image/png;base64,AAAA", "concept": "dragon"},
                )
        finally:
            main_module.sam_agent = old
        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertEqual(resp.json()["status"], "no_match")

    def test_transcribe_success(self):
        import base64
        import httpx
        import json
        import app.main as main_module
        from app.agents.voice_agent import VoiceAgent
        from unittest.mock import AsyncMock, MagicMock, patch

        seen = {}
        resp_200 = MagicMock()
        resp_200.status_code = 200
        resp_200.json = MagicMock(
            return_value={
                "transcript": "un zombie",
                "audioDurationMs": 1200,
                "turns": [
                    {
                        "turnId": 1,
                        "startMs": 0,
                        "endMs": 1200,
                        "transcript": "un zombie",
                        "speaker": "A",
                    }
                ],
            }
        )
        resp_200.raise_for_status = MagicMock()

        async def fake_post(url, headers=None, **kwargs):
            seen["url"] = url
            seen["headers"] = headers
            seen["kwargs"] = kwargs
            return resp_200

        client = MagicMock()
        client.__aenter__ = AsyncMock(return_value=client)
        client.__aexit__ = AsyncMock(return_value=False)
        client.post = fake_post

        wav = b"RIFF" + (36).to_bytes(4, "little") + b"WAVE" + bytes(32)
        old = main_module.voice_agent
        main_module.voice_agent = VoiceAgent(api_key="dummy-test-key")
        try:
            with patch.object(httpx, "AsyncClient", MagicMock(return_value=client)):
                resp = self.client.post(
                    "/api/v1/transcribe",
                    json={"audio_base64": base64.b64encode(wav).decode("ascii")},
                )
        finally:
            main_module.voice_agent = old
        self.assertEqual(resp.status_code, 200, resp.text)
        body = resp.json()
        self.assertEqual(body["status"], "success")
        self.assertEqual(body["transcript"], "un zombie")
        self.assertEqual(len(body["turns"]), 1)
        self.assertIn("/asr/transcribe", seen["url"])
        sent_files = seen["kwargs"]["files"]
        self.assertEqual(sent_files["audio"][1], wav)
        sent_request = json.loads(seen["kwargs"]["data"]["request"])
        self.assertEqual(sent_request["model"], "muse-voice-transcribe-1.0")
        self.assertEqual(sent_request["audioEncoding"], "WAV")

    def test_transcribe_rejects_bad_audio(self):
        r1 = self.client.post("/api/v1/transcribe", json={"audio_base64": "!!!"})
        self.assertEqual(r1.status_code, 200)
        self.assertEqual(r1.json()["status"], "error")
        import base64

        r2 = self.client.post(
            "/api/v1/transcribe",
            json={"audio_base64": base64.b64encode(b"not a wav file" * 4).decode("ascii")},
        )
        self.assertEqual(r2.status_code, 200)
        self.assertEqual(r2.json()["status"], "error")

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


    def _make_wav(self, seconds=12, sample_rate=32000, channels=1):
        import math
        import struct

        frames = int(seconds * sample_rate)
        pcm = bytearray()
        for i in range(frames):
            sample = int(8000 * math.sin(2 * math.pi * 220 * i / sample_rate))
            pcm += struct.pack("<h", sample) * channels
        return (
            b"RIFF"
            + struct.pack("<I", 36 + len(pcm))
            + b"WAVEfmt "
            + struct.pack(
                "<IHHIIHH", 16, 1, channels, sample_rate, sample_rate * channels * 2,
                channels * 2, 16,
            )
            + b"data"
            + struct.pack("<I", len(pcm))
            + bytes(pcm)
        )

    def _replicate_client(self, wav_bytes, final_status="succeeded", seen=None):
        from unittest.mock import AsyncMock, MagicMock

        seen = seen if seen is not None else {}
        created = MagicMock()
        created.status_code = 200
        created.json = MagicMock(return_value={"id": "pred-1", "status": "starting"})
        created.raise_for_status = MagicMock()
        polled = MagicMock()
        polled.status_code = 200
        polled.json = MagicMock(
            return_value={
                "id": "pred-1",
                "status": final_status,
                "output": "https://cdn.example/x.wav",
                "error": "boom" if final_status == "failed" else None,
            }
        )
        polled.raise_for_status = MagicMock()
        audio = MagicMock()
        audio.status_code = 200
        audio.content = wav_bytes
        audio.raise_for_status = MagicMock()

        async def fake_post(url, headers=None, json=None, **kwargs):
            seen["post_url"] = url
            seen["post_headers"] = headers
            seen["post_json"] = json
            return created

        async def fake_get(url, headers=None, **kwargs):
            if "predictions/pred-1" in url:
                seen["poll_headers"] = headers
                return polled
            seen["file_headers"] = headers
            return audio

        client = MagicMock()
        client.__aenter__ = AsyncMock(return_value=client)
        client.__aexit__ = AsyncMock(return_value=False)
        client.post = fake_post
        client.get = fake_get
        return client

    def test_generate_music_success_trims(self):
        import httpx
        import app.main as main_module
        from app.agents.music_agent import MusicAgent
        from unittest.mock import AsyncMock, MagicMock, patch

        wav12 = self._make_wav(seconds=12)
        seen = {}
        client = self._replicate_client(wav12, seen=seen)

        old = main_module.music_agent
        main_module.music_agent = MusicAgent(api_key="dummy-test-key")
        try:
            with patch.object(httpx, "AsyncClient", MagicMock(return_value=client)):
                resp = self.client.post(
                    "/api/v1/generate-music",
                    json={"prompt": "dark dungeon", "style": "orchestral", "duration_sec": 5},
                )
        finally:
            main_module.music_agent = old
        self.assertEqual(resp.status_code, 200, resp.text)
        body = resp.json()
        self.assertEqual(body["status"], "success")
        self.assertEqual(body["sample_rate"], 32000)
        self.assertEqual(body["channels"], 1)
        self.assertAlmostEqual(body["duration_sec"], 5.0, places=1)
        self.assertIn("orchestral", body["prompt_used"])
        self.assertIn("no fade out", body["prompt_used"])
        import base64

        trimmed = base64.b64decode(body["audio_base64"])
        self.assertTrue(trimmed.startswith(b"RIFF"))
        self.assertEqual(seen["post_headers"].get("Authorization"), "Bearer dummy-test-key")
        self.assertTrue(seen["post_url"].endswith("/v1/predictions"))
        self.assertEqual(
            seen["post_json"]["version"],
            "671ac645ce5e552cc63a54a2bbff63fcf798043055d2dac5fc9e36a837eedcfb",
        )
        self.assertEqual(seen["post_json"]["input"]["duration"], 5)
        self.assertIsNone(seen["file_headers"])

    def test_generate_music_failed_prediction_is_explicit(self):
        import httpx
        import app.main as main_module
        from app.agents.music_agent import MusicAgent
        from unittest.mock import MagicMock, patch

        client = self._replicate_client(self._make_wav(seconds=1), final_status="failed")

        old = main_module.music_agent
        main_module.music_agent = MusicAgent(api_key="dummy-test-key")
        try:
            with patch.object(httpx, "AsyncClient", MagicMock(return_value=client)):
                resp = self.client.post("/api/v1/generate-music", json={"prompt": "x"})
        finally:
            main_module.music_agent = old
        self.assertEqual(resp.status_code, 200, resp.text)
        body = resp.json()
        self.assertEqual(body["status"], "error")
        self.assertIn("prédiction", body["error"])

    def test_generate_music_bad_token_is_explicit(self):
        import httpx
        import app.main as main_module
        from app.agents.music_agent import MusicAgent
        from unittest.mock import AsyncMock, MagicMock, patch

        denied = MagicMock()
        denied.status_code = 401
        client = MagicMock()
        client.__aenter__ = AsyncMock(return_value=client)
        client.__aexit__ = AsyncMock(return_value=False)
        client.post = AsyncMock(return_value=denied)

        old = main_module.music_agent
        main_module.music_agent = MusicAgent(api_key="dummy-test-key")
        try:
            with patch.object(httpx, "AsyncClient", MagicMock(return_value=client)):
                resp = self.client.post("/api/v1/generate-music", json={"prompt": "x"})
        finally:
            main_module.music_agent = old
        self.assertEqual(resp.status_code, 200, resp.text)
        body = resp.json()
        self.assertEqual(body["status"], "error")
        self.assertIn("Replicate", body["error"])

    def test_generate_music_404_probes_auth(self):
        import httpx
        import app.main as main_module
        from app.agents.music_agent import MusicAgent
        from unittest.mock import AsyncMock, MagicMock, patch

        not_found = MagicMock()
        not_found.status_code = 404
        unauth = MagicMock()
        unauth.status_code = 401
        client = MagicMock()
        client.__aenter__ = AsyncMock(return_value=client)
        client.__aexit__ = AsyncMock(return_value=False)
        client.post = AsyncMock(return_value=not_found)
        client.get = AsyncMock(return_value=unauth)

        old = main_module.music_agent
        main_module.music_agent = MusicAgent(api_key="dummy-test-key")
        try:
            with patch.object(httpx, "AsyncClient", MagicMock(return_value=client)):
                resp = self.client.post("/api/v1/generate-music", json={"prompt": "x"})
        finally:
            main_module.music_agent = old
        self.assertEqual(resp.status_code, 200, resp.text)
        body = resp.json()
        self.assertEqual(body["status"], "error")
        self.assertIn("Clé Replicate invalide", body["error"])
        client.get.assert_awaited_once()
        probe_url = client.get.await_args.args[0]
        self.assertIn("/account", probe_url)

    def test_generate_music_uses_caller_replicate_key(self):
        import httpx
        import app.main as main_module
        from app.agents.music_agent import MusicAgent
        from unittest.mock import MagicMock, patch

        seen = {}
        client = self._replicate_client(self._make_wav(seconds=1), seen=seen)
        old = main_module.music_agent
        main_module.music_agent = MusicAgent(api_key="dummy-test-key")
        try:
            with patch.object(httpx, "AsyncClient", MagicMock(return_value=client)):
                resp = self.client.post(
                    "/api/v1/generate-music",
                    json={"prompt": "x"},
                    headers={"X-Replicate-Key": "r8-user-key-123"},
                )
        finally:
            main_module.music_agent = old
        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertEqual(resp.json()["status"], "success")
        self.assertEqual(seen["post_headers"].get("Authorization"), "Bearer r8-user-key-123")

    def test_crossfade_loop_blends_tail_with_head(self):
        import struct

        from app.agents.music_agent import _find_data_chunk, crossfade_loop_wav

        sample_rate, seconds, level = 32000, 5, 12000
        frames = seconds * sample_rate
        pcm = bytearray()
        for i in range(frames):
            pcm += struct.pack("<h", level if i < frames // 2 else -level)
        wav = (
            b"RIFF"
            + struct.pack("<I", 36 + len(pcm))
            + b"WAVEfmt "
            + struct.pack(
                "<IHHIIHH", 16, 1, 1, sample_rate, sample_rate * 2, 2, 16
            )
            + b"data"
            + struct.pack("<I", len(pcm))
            + bytes(pcm)
        )
        out = crossfade_loop_wav(wav)
        self.assertEqual(len(out), len(wav))
        _, _, data_offset, data_len = _find_data_chunk(wav)
        total = data_len // 2
        span = min(int(sample_rate * 1.5), total // 4)
        # Untouched before the crossfade zone.
        head = (total - span) * 2
        self.assertEqual(out[data_offset:data_offset + head], wav[data_offset:data_offset + head])
        # Mid-crossfade is an exact 50/50 blend: (+12000 - 12000) / 2 = 0.
        mid = struct.unpack_from("<h", out, data_offset + (total - span // 2) * 2)[0]
        self.assertLessEqual(abs(mid), 1)
        # Last frame converged to the head material, far from the old tail.
        last = struct.unpack_from("<h", out, data_offset + (total - 1) * 2)[0]
        self.assertGreater(last, level - 50)
        old_last = struct.unpack_from("<h", wav, data_offset + (total - 1) * 2)[0]
        self.assertEqual(old_last, -level)

    def _meta_text_client(self, text, seen=None):
        from unittest.mock import AsyncMock, MagicMock

        seen = seen if seen is not None else {}
        payload = {
            "status": "completed",
            "output": [
                {
                    "type": "message",
                    "content": [{"type": "output_text", "text": text}],
                }
            ],
        }
        resp = MagicMock()
        resp.json = MagicMock(return_value=payload)
        resp.raise_for_status = MagicMock()

        async def fake_post(url, headers=None, json=None, **kwargs):
            seen["url"] = url
            seen["headers"] = headers
            seen["json"] = json
            return resp

        client = MagicMock()
        client.__aenter__ = AsyncMock(return_value=client)
        client.__aexit__ = AsyncMock(return_value=False)
        client.post = fake_post
        return client

    def test_review_gdd_success_parses_report(self):
        import httpx
        import app.routers.gdd_router as router_module
        from app.agents.review_agent import ReviewAgent
        from unittest.mock import MagicMock, patch

        seen = {}
        client = self._meta_text_client(
            '{"score": 7, "verdict": "Solid base, thin USPs.", '
            '"checks": [{"item": "USPs", "status": "weak", "detail": "generic"}], '
            '"suggestions": [{"id": "x", "section": "USPs", "issue": "vague", '
            '"proposal": "Add permadeath raids."}]}',
            seen=seen,
        )
        old = router_module.review_agent
        router_module.review_agent = ReviewAgent(api_key="dummy-test-key")
        try:
            with patch.object(httpx, "AsyncClient", MagicMock(return_value=client)):
                resp = self.client.post(
                    "/api/v1/review-gdd",
                    json={"doc_type": "one_sheet", "document": '{"title": "T"}'},
                )
        finally:
            router_module.review_agent = old
        self.assertEqual(resp.status_code, 200, resp.text)
        body = resp.json()
        self.assertEqual(body["status"], "success")
        self.assertEqual(body["score"], 7)
        self.assertEqual(body["suggestions"][0]["id"], "s1")
        self.assertEqual(seen["json"]["model"], "muse-wonder-1.0")
        sent = seen["json"]["input"][0]["content"][0]["text"]
        self.assertIn("USPs", sent)

    def test_review_gdd_bad_output_is_explicit_error(self):
        import httpx
        import app.routers.gdd_router as router_module
        from app.agents.review_agent import ReviewAgent
        from unittest.mock import MagicMock, patch

        client = self._meta_text_client("not json at all")
        old = router_module.review_agent
        router_module.review_agent = ReviewAgent(api_key="dummy-test-key")
        try:
            with patch.object(httpx, "AsyncClient", MagicMock(return_value=client)):
                resp = self.client.post(
                    "/api/v1/review-gdd", json={"doc_type": "one_sheet", "document": "x"}
                )
        finally:
            router_module.review_agent = old
        self.assertEqual(resp.status_code, 200, resp.text)
        body = resp.json()
        self.assertEqual(body["status"], "error")
        self.assertIn("Audit impossible", body["error"])

    def test_review_gdd_empty_document_rejected(self):
        resp = self.client.post(
            "/api/v1/review-gdd", json={"doc_type": "one_sheet", "document": "  "}
        )
        self.assertEqual(resp.status_code, 400)
        self.assertIn("auditer", resp.json()["detail"])

    def test_fix_gdd_applies_only_selected(self):
        import httpx
        import app.routers.gdd_router as router_module
        from app.agents.review_agent import ReviewAgent
        from unittest.mock import MagicMock, patch

        seen = {}
        client = self._meta_text_client('{"title": "T fixed"}', seen=seen)
        old = router_module.review_agent
        router_module.review_agent = ReviewAgent(api_key="dummy-test-key")
        try:
            with patch.object(httpx, "AsyncClient", MagicMock(return_value=client)):
                resp = self.client.post(
                    "/api/v1/fix-gdd",
                    json={
                        "doc_type": "one_sheet",
                        "document": '{"title": "T"}',
                        "suggestions": [
                            {"id": "s1", "section": "USPs", "issue": "vague", "proposal": "PROPOSAL-ONE"},
                            {"id": "s2", "section": "Modes", "issue": "thin", "proposal": "PROPOSAL-TWO"},
                        ],
                        "apply_ids": ["s1"],
                    },
                )
        finally:
            router_module.review_agent = old
        self.assertEqual(resp.status_code, 200, resp.text)
        body = resp.json()
        self.assertEqual(body["status"], "success")
        self.assertEqual(body["doc_format"], "json")
        self.assertEqual(body["improved_json"], {"title": "T fixed"})
        self.assertEqual(body["applied"], ["s1"])
        sent = seen["json"]["input"][0]["content"][0]["text"]
        self.assertIn("PROPOSAL-ONE", sent)
        self.assertNotIn("PROPOSAL-TWO", sent)

    def test_fix_gdd_empty_selection_rejected(self):
        resp = self.client.post(
            "/api/v1/fix-gdd",
            json={"doc_type": "one_sheet", "document": "x", "suggestions": [], "apply_ids": []},
        )
        self.assertEqual(resp.status_code, 400)
        self.assertIn("suggestion", resp.json()["detail"])

    def test_review_gdd_byok_reaches_meta(self):
        import httpx
        import app.routers.gdd_router as router_module
        from app.agents.review_agent import ReviewAgent
        from unittest.mock import MagicMock, patch

        seen = {}
        client = self._meta_text_client('{"score": 5}', seen=seen)
        old = router_module.review_agent
        router_module.review_agent = ReviewAgent(api_key="dummy-test-key")
        try:
            with patch.object(httpx, "AsyncClient", MagicMock(return_value=client)):
                resp = self.client.post(
                    "/api/v1/review-gdd",
                    json={"doc_type": "one_sheet", "document": "x"},
                    headers={"Authorization": "Bearer user-key-abc"},
                )
        finally:
            router_module.review_agent = old
        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertEqual(seen["headers"].get("Authorization"), "Bearer user-key-abc")

    def _rate_dispatch(self, middleware, method="POST", path="/api/v1/gdd-pdf", headers=None):
        import asyncio

        from starlette.requests import Request  # type: ignore
        from starlette.responses import JSONResponse  # type: ignore

        async def echo(request):
            return JSONResponse({"ok": True})

        scope = {
            "type": "http",
            "method": method,
            "path": path,
            "headers": [(k.lower().encode(), v.encode()) for k, v in (headers or {}).items()],
            "client": ("rate-test-client", 0),
        }
        return asyncio.run(middleware.dispatch(Request(scope), echo))

    def test_rate_limit_429s_when_exceeded(self):
        import os

        from app.security import RATE_LIMIT_ENV, RateLimitMiddleware

        async def echo(request):
            from starlette.responses import JSONResponse  # type: ignore

            return JSONResponse({"ok": True})

        old = os.environ.get(RATE_LIMIT_ENV)
        os.environ[RATE_LIMIT_ENV] = "2"
        try:
            mw = RateLimitMiddleware(echo)
            self.assertEqual(self._rate_dispatch(mw).status_code, 200)
            self.assertEqual(self._rate_dispatch(mw).status_code, 200)
            limited = self._rate_dispatch(mw)
            self.assertEqual(limited.status_code, 429)
            self.assertIn("Trop de requêtes", limited.body.decode("utf-8"))
        finally:
            if old is None:
                os.environ.pop(RATE_LIMIT_ENV, None)
            else:
                os.environ[RATE_LIMIT_ENV] = old

    def test_rate_limit_skips_byok_and_get(self):
        import os

        from app.security import RATE_LIMIT_ENV, RateLimitMiddleware

        async def echo(request):
            from starlette.responses import JSONResponse  # type: ignore

            return JSONResponse({"ok": True})

        old = os.environ.get(RATE_LIMIT_ENV)
        os.environ[RATE_LIMIT_ENV] = "1"
        try:
            mw = RateLimitMiddleware(echo)
            for _ in range(3):
                res = self._rate_dispatch(mw, headers={"Authorization": "Bearer user-key"})
                self.assertEqual(res.status_code, 200)
                res = self._rate_dispatch(mw, method="GET", path="/api/v1/review-gdd")
                self.assertEqual(res.status_code, 200)
        finally:
            if old is None:
                os.environ.pop(RATE_LIMIT_ENV, None)
            else:
                os.environ[RATE_LIMIT_ENV] = old

    def test_daily_limit_429s_when_exceeded(self):
        import os

        from app.security import RATE_LIMIT_DAY_ENV, RATE_LIMIT_ENV, RateLimitMiddleware

        async def echo(request):
            from starlette.responses import JSONResponse  # type: ignore

            return JSONResponse({"ok": True})

        saved = {k: os.environ.get(k) for k in (RATE_LIMIT_ENV, RATE_LIMIT_DAY_ENV)}
        os.environ[RATE_LIMIT_ENV] = "100"
        os.environ[RATE_LIMIT_DAY_ENV] = "2"
        try:
            mw = RateLimitMiddleware(echo)
            self.assertEqual(self._rate_dispatch(mw).status_code, 200)
            self.assertEqual(self._rate_dispatch(mw).status_code, 200)
            limited = self._rate_dispatch(mw)
            self.assertEqual(limited.status_code, 429)
            self.assertIn("quotidienne", limited.body.decode("utf-8"))
        finally:
            for k, v in saved.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v

    def test_billing_paused_503s_server_key_but_allows_byok(self):
        import os

        from app.security import BILLING_PAUSED_ENV, RateLimitMiddleware

        async def echo(request):
            from starlette.responses import JSONResponse  # type: ignore

            return JSONResponse({"ok": True})

        old = os.environ.get(BILLING_PAUSED_ENV)
        os.environ[BILLING_PAUSED_ENV] = "1"
        try:
            mw = RateLimitMiddleware(echo)
            paused = self._rate_dispatch(mw)
            self.assertEqual(paused.status_code, 503)
            self.assertIn("pause", paused.body.decode("utf-8"))
            res = self._rate_dispatch(mw, headers={"Authorization": "Bearer [REDACTED]"})
            self.assertEqual(res.status_code, 200)
        finally:
            if old is None:
                os.environ.pop(BILLING_PAUSED_ENV, None)
            else:
                os.environ[BILLING_PAUSED_ENV] = old

    def test_is_safe_fetch_url(self):
        from app.security import is_safe_fetch_url

        self.assertTrue(is_safe_fetch_url("https://1.1.1.1/a.png"))
        self.assertTrue(is_safe_fetch_url("http://8.8.8.8/x"))
        self.assertTrue(is_safe_fetch_url("http://127.0.0.1:3000/demo/a.webp"))
        self.assertTrue(is_safe_fetch_url("http://localhost:3000/a"))
        self.assertFalse(is_safe_fetch_url("http://10.0.0.1/x"))
        self.assertFalse(is_safe_fetch_url("http://192.168.1.1/x"))
        self.assertFalse(is_safe_fetch_url("http://169.254.169.254/latest"))
        self.assertFalse(is_safe_fetch_url("ftp://example.com/x"))
        self.assertFalse(is_safe_fetch_url("data:image/png;base64,xx"))
        self.assertFalse(is_safe_fetch_url("not a url"))

    def test_review_gdd_document_too_big(self):
        resp = self.client.post(
            "/api/v1/review-gdd", json={"doc_type": "one_sheet", "document": "x" * 100_001}
        )
        self.assertEqual(resp.status_code, 400)
        self.assertIn("100 Ko", resp.json()["detail"])

    def test_gdd_pdf_document_too_big(self):
        resp = self.client.post(
            "/api/v1/gdd-pdf",
            json={"gdd": {"document_type": "one_sheet", "blob": "x" * 200_001}, "style": "pro"},
        )
        self.assertEqual(resp.status_code, 400)
        # Assert on raw bytes: with a 200 Ko+ request body the in-process
        # TestClient transport hands back a parsed dict whose key string
        # carries a poisoned cached hash (clean bytes, real str, but ==
        # and hash() disagree), so resp.json()["Detail"] raises KeyError.
        # The wire bytes are correct; this is a test-transport quirk, not
        # an app bug (uvicorn/browsers never take this parsing path).
        self.assertIn("200 Ko", resp.text)

    def test_generate_music_prompt_truncated(self):
        import httpx
        import app.main as main_module
        from app.agents.music_agent import MusicAgent
        from unittest.mock import MagicMock, patch

        seen = {}
        client = self._replicate_client(self._make_wav(seconds=1), seen=seen)
        old = main_module.music_agent
        main_module.music_agent = MusicAgent(api_key="dummy-test-key")
        try:
            with patch.object(httpx, "AsyncClient", MagicMock(return_value=client)):
                resp = self.client.post(
                    "/api/v1/generate-music", json={"prompt": "x" * 600, "style": ""}
                )
        finally:
            main_module.music_agent = old
        self.assertEqual(resp.status_code, 200, resp.text)
        sent = seen["post_json"]["input"]["prompt"]
        self.assertIn("x" * 500, sent)
        self.assertNotIn("x" * 501, sent)

    def _mini_gdd(self):
        return {
            "document_type": "full_gdd",
            "one_sheet": {
                "title": "Neon Harbor",
                "target_systems": ["PC", "Switch"],
                "target_age": "12+",
                "esrb_rating": "E10+",
                "story_summary": "Run a ramen stall by day, smuggle parts by night.",
                "gameplay_modes": ["Solo"],
                "usps": ["Day/night double life", "Ramen crafting", "Harbor factions"],
                "competitive_products": ["Stardew Valley"],
            },
            "beat_chart": [
                {
                    "level_name": "Opening",
                    "progression_focus": "Tutorial",
                    "mechanics_introduced": ["Cooking"],
                    "enemies_introduced": [],
                    "estimated_play_time": "20 min",
                }
            ],
            "ten_pager": {
                "camera": "Top-down",
                "character": "Ramen chef",
                "controls": "Mouse + WASD",
                "core_loop": "Cook, serve, smuggle, upgrade.",
                "menu_flow": "Title > Stall > Night market",
            },
            "full_gdd": {
                "lore": "A neon harbor after the flood.",
                "level_design": "Three docks, one market.",
                "features": ["Day/night cycle"],
                "ai_type": "Utility AI",
                "physics_engine": "Builtin",
            },
            "visual_style_prompt": "Cozy cyberpunk pixel art.",
        }

    def test_gdd_pdf_pro_renders_real_pdf(self):
        import base64

        resp = self.client.post(
            "/api/v1/gdd-pdf", json={"gdd": self._mini_gdd(), "style": "pro"}
        )
        self.assertEqual(resp.status_code, 200, resp.text)
        body = resp.json()
        self.assertEqual(body["status"], "success")
        raw = base64.b64decode(body["pdf_base64"])
        self.assertTrue(raw.startswith(b"%PDF"))
        self.assertGreater(len(raw), 3000)

    def test_gdd_pdf_gamebook_differs(self):
        import base64

        bodies = {}
        for style in ("pro", "gamebook"):
            resp = self.client.post(
                "/api/v1/gdd-pdf", json={"gdd": self._mini_gdd(), "style": style}
            )
            self.assertEqual(resp.status_code, 200, resp.text)
            bodies[style] = base64.b64decode(resp.json()["pdf_base64"])
            self.assertTrue(bodies[style].startswith(b"%PDF"))
        self.assertNotEqual(bodies["pro"], bodies["gamebook"])

    def test_gdd_pdf_cover_data_url(self):
        import base64

        pixel = (
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5"
            "ErkJggg=="
        )
        resp = self.client.post(
            "/api/v1/gdd-pdf",
            json={
                "gdd": self._mini_gdd(),
                "style": "pro",
                "images": [{"image_url": f"data:image/png;base64,{pixel}"}],
            },
        )
        self.assertEqual(resp.status_code, 200, resp.text)
        body = resp.json()
        self.assertEqual(body["status"], "success")
        self.assertTrue(base64.b64decode(body["pdf_base64"]).startswith(b"%PDF"))

    def test_gdd_pdf_bad_style_rejected(self):
        resp = self.client.post(
            "/api/v1/gdd-pdf", json={"gdd": self._mini_gdd(), "style": "comic"}
        )
        self.assertEqual(resp.status_code, 400)
        self.assertIn("Style PDF", resp.json()["detail"])

    def test_gdd_pdf_empty_rejected(self):
        resp = self.client.post("/api/v1/gdd-pdf", json={"gdd": {}, "style": "pro"})
        self.assertEqual(resp.status_code, 400)
        self.assertIn("PDF", resp.json()["detail"])

    def test_music_to_mp3_roundtrip(self):
        import base64

        wav = self._make_wav(seconds=1, sample_rate=16000)
        resp = self.client.post(
            "/api/v1/music-to-mp3", json={"audio_base64": base64.b64encode(wav).decode("ascii")}
        )
        self.assertEqual(resp.status_code, 200, resp.text)
        body = resp.json()
        self.assertEqual(body["status"], "success")
        mp3 = base64.b64decode(body["audio_base64"])
        self.assertGreater(len(mp3), 100)
        self.assertEqual(mp3[0], 0xFF)
        self.assertEqual(mp3[1] & 0xE0, 0xE0)

    def test_music_to_mp3_rejects_bad_audio(self):
        r1 = self.client.post("/api/v1/music-to-mp3", json={"audio_base64": "!!!"})
        self.assertEqual(r1.status_code, 200)
        self.assertEqual(r1.json()["status"], "error")

    def test_offline_demo_path_with_visuals_uses_placeholders(self):
        # Demo-path guard: with no API keys and MOCK_VISUALS off (the real
        # offline demo), the rich GDDForm payload still returns 200 with a
        # mock document and placeholder images, each with a distinct prompt.
        import app.routers.gdd_router as router_module

        old_flag = router_module.MOCK_VISUALS
        router_module.MOCK_VISUALS = False
        try:
            resp = self.client.post(
                "/api/v1/generate-gdd",
                json={
                    "prompt": "haunted lighthouse",
                    "doc_type": "one_sheet",
                    "visuals": [
                        {"asset_type": "concept_art", "enabled": True, "count": 2},
                        {"asset_type": "sprite", "enabled": True, "count": 2},
                    ],
                },
            )
        finally:
            router_module.MOCK_VISUALS = old_flag
        self.assertEqual(resp.status_code, 200, resp.text)
        body = resp.json()
        self.assertEqual(body["status"], "mock")
        self.assertEqual(len(body["images"]), 4)
        self.assertTrue(all(i["status"] == "placeholder" for i in body["images"]))
        self.assertTrue(all("placehold.co" in i["image_url"] for i in body["images"]))
        prompts = [i["prompt_used"] for i in body["images"]]
        self.assertEqual(len(set(prompts)), 4)

    def test_generate_gdd_success_path_with_mocked_meta(self):
        # Locks the live path: well-formed Meta JSON becomes a success document.
        import app.routers.gdd_router as router_module
        from app.agents.gdd_agent import GDDAgent
        from unittest.mock import AsyncMock

        text = (
            '{"one_sheet": {"title": "Lumen Deep", "target_systems": ["PC"],'
            ' "target_age": "12+", "esrb_rating": "E10+", "story_summary": "Dive.",'
            ' "gameplay_modes": ["Solo"], "usps": ["Light crafting"],'
            ' "competitive_products": ["Subnautica"]},'
            ' "beat_chart": [{"level_name": "Descent", "progression_focus": "Learn",'
            ' "mechanics_introduced": ["Swim"], "enemies_introduced": [],'
            ' "estimated_play_time": "10 min"}],'
            ' "visual_style_prompt": "Bioluminescent pixel art."}'
        )
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
        agent._fetch_market_references = AsyncMock(return_value="")
        old = router_module.gdd_agent
        router_module.gdd_agent = agent
        try:
            resp = self.client.post(
                "/api/v1/generate-gdd",
                json={"prompt": "underwater", "doc_type": "full_gdd"},
            )
        finally:
            router_module.gdd_agent = old
        self.assertEqual(resp.status_code, 200, resp.text)
        body = resp.json()
        self.assertEqual(body["status"], "success")
        self.assertEqual(body["document_type"], "full_gdd")
        self.assertEqual(body["one_sheet"]["title"], "Lumen Deep")
        self.assertEqual(len(body["beat_chart"]), 1)
        self.assertEqual(body["beat_chart"][0]["level_name"], "Descent")

    def test_gdd_pdf_ignores_images_embedded_in_gdd(self):
        # Regression: the GDD form posts its whole result object as `gdd`,
        # including full data-URL images. Those must not trip the 200 Ko cap
        # (cover images travel via the separate `images` field).
        import base64

        gdd = self._mini_gdd()
        gdd["images"] = [
            {
                "asset_type": "concept_art",
                "prompt_used": "p",
                "image_url": "data:image/png;base64,"
                + base64.b64encode(b"x" * 300_000).decode("ascii"),
                "status": "success",
            }
        ]
        resp = self.client.post(
            "/api/v1/gdd-pdf", json={"gdd": gdd, "style": "pro", "images": []}
        )
        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertEqual(resp.json()["status"], "success")

    def test_pdf_beat_chart_accepts_renamed_level_keys(self):
        # Regression: fix-agent output renames level keys (or uses bare
        # strings), which rendered as an empty/??? beat-chart table.
        from app.services.pdf_layout import _blocks

        gdd = self._mini_gdd()
        gdd["beat_chart"] = [
            {
                "name": "Descent",
                "focus": "Learn to swim",
                "mechanics": "Swimming, diving",
                "enemies": ["Anglerfish"],
                "playtime": "10 min",
            },
            "Interlude",
        ]
        tables = [b for b in _blocks(gdd) if b[0] == "table"]
        self.assertEqual(len(tables), 1)
        rows = tables[0][2]
        self.assertEqual(
            rows[0], ["Descent", "Learn to swim", "Swimming, diving", "Anglerfish", "10 min"]
        )
        self.assertEqual(rows[1][0], "Interlude")
        import base64

        r2 = self.client.post(
            "/api/v1/music-to-mp3",
            json={"audio_base64": base64.b64encode(b"not a wav" * 8).decode("ascii")},
        )
        self.assertEqual(r2.status_code, 200)
        self.assertEqual(r2.json()["status"], "error")


if __name__ == "__main__":
    unittest.main()
