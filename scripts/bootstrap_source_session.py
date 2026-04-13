from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from urllib import error, request

from app.config import settings


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Capture an operator-assisted session for a review source.")
    parser.add_argument("--source-id", type=int, required=True)
    parser.add_argument("--share-scope", default="source")
    parser.add_argument("--platform", required=True)
    parser.add_argument("--source-url", required=True)
    parser.add_argument("--source-label", required=True)
    parser.add_argument("--output-path", required=True)
    parser.add_argument("--api-base-url", default="http://127.0.0.1:8000")
    return parser.parse_args()


async def capture_session(source_url: str, source_label: str, output_path: Path) -> tuple[str, str]:
    from playwright.async_api import async_playwright

    existing_state = output_path if output_path.exists() else None
    async with async_playwright() as playwright:
        launch_kwargs = {
            "headless": False,
            "args": [f"--lang={settings.review_browser_locale}", "--disable-blink-features=AutomationControlled"],
        }
        proxy_server = _proxy_server_for(source_url)
        if proxy_server:
            launch_kwargs["proxy"] = {"server": proxy_server}
        browser = await playwright.chromium.launch(
            **launch_kwargs,
        )
        context_kwargs = {
            "viewport": {"width": 1440, "height": 1024},
            "locale": settings.review_browser_locale,
            "timezone_id": settings.review_browser_timezone,
            "extra_http_headers": {"Accept-Language": f"{settings.review_browser_locale},en;q=0.9"},
        }
        if existing_state:
            context_kwargs["storage_state"] = str(existing_state)
        context = await browser.new_context(**context_kwargs)
        page = await context.new_page()
        print("")
        print(f"Opening {source_label} in a browser window...")
        await page.goto(source_url, wait_until="domcontentloaded", timeout=45000)
        print("1. Log in with the authorized staff account if the site asks you to sign in.")
        print("2. Navigate until the review page is fully visible and usable.")
        print("3. Leave the browser open, then come back to this window and press ENTER to save the session.")
        input("")
        await context.storage_state(path=str(output_path))
        current_url = page.url
        title = await page.title()
        await browser.close()
        return current_url, title


def _proxy_server_for(source_url: str) -> str:
    lowered = source_url.lower()
    if "google." in lowered:
        return settings.google_browser_proxy
    if "yelp." in lowered:
        return settings.yelp_browser_proxy
    return ""


def register_session(api_base_url: str, source_id: int, output_path: Path, share_scope: str) -> bool:
    return _register_session(
        api_base_url=api_base_url,
        source_id=source_id,
        output_path=output_path,
        share_scope=share_scope,
        source_url_override=None,
    )


def _register_session(
    api_base_url: str,
    source_id: int,
    output_path: Path,
    share_scope: str,
    source_url_override: str | None,
) -> bool:
    payload = json.dumps(
        {
            "session_reference": str(output_path),
            "status": "active",
            "source_url_override": source_url_override,
        }
    ).encode("utf-8")
    req = request.Request(
        f"{api_base_url.rstrip('/')}/api/sources/{source_id}/sessions?share_scope={share_scope}",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with request.urlopen(req, timeout=15) as resp:
            body = json.loads(resp.read().decode("utf-8"))
            print(f"Session registered with START: HTTP {resp.status}")
            if body.get("source_url_updated") and body.get("source_url"):
                print(f"Saved exact review URL for this source: {body['source_url']}")
    except error.URLError as exc:
        print(f"Could not register the session automatically: {exc}")
        print(f"Manual fallback: save this path in Admin > Sources > Session reference")
        print(str(output_path))
        return False
    return True


def trigger_sync(api_base_url: str, source_id: int, platform: str, share_scope: str) -> None:
    query = f"platform={platform}" if share_scope == "platform" else f"source_id={source_id}"
    req = request.Request(
        f"{api_base_url.rstrip('/')}/api/fetch/trigger?{query}",
        data=b"",
        method="POST",
    )
    try:
        with request.urlopen(req, timeout=15) as resp:
            print(f"Sync triggered: HTTP {resp.status}")
    except error.URLError as exc:
        print(f"Session saved, but sync trigger failed: {exc}")


def main() -> int:
    args = parse_args()
    output_path = Path(args.output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    print("START session bootstrap")
    print(f"Source: {args.source_label} ({args.platform})")
    print(f"Scope: {args.share_scope}")
    print(f"Output: {output_path}")

    try:
        current_url, title = asyncio.run(
            capture_session(
                source_url=args.source_url,
                source_label=args.source_label,
                output_path=output_path,
            )
        )
    except KeyboardInterrupt:
        print("Bootstrap cancelled.")
        return 1
    except Exception as exc:
        print(f"Session capture failed: {exc}")
        return 1

    print("")
    print("Session captured successfully.")
    print(f"Last page: {title or '(untitled)'}")
    print(f"URL: {current_url}")

    registered = _register_session(
        args.api_base_url,
        args.source_id,
        output_path,
        args.share_scope,
        current_url,
    )
    if registered:
        trigger_sync(args.api_base_url, args.source_id, args.platform, args.share_scope)

    print("")
    print("You can close this window now.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
