import asyncio
from types import SimpleNamespace

import pytest

from src.services import flow_client as flow_client_module
from src.services.flow_client import FlowClient


def test_create_project_retries_timeout_then_succeeds(monkeypatch):
    client = FlowClient(proxy_manager=None)
    attempts = []
    sleep_calls = []

    async def fake_make_request(**kwargs):
        attempts.append(kwargs["timeout"])
        if len(attempts) < 3:
            raise Exception("Flow API request failed: curl: (28) Connection timed out after 5013 milliseconds")
        return {
            "result": {
                "data": {
                    "json": {
                        "result": {
                            "projectId": "project-123",
                        }
                    }
                }
            }
        }

    async def fake_sleep(seconds):
        sleep_calls.append(seconds)

    monkeypatch.setattr(client, "_make_request", fake_make_request)
    monkeypatch.setattr(flow_client_module.asyncio, "sleep", fake_sleep)

    project_id = asyncio.run(client.create_project("st-token", "Retry Test"))

    assert project_id == "project-123"
    assert attempts == [15, 15, 15]
    assert sleep_calls == [1, 1]


def test_create_project_invalid_response_fails_fast(monkeypatch):
    client = FlowClient(proxy_manager=None)
    attempts = []

    async def fake_make_request(**kwargs):
        attempts.append(kwargs["timeout"])
        return {"result": {"data": {"json": {"result": {}}}}}

    monkeypatch.setattr(client, "_make_request", fake_make_request)

    with pytest.raises(Exception, match="missing projectId"):
        asyncio.run(client.create_project("st-token", "Invalid Response"))

    assert attempts == [15]


def test_get_recaptcha_token_falls_back_to_yescaptcha_when_ant_browser_returns_none(monkeypatch):
    client = FlowClient(proxy_manager=None)
    original_method = flow_client_module.config.captcha_method
    original_yes_key = flow_client_module.config.yescaptcha_api_key

    class FakeBrowserCaptchaService:
        @classmethod
        async def get_instance(cls, db):
            return cls()

        async def get_token(self, project_id, action, token_id=None):
            return None, None

        async def get_fingerprint(self, browser_ref):
            return None

    async def fake_api_token(method, project_id, action="IMAGE_GENERATION"):
        assert method == "yescaptcha"
        return "api-token-123"

    flow_client_module.config.set_captcha_method("ant_browser")
    flow_client_module.config.set_yescaptcha_api_key("yes-key")
    monkeypatch.setattr(flow_client_module, "BrowserCaptchaService", None, raising=False)
    monkeypatch.setattr(client, "_get_api_captcha_token", fake_api_token)

    import src.services.browser_captcha as browser_captcha_module
    monkeypatch.setattr(browser_captcha_module, "BrowserCaptchaService", FakeBrowserCaptchaService)

    async def run_case():
        token, browser_id = await client._get_recaptcha_token("project-1", action="IMAGE_GENERATION", token_id=1)
        return token, browser_id, client.get_captcha_resolution()

    token, browser_id, resolution = asyncio.run(run_case())
    assert token == "api-token-123"
    assert browser_id is None
    assert resolution["requested_method"] == "ant_browser"
    assert resolution["used_method"] == "yescaptcha"
    assert resolution["fallback_used"] is True
    assert resolution["attempted_methods"] == ["ant_browser", "yescaptcha"]

    flow_client_module.config.set_captcha_method(original_method)
    flow_client_module.config.set_yescaptcha_api_key(original_yes_key)


