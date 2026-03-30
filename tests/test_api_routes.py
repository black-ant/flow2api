import asyncio
import base64
import json
from types import SimpleNamespace

from src.api import admin as admin_module
from src.api import routes
from src.core.auth import AuthManager, verify_api_key_flexible


def build_openai_completion(content: str) -> str:
    return json.dumps(
        {
            "id": "chatcmpl-test",
            "object": "chat.completion",
            "created": 1,
            "model": "flow2api",
            "choices": [
                {
                    "index": 0,
                    "message": {
                        "role": "assistant",
                        "content": content,
                    },
                    "finish_reason": "stop",
                }
            ],
        }
    )


def test_openai_route_resolves_alias_and_returns_non_stream_result(client, fake_handler):
    fake_handler.non_stream_chunks = [build_openai_completion("![Generated Image](https://example.com/out.png)")]

    response = client.post(
        "/v1/chat/completions",
        json={
            "model": "gemini-3.0-pro-image",
            "messages": [{"role": "user", "content": "draw a sunset"}],
            "generationConfig": {
                "imageConfig": {
                    "aspectRatio": "16:9",
                    "imageSize": "2K",
                }
            },
        },
    )

    assert response.status_code == 200
    assert fake_handler.calls[0]["model"] == "gemini-3.0-pro-image-landscape-2k"
    assert response.json()["choices"][0]["message"]["content"].startswith("![Generated Image]")


def test_openai_route_accepts_data_url_reference_image(client, fake_handler):
    fake_handler.non_stream_chunks = [build_openai_completion("![Generated Image](https://example.com/out.png)")]
    reference_image = base64.b64encode(b"\x89PNG\r\n\x1a\nref").decode()

    response = client.post(
        "/v1/chat/completions",
        json={
            "model": "gemini-3.1-flash-image",
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "draw a cat"},
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/png;base64,{reference_image}"
                            },
                        },
                    ],
                }
            ],
        },
    )

    assert response.status_code == 200
    assert len(fake_handler.calls[0]["images"]) == 1
    assert fake_handler.calls[0]["images"][0].startswith(b"\x89PNG")


def test_openai_route_returns_handler_error_status(client, fake_handler):
    fake_handler.non_stream_chunks = [
        json.dumps(
            {
                "error": {
                    "message": "没有可用的Token进行图片生成",
                    "status_code": 503,
                }
            }
        )
    ]

    response = client.post(
        "/v1/chat/completions",
        json={
            "model": "gemini-3.0-pro-image",
            "messages": [{"role": "user", "content": "draw a tree"}],
        },
    )

    assert response.status_code == 503
    assert response.json()["error"]["message"] == "没有可用的Token进行图片生成"


def test_flexible_auth_accepts_x_goog_api_key(monkeypatch):
    monkeypatch.setattr(AuthManager, "verify_api_key", staticmethod(lambda api_key: api_key == "secret"))

    assert asyncio.run(
        verify_api_key_flexible(
            credentials=None,
            x_goog_api_key="secret",
            key=None,
        )
    ) == "secret"


def test_admin_remote_browser_helper_uses_asyncsession(monkeypatch):
    calls = []

    class FakeResponse:
        status_code = 200
        text = '{"success": true, "token": "abc"}'

        def json(self):
            return {"success": True, "token": "abc"}

    class FakeSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def request(self, method, url, **kwargs):
            calls.append({
                "method": method,
                "url": url,
                "kwargs": kwargs,
            })
            return FakeResponse()

    monkeypatch.setattr(admin_module, "AsyncSession", FakeSession)

    status_code, payload, response_text = asyncio.run(
        admin_module._sync_json_http_request(
            method="POST",
            url="https://example.com/api/v1/custom-score",
            headers={"Authorization": "Bearer token"},
            payload={"website_url": "https://example.com"},
            timeout=15,
        )
    )

    assert status_code == 200
    assert payload == {"success": True, "token": "abc"}
    assert response_text == '{"success": true, "token": "abc"}'
    assert calls == [
        {
            "method": "POST",
            "url": "https://example.com/api/v1/custom-score",
            "kwargs": {
                "headers": {
                    "Authorization": "Bearer token",
                    "Accept": "application/json",
                    "Content-Type": "application/json; charset=utf-8",
                },
                "timeout": 15,
                "impersonate": "chrome120",
                "json": {"website_url": "https://example.com"},
            },
        }
    ]


