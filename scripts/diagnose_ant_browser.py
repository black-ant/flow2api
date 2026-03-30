"""Command-line helper to simulate an external ant-browser diagnostics call."""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any, Dict, Optional, Tuple
from urllib import error, request


DEFAULT_BASE_URL = "http://127.0.0.1:8000"


def _build_url(base_url: str, path: str) -> str:
    return f"{base_url.rstrip('/')}{path}"


def _http_json(
    url: str,
    method: str = "GET",
    payload: Optional[Dict[str, Any]] = None,
    bearer_token: str = "",
    timeout: int = 120,
) -> Tuple[int, Dict[str, Any]]:
    body = None
    headers = {
        "Accept": "application/json",
    }
    if payload is not None:
        body = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    if bearer_token:
        headers["Authorization"] = f"Bearer {bearer_token}"

    req = request.Request(url=url, data=body, method=method.upper(), headers=headers)
    try:
        with request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            return int(resp.status), json.loads(raw) if raw else {}
    except error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            payload = json.loads(raw) if raw else {}
        except Exception:
            payload = {"message": raw or str(exc)}
        return int(exc.code), payload
    except Exception as exc:
        raise RuntimeError(f"HTTP request failed: {exc}") from exc


def _login(base_url: str, username: str, password: str, timeout: int) -> str:
    status, payload = _http_json(
        _build_url(base_url, "/api/login"),
        method="POST",
        payload={"username": username, "password": password},
        timeout=timeout,
    )
    if status >= 400 or not payload.get("success") or not payload.get("token"):
        raise RuntimeError(f"Login failed: {payload.get('message') or payload}")
    return str(payload["token"])


def _format_bool(value: bool) -> str:
    return "yes" if value else "no"


def _print_summary(summary: Dict[str, Any]) -> None:
    print("== Diagnostics Summary ==")
    print(f"captcha_method: {summary.get('captcha_method') or '-'}")
    print(f"is_ant_browser_mode: {_format_bool(bool(summary.get('is_ant_browser_mode')))}")
    print(f"base_url: {summary.get('base_url') or '-'}")
    print(f"launch_code_configured: {_format_bool(bool(summary.get('launch_code_configured')))}")
    print(f"api_key_configured: {_format_bool(bool(summary.get('api_key_configured')))}")
    print(f"browser_proxy_enabled: {_format_bool(bool(summary.get('browser_proxy_enabled')))}")
    print(f"ready_for_diagnose: {_format_bool(bool(summary.get('ready_for_diagnose')))}")


def _print_run_result(result: Dict[str, Any]) -> None:
    print()
    print("== Diagnostics Result ==")
    print(f"success: {_format_bool(bool(result.get('success')))}")
    print(f"stage: {result.get('stage') or '-'}")
    print(f"message: {result.get('message') or '-'}")
    print(f"elapsed_ms: {result.get('elapsed_ms') or '-'}")

    steps = result.get("steps") or []
    if steps:
        print()
        print("== Steps ==")
        for index, step in enumerate(steps, start=1):
            print(f"{index}. [{step.get('status') or 'info'}] {step.get('title') or step.get('key') or 'step'}")
            print(f"   {step.get('message') or '-'}")
            details = step.get("details") or {}
            for key, value in details.items():
                rendered = json.dumps(value, ensure_ascii=False) if isinstance(value, (dict, list)) else str(value)
                print(f"   - {key}: {rendered}")

    verify_result = result.get("verify_result")
    if isinstance(verify_result, dict) and verify_result:
        print()
        print("== Verify Result ==")
        print(json.dumps(verify_result, ensure_ascii=False, indent=2))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Simulate an external ant-browser diagnostics call against the Flow2API admin API.",
    )
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL, help=f"Flow2API base URL, default: {DEFAULT_BASE_URL}")
    parser.add_argument("--token", default="", help="Existing admin bearer token")
    parser.add_argument("--username", default="", help="Admin username, used when --token is not provided")
    parser.add_argument("--password", default="", help="Admin password, used when --token is not provided")
    parser.add_argument("--timeout", type=int, default=180, help="HTTP timeout in seconds")
    parser.add_argument("--skip-run", action="store_true", help="Only fetch summary, do not execute diagnostics")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        token = args.token.strip()
        if not token:
            if not args.username or not args.password:
                raise RuntimeError("Provide either --token or both --username and --password")
            token = _login(args.base_url, args.username, args.password, args.timeout)

        _, summary_payload = _http_json(
            _build_url(args.base_url, "/api/diagnostics/ant-browser/summary"),
            method="GET",
            bearer_token=token,
            timeout=args.timeout,
        )
        summary = summary_payload.get("summary") if isinstance(summary_payload, dict) else {}
        _print_summary(summary if isinstance(summary, dict) else {})

        if args.skip_run:
            return 0

        _, run_payload = _http_json(
            _build_url(args.base_url, "/api/diagnostics/ant-browser/run"),
            method="POST",
            payload={},
            bearer_token=token,
            timeout=args.timeout,
        )
        _print_run_result(run_payload if isinstance(run_payload, dict) else {})
        return 0 if bool(run_payload.get("success")) else 2
    except Exception as exc:
        print(f"diagnose_ant_browser.py failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