def test_get_recaptcha_token_records_primary_api_method_success(monkeypatch):
    client = FlowClient(proxy_manager=None)
    original_method = flow_client_module.config.captcha_method
    original_yes_key = flow_client_module.config.yescaptcha_api_key

    async def fake_api_token(method, project_id, action="IMAGE_GENERATION"):
        assert method == "yescaptcha"
        return "api-token-primary"

    flow_client_module.config.set_captcha_method("yescaptcha")
    flow_client_module.config.set_yescaptcha_api_key("yes-key")
    monkeypatch.setattr(client, "_get_api_captcha_token", fake_api_token)

    async def run_case():
        token, browser_id = await client._get_recaptcha_token("project-2", action="IMAGE_GENERATION", token_id=2)
        return token, browser_id, client.get_captcha_resolution()

    token, browser_id, resolution = asyncio.run(run_case())
    assert token == "api-token-primary"
    assert browser_id is None
    assert resolution["requested_method"] == "yescaptcha"
    assert resolution["used_method"] == "yescaptcha"
    assert resolution["fallback_used"] is False
    assert resolution["attempted_methods"] == ["yescaptcha"]

    flow_client_module.config.set_captcha_method(original_method)
    flow_client_module.config.set_yescaptcha_api_key(original_yes_key)


def test_retryable_generation_error_switches_captcha_method_after_recaptcha_failure(monkeypatch):
    client = FlowClient(proxy_manager=None)
    original_method = flow_client_module.config.captcha_method
    original_yes_key = flow_client_module.config.yescaptcha_api_key

    async def fake_notify(**kwargs):
        return None

    async def fake_sleep(_seconds):
        return None

    flow_client_module.config.set_captcha_method("ant_browser")
    flow_client_module.config.set_yescaptcha_api_key("yes-key")
    client._set_captcha_resolution({
        "requested_method": "ant_browser",
        "used_method": "ant_browser",
        "attempted_methods": ["ant_browser"],
        "fallback_used": False,
    })

    monkeypatch.setattr(client, "_notify_browser_captcha_error", fake_notify)
    monkeypatch.setattr(flow_client_module.asyncio, "sleep", fake_sleep)

    async def run_case():
        should_retry = await client._handle_retryable_generation_error(
            error=Exception("HTTP Error 403: reCAPTCHA evaluation failed"),
            retry_attempt=0,
            max_retries=4,
            browser_id=None,
            project_id="project-1",
            log_prefix="[IMAGE] 生成",
        )
        return should_retry, client.get_preferred_captcha_method()

    should_retry, preferred_method = asyncio.run(run_case())

    assert should_retry is True
    assert preferred_method == "yescaptcha"

    flow_client_module.config.set_captcha_method(original_method)
    flow_client_module.config.set_yescaptcha_api_key(original_yes_key)


def test_retryable_generation_error_keeps_captcha_method_for_generic_timeout(monkeypatch):
    client = FlowClient(proxy_manager=None)
    original_method = flow_client_module.config.captcha_method
    original_yes_key = flow_client_module.config.yescaptcha_api_key

    async def fake_notify(**kwargs):
        return None

    async def fake_sleep(_seconds):
        return None

    flow_client_module.config.set_captcha_method("ant_browser")
    flow_client_module.config.set_yescaptcha_api_key("yes-key")
    client._set_captcha_resolution({
        "requested_method": "ant_browser",
        "used_method": "ant_browser",
        "attempted_methods": ["ant_browser"],
        "fallback_used": False,
    })

    monkeypatch.setattr(client, "_notify_browser_captcha_error", fake_notify)
    monkeypatch.setattr(flow_client_module.asyncio, "sleep", fake_sleep)

    async def run_case():
        should_retry = await client._handle_retryable_generation_error(
            error=Exception("Flow API request failed: curl: (28) Connection timed out after 5000 milliseconds"),
            retry_attempt=0,
            max_retries=4,
            browser_id=None,
            project_id="project-1",
            log_prefix="[IMAGE] 生成",
        )
        return should_retry, client.get_preferred_captcha_method()

    should_retry, preferred_method = asyncio.run(run_case())

    assert should_retry is False
    assert preferred_method is None

    flow_client_module.config.set_captcha_method(original_method)
    flow_client_module.config.set_yescaptcha_api_key(original_yes_key)