def test_ant_browser_diagnostics_summary_masks_configuration_state():
    captcha_config = SimpleNamespace(
        captcha_method="ant_browser",
        ant_browser_base_url="http://0.0.0.0:5030",
        ant_browser_launch_code="launch-code",
        ant_browser_api_key="secret",
        ant_browser_api_header="X-Ant-Api-Key",
        browser_proxy_enabled=True,
        browser_proxy_url="http://127.0.0.1:7890",
    )

    payload = admin_module._build_ant_browser_summary_payload(captcha_config)

    assert payload["success"] is True
    assert payload["summary"]["is_ant_browser_mode"] is True
    assert payload["summary"]["base_url"] == "http://127.0.0.1:5030"
    assert payload["summary"]["launch_code_configured"] is True
    assert payload["summary"]["api_key_configured"] is True
    assert payload["summary"]["browser_proxy_enabled"] is True
    assert payload["summary"]["ready_for_diagnose"] is True


def test_generation_playground_config_payload_contains_defaults():
    admin_config = SimpleNamespace(api_key="flow2api-key")

    payload = admin_module._build_generation_playground_config_payload(admin_config)

    assert payload["success"] is True
    config = payload["config"]
    assert config["api_key"] == "flow2api-key"
    assert config["default_openai_image_model"]
    assert config["default_openai_video_model"]
    assert any(item["type"] == "image" for item in config["openai_models"])
    assert any(item["type"] == "video" for item in config["openai_models"])
    assert any(item["id"] == "gemini-3.1-flash-image" for item in config["gemini_models"])


def test_ant_browser_diagnostics_run_returns_config_error_when_mode_mismatch(monkeypatch):
    class FakeDb:
        async def get_captcha_config(self):
            return SimpleNamespace(
                captcha_method="browser",
                ant_browser_base_url="http://127.0.0.1:5030",
                ant_browser_launch_code="launch-code",
                ant_browser_api_key="",
                ant_browser_api_header="X-Ant-Api-Key",
                browser_proxy_enabled=False,
                browser_proxy_url="",
            )

    monkeypatch.setattr(admin_module, "db", FakeDb())

    result = asyncio.run(
        admin_module._run_ant_browser_diagnostics(
            admin_module.AntBrowserDiagnosticsRunRequest()
        )
    )

    assert result["success"] is False
    assert result["stage"] == "config_check"
    assert result["summary"]["captcha_method"] == "browser"
    assert result["steps"][0]["status"] == "error"
    assert "ant_browser" in result["message"]


def test_ant_browser_diagnostics_run_emits_stream_step_callbacks(monkeypatch):
    emitted_steps = []

    class FakeDb:
        async def get_captcha_config(self):
            return SimpleNamespace(
                captcha_method="browser",
                ant_browser_base_url="http://127.0.0.1:5030",
                ant_browser_launch_code="launch-code",
                ant_browser_api_key="",
                ant_browser_api_header="X-Ant-Api-Key",
                browser_proxy_enabled=False,
                browser_proxy_url="",
            )

    async def emit_step(step):
        emitted_steps.append(step)

    monkeypatch.setattr(admin_module, "db", FakeDb())

    result = asyncio.run(
        admin_module._run_ant_browser_diagnostics(
            admin_module.AntBrowserDiagnosticsRunRequest(),
            emit_step=emit_step,
        )
    )

    assert result["success"] is False
    assert emitted_steps
    assert emitted_steps[0]["key"] == "config_check"
    assert emitted_steps[0]["status"] == "error"
