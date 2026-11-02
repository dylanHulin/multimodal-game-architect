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
        import base64

        r2 = self.client.post(
            "/api/v1/music-to-mp3",
            json={"audio_base64": base64.b64encode(b"not a wav" * 8).decode("ascii")},
        )
        self.assertEqual(r2.status_code, 200)
        self.assertEqual(r2.json()["status"], "error")


if __name__ == "__main__":
    unittest.main()
