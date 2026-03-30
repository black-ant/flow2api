"""Simulate external image/video generation requests against Flow2API."""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any, Dict, List, Optional, Tuple
from urllib import error, request


DEFAULT_BASE_URL = "http://127.0.0.1:8000"


def _build_url(base_url: str, path: str) -> str:
    return f"{base_url.rstrip('/')}{path}"


def _http_json(
    url: str,
    method: str = "GET",
    payload: Optional[Dict[str, Any]] = None,
    headers: Optional[Dict[str, str]] = None,
    timeout: int = 1800,
) -> Tuple[int, Dict[str, Any]]:
    body = None
    req_headers = {
        "Accept": "application/json",
        **(headers or {}),
    }
    if payload is not None:
        body = json.dumps(payload).encode("utf-8")
        req_headers["Content-Type"] = "application/json"

    req = request.Request(url=url, data=body, method=method.upper(), headers=req_headers)
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


def _get_playground_config(base_url: str, admin_token: str, timeout: int) -> Dict[str, Any]:
    status, payload = _http_json(
        _build_url(base_url, "/api/playground/config"),
        headers={"Authorization": f"Bearer {admin_token}"},
        timeout=timeout,
    )
    if status >= 400 or not payload.get("success"):
        raise RuntimeError(f"Failed to load playground config: {payload}")
    return payload.get("config") or {}


def _build_openai_payload(model: str, prompt: str, image_urls: List[str]) -> Dict[str, Any]:
    content: List[Dict[str, Any]] = [{"type": "text", "text": prompt}]
    for image_url in image_urls:
        content.append({"type": "image_url", "image_url": {"url": image_url}})
    return {
        "model": model,
        "messages": [{"role": "user", "content": content}],
        "stream": False,
    }


def _build_gemini_payload(prompt: str, image_urls: List[str]) -> Dict[str, Any]:
    parts: List[Dict[str, Any]] = [{"text": prompt}]
    for image_url in image_urls:
        parts.append({"fileData": {"fileUri": image_url, "mimeType": "image/png"}})
    return {"contents": [{"role": "user", "parts": parts}]}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Simulate image/video generation requests against Flow2API.")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL, help=f"Flow2API base URL, default: {DEFAULT_BASE_URL}")
    parser.add_argument("--admin-token", default="", help="Existing admin token for reading playground config")
    parser.add_argument("--username", default="", help="Admin username if --admin-token is not provided")
    parser.add_argument("--password", default="", help="Admin password if --admin-token is not provided")
    parser.add_argument("--mode", choices=["openai", "gemini"], default="openai")
    parser.add_argument("--model", required=True, help="Target generation model")
    parser.add_argument("--prompt", required=True, help="Prompt text")
    parser.add_argument("--image-url", action="append", default=[], help="Optional reference image URL; can be repeated")
    parser.add_argument("--timeout", type=int, default=1800, help="HTTP timeout in seconds")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        admin_token = args.admin_token.strip()
        if not admin_token:
            if not args.username or not args.password:
                raise RuntimeError("Provide either --admin-token or both --username and --password")
            admin_token = _login(args.base_url, args.username, args.password, args.timeout)

        cfg = _get_playground_config(args.base_url, admin_token, args.timeout)
        api_key = str(cfg.get("api_key") or "").strip()
        if not api_key:
            raise RuntimeError("Playground config did not return an API key")

        if args.mode == "openai":
            endpoint = _build_url(args.base_url, "/v1/chat/completions")
            headers = {"Authorization": f"Bearer {api_key}"}
            payload = _build_openai_payload(args.model, args.prompt, args.image_url)
        else:
            endpoint = _build_url(args.base_url, f"/models/{args.model}:generateContent")
            headers = {"x-goog-api-key": api_key}
            payload = _build_gemini_payload(args.prompt, args.image_url)

        print("== Request ==")
        print(json.dumps({"endpoint": endpoint, "headers": headers, "body": payload}, ensure_ascii=False, indent=2))
        status, response_payload = _http_json(
            endpoint,
            method="POST",
            payload=payload,
            headers=headers,
            timeout=args.timeout,
        )
        print()
        print("== Response ==")
        print(f"status: {status}")
        print(json.dumps(response_payload, ensure_ascii=False, indent=2))
        return 0 if status < 400 else 2
    except Exception as exc:
        print(f"simulate_generation_request.py failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
