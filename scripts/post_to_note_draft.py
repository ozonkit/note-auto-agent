import os
import json
from pathlib import Path
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

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
    d = json.loads(Path("run_log.txt").read_text(encoding="utf-8"))
    return d["run_id"]

def extract_title_from_md(md_text: str, fallback: str):
    for line in md_text.splitlines():
        if line.startswith("# "):
            t = line[2:].strip()
            return t if t else fallback
        if line.strip():
            break
    return fallback

def main():
    run_id = os.getenv("RUN_ID") or read_run_id()
    run_dir = Path(os.getenv("RUN_DIR", f"drafts/generated/{run_id}"))
    images_dir = Path(os.getenv("IMAGES_DIR", f"assets/images/{run_id}"))

    article_path = run_dir / "article.md"
    cover_path = images_dir / "cover_1280x210.png"  # note推奨サイズ（なければ後で差し替え）

    if not Path(AUTH_FILE).exists():
        raise SystemExit("auth.json not found (restored from secrets?)")
    if not article_path.exists():
        raise SystemExit(f"article.md not found: {article_path}")

    article_md = article_path.read_text(encoding="utf-8")
    title = extract_title_from_md(article_md, f"Auto draft {run_id}")

    headless = os.getenv("HEADLESS", "true").lower() in ("1","true","yes","y")
    test_mode = os.getenv("TEST_MODE", "false").lower() in ("1","true","yes","y")

    log(f"RUN_ID={run_id}")
    log(f"HEADLESS={headless} TEST_MODE={test_mode}")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless, args=["--lang=ja-JP"])
        context = browser.new_context(locale="ja-JP", storage_state=AUTH_FILE)
        context.tracing.start(screenshots=True, snapshots=True, sources=False)

        page = context.new_page()
        page.set_default_timeout(180000)

        try:
            log("Open editor new page...")
            page.goto(NEW_URL, wait_until="domcontentloaded")

            # ログイン切れの判定（ログイン画面に飛ばされたらNG）
            if "login" in page.url:
                raise RuntimeError(f"Not logged in (redirected to {page.url}). Recreate auth.json after visiting editor.note.com/new.")

            # タイトル欄（noteのUI変更により要調整の可能性あり）
            page.wait_for_selector('textarea[placeholder*="タイトル"], textarea[placeholder*="title"]')
            page.fill('textarea[placeholder*="タイトル"], textarea[placeholder*="title"]', title)

            # 本文欄（contenteditableを優先）
            editor = page.locator('[contenteditable="true"]').first
            editor.click()
            # Markdownをそのまま貼る（整形はPhase3後半で詰める）
            page.keyboard.insert_text(article_md)

            # 画像アップロード（初回は壊れやすいので best-effort）
            if cover_path.exists():
                log(f"Cover found: {cover_path}")
                # 画像追加ボタンの候補（UI次第で変わるのでtraceで調整）
                # 「画像を追加」「画像」などを探索
                btn = page.locator('button[aria-label*="画像"], button:has-text("画像")').first
                if btn.count() > 0:
                    btn.click()
                    # input[type=file] が出るパターン
                    file_input = page.locator('input[type="file"]').first
                    if file_input.count() > 0:
                        file_input.set_input_files(str(cover_path))
            else:
                log("Cover image not found. Skipping cover upload for now.")

            # 下書き保存（UI表現が変わる可能性あり）
            save_btn = page.locator('button:has-text("下書き"), button:has-text("保存"), button:has-text("Save")').first
            if save_btn.count() > 0:
                if not test_mode:
                    save_btn.click()
                    page.wait_for_timeout(3000)
                else:
                    log("TEST_MODE=True: skipping click save.")
            else:
                log("Save button not found. You may need to adjust selectors with trace.")

            save_debug(page)

            # 成功時：編集URLに遷移している可能性があるので出力
            log(f"Current URL: {page.url}")

        except Exception as e:
            save_debug(page)
            raise
        finally:
            context.tracing.stop(path=TRACE_FILE)
            browser.close()

if __name__ == "__main__":
    main()
