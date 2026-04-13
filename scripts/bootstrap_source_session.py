from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from urllib import error, request


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Capture an operator-assisted session for a review source.")
    parser.add_argument("--source-id", type=int, required=True)
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
        browser = await playwright.chromium.launch(
            headless=False,
            args=["--disable-blink-features=AutomationControlled"],
        )
        context_kwargs = {"viewport": {"width": 1440, "height": 1024}}
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


def register_session(api_base_url: str, source_id: int, output_path: Path) -> bool:
    payload = json.dumps(
        {
            "session_reference": str(output_path),
            "status": "active",
        }
    ).encode("utf-8")
    req = request.Request(
        f"{api_base_url.rstrip('/')}/api/sources/{source_id}/sessions",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with request.urlopen(req, timeout=15) as resp:
            print(f"Session registered with START: HTTP {resp.status}")
    except error.URLError as exc:
        print(f"Could not register the session automatically: {exc}")
        print(f"Manual fallback: save this path in Admin > Sources > Session reference")
        print(str(output_path))
        return False
    return True


def trigger_sync(api_base_url: str, source_id: int) -> None:
    req = request.Request(
        f"{api_base_url.rstrip('/')}/api/fetch/trigger?source_id={source_id}",
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

    registered = register_session(args.api_base_url, args.source_id, output_path)
    if registered:
        trigger_sync(args.api_base_url, args.source_id)

    print("")
    print("You can close this window now.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
