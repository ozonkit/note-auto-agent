import os
import json
from pathlib import Path
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]

AUTH_FILE = "auth.json"
TRACE_FILE = "trace.zip"
DEBUG_PNG = "debug.png"
DEBUG_HTML = "debug.html"

NEW_URL = "https://editor.note.com/new"

def log(msg: str):
    print(msg, flush=True)

def save_debug(page):
    try:
        page.screenshot(path=DEBUG_PNG, full_page=True)
        log(f"Saved screenshot: {DEBUG_PNG}")
    except Exception as e:
        log(f"Failed screenshot: {e}")
    try:
        Path(DEBUG_HTML).write_text(page.content(), encoding="utf-8")
        log(f"Saved HTML: {DEBUG_HTML}")
    except Exception as e:
        log(f"Failed HTML: {e}")

def read_run_id():
    return json.loads(Path("run_log.txt").read_text(encoding="utf-8"))["run_id"]

def split_title_and_body(md_text: str, fallback_title: str):
    """
    先頭が '# ' ならタイトルに回し、本文から除外。
    """
    lines = md_text.splitlines()
    title = fallback_title
    body_lines = lines[:]

    if lines and lines[0].startswith("# "):
        title = lines[0][2:].strip() or fallback_title
        body_lines = lines[1:]
        while body_lines and body_lines[0].strip() == "":
            body_lines = body_lines[1:]

    body = "\n".join(body_lines).strip()
    return title, body

def main():
    run_id = os.getenv("RUN_ID") or read_run_id()
    run_dir = Path(os.getenv("RUN_DIR", f"drafts/generated/{run_id}"))

    article_path = run_dir / "article.md"

    if not Path(AUTH_FILE).exists():
        raise SystemExit("auth.json not found")
    if not article_path.exists():
        raise SystemExit(f"article.md not found: {article_path}")

    article_md = article_path.read_text(encoding="utf-8")
    fallback_title = f"Auto draft {run_id}"
    title, body_md = split_title_and_body(article_md, fallback_title)

    headless = os.getenv("HEADLESS", "false").lower() in ("1", "true", "yes", "y")

    log(f"RUN_ID={run_id}")
    log(f"HEADLESS={headless}")
    log(f"TITLE={title}")

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=headless,
            args=["--lang=ja-JP"]
        )
        context = browser.new_context(
            locale="ja-JP",
            storage_state=AUTH_FILE
        )

        context.tracing.start(
            screenshots=True,
            snapshots=True,
            sources=False
        )

        page = context.new_page()
        page.set_default_timeout(180000)

        page.on("console", lambda m: log(f"[console] {m.type}: {m.text}"))
        page.on("pageerror", lambda e: log(f"[pageerror] {e}"))
        page.on("requestfailed", lambda r: log(f"[requestfailed] {r.url} {r.failure}"))

        try:
            log("Open note editor (new)...")
            page.goto(NEW_URL, wait_until="domcontentloaded")
            page.wait_for_load_state("networkidle")
            page.wait_for_timeout(2000)

            if "login" in page.url:
                raise RuntimeError("Not logged in. auth.json is invalid for editor.note.com")

            # ===== A. タイトル（これだけ・確実）=====
            title_el = page.locator("h1[contenteditable='true']").first
            title_el.wait_for(state="visible", timeout=30000)
            title_el.click()
            page.keyboard.press("Control+A")
            page.keyboard.insert_text(title)

            # ===== B. 本文（ProseMirror限定）=====
            editor = page.locator("div.ProseMirror[contenteditable='true']").first
            editor.wait_for(state="visible", timeout=30000)
            editor.click()
            page.keyboard.press("Control+A")
            page.keyboard.insert_text(body_md)

            save_debug(page)
            log(f"SUCCESS. Current URL: {page.url}")

        except Exception:
            save_debug(page)
            raise
        finally:
            context.tracing.stop(path=TRACE_FILE)
            browser.close()

if __name__ == "__main__":
    main()
