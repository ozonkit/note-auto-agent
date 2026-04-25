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

def split_title_and_body(md_text: str, fallback_title: str):
    """
    - 先頭行が '# ' の場合：それをタイトルに、本文から除外
    - それ以外：fallback_title をタイトルに、本文はそのまま
    """
    lines = md_text.splitlines()
    title = fallback_title
    body_lines = lines[:]

    if lines and lines[0].startswith("# "):
        title = lines[0][2:].strip() or fallback_title
        body_lines = lines[1:]

        # 先頭の空行を削る
        while body_lines and body_lines[0].strip() == "":
            body_lines = body_lines[1:]

    body = "\n".join(body_lines).strip()
    return title, body

def try_fill_first(page, selectors, text, timeout_each=5000):
    """
    複数候補のセレクタを順に試し、最初に見つかった要素へ入力する。
    成功したら True。
    """
    for sel in selectors:
        loc = page.locator(sel).first
        try:
            loc.wait_for(state="visible", timeout=timeout_each)
            loc.click()
            # input/textareaならfillが効く。contenteditable系はキーボードで上書き
            tag = None
            try:
                tag = loc.evaluate("el => el.tagName")
            except Exception:
                tag = None

            # 既存文字を消して入れ替え
            if tag in ("INPUT", "TEXTAREA"):
                loc.fill("")
                loc.fill(text)
            else:
                page.keyboard.press("Control+A")
                page.keyboard.insert_text(text)
            return True
        except Exception:
            continue
    return False

def main():
    run_id = os.getenv("RUN_ID") or read_run_id()
    run_dir = Path(os.getenv("RUN_DIR", f"drafts/generated/{run_id}"))
    images_dir = Path(os.getenv("IMAGES_DIR", f"assets/images/{run_id}"))

    article_path = run_dir / "article.md"
    cover_path = images_dir / "cover_1280x210.png"  # note推奨

    if not Path(AUTH_FILE).exists():
        raise SystemExit("auth.json not found (restored from secrets?)")
    if not article_path.exists():
        raise SystemExit(f"article.md not found: {article_path}")

    article_md = article_path.read_text(encoding="utf-8")

    fallback_title = f"Auto draft {run_id}"
    title, body_md = split_title_and_body(article_md, fallback_title)

    headless = os.getenv("HEADLESS", "true").lower() in ("1", "true", "yes", "y")
    test_mode = os.getenv("TEST_MODE", "false").lower() in ("1", "true", "yes", "y")
    upload_cover = os.getenv("UPLOAD_COVER", "true").lower() in ("1", "true", "yes", "y")

    log(f"RUN_ID={run_id}")
    log(f"HEADLESS={headless} TEST_MODE={test_mode} UPLOAD_COVER={upload_cover}")
    log(f"RUN_DIR={run_dir}")
    log(f"IMAGES_DIR={images_dir}")
    log(f"TITLE={title}")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless, args=["--lang=ja-JP"])
        context = browser.new_context(locale="ja-JP", storage_state=AUTH_FILE)

        # 失敗時に追えるよう tracing を開始（Artifacts 回収前提）[2](https://techcommunity.microsoft.com/blog/azure-ai-foundry-blog/introducing-mai-image-2-efficient-faster-more-efficient-image-generation/4510918)
        context.tracing.start(screenshots=True, snapshots=True, sources=False)

        page = context.new_page()
        page.set_default_timeout(180000)

        # 白画面原因の手掛かり用（任意だが効く）
        page.on("console", lambda m: log(f"[console] {m.type}: {m.text}"))
        page.on("pageerror", lambda e: log(f"[pageerror] {e}"))
        page.on("requestfailed", lambda r: log(f"[requestfailed] {r.url} {r.failure}"))

        try:
            log("Open editor new page...")
            page.goto(NEW_URL, wait_until="domcontentloaded")

            # SPA描画待ち（白画面/ローディング対策の補助）
            page.wait_for_load_state("networkidle")
            page.wait_for_timeout(2000)

            # URLでloginへ飛ぶ場合
            if "login" in page.url:
                raise RuntimeError(
                    f"Not logged in (redirected to {page.url}). "
                    f"Recreate auth.json after visiting editor.note.com/new."
                )

            # URLが変わらずログイン要求UIが出る場合
            login_like = page.locator('text=ログイン, text=Sign in, a[href*="login"], button:has-text("ログイン")')
            if login_like.count() > 0:
                raise RuntimeError(
                    "Login prompt detected on editor page. "
                    "auth.json may be invalid for editor.note.com"
                )

            # -----------------------------
            # 1) タイトル入力（候補を広めに）
            # -----------------------------
            title_candidates = [
                'textarea[placeholder*="タイトル"]',
                'textarea[aria-label*="タイトル"]',
                'input[placeholder*="タイトル"]',
                'input[aria-label*="タイトル"]',
                '[data-testid*="title"] textarea',
                '[data-testid*="title"] input',
                'h1[contenteditable="true"]',
                '[contenteditable="true"][data-testid*="title"]',
            ]

            ok_title = try_fill_first(page, title_candidates, title)
            if not ok_title:
                raise RuntimeError("Title field not found. Check trace.zip/debug.html to update selectors.")

            # -----------------------------
            # 2) 本文入力（ProseMirror優先）
            #    ※ ```markdown が出る問題は入力先ズレが多いので、本文エディタ本体を狙う
            # -----------------------------
            editor_candidates = [
                "div.ProseMirror[contenteditable='true']",
                "[role='textbox'][contenteditable='true']",
                "div[contenteditable='true']",
            ]

            editor_found = False
            for sel in editor_candidates:
                loc = page.locator(sel).first
                try:
                    loc.wait_for(state="visible", timeout=15000)
                    loc.click()
                    page.keyboard.press("Control+A")
                    page.keyboard.insert_text(body_md)
                    editor_found = True
                    break
                except Exception:
                    continue

            if not editor_found:
                raise RuntimeError("Body editor not found. Check trace.zip/debug.html to update selectors.")

            # -----------------------------
            # 3) アイキャッチ（best-effort）
            # -----------------------------
            if upload_cover and cover_path.exists():
                log(f"Cover found: {cover_path}")

                # 左上の画像プレースホルダを狙う（UI次第で調整が必要なのでtraceで確定推奨）
                # まず file input を探し、なければプレースホルダをクリックして出す
                file_input = page.locator('input[type="file"]').first
                if file_input.count() == 0:
                    # それっぽいボタン/領域をクリックして file input を出す
                    placeholder_candidates = [
                        "button:has(svg)",
                        "div:has(svg)",
                        "button:has-text('画像')",
                        "button[aria-label*='画像']",
                    ]
                    for sel in placeholder_candidates:
                        try:
                            page.locator(sel).first.click(timeout=2000)
                            break
                        except Exception:
                            pass
                    page.wait_for_timeout(500)
                    file_input = page.locator('input[type="file"]').first

                if file_input.count() > 0:
                    file_input.set_input_files(str(cover_path))
                    page.wait_for_timeout(1500)
                else:
                    log("Cover upload input not found. (best-effort)")

            else:
                log("Cover image not found or UPLOAD_COVER=false. Skipping cover upload.")

            # -----------------------------
            # 4) 下書き保存（best-effort）
            # -----------------------------
            save_btn = page.locator(
                'button:has-text("下書き"), button:has-text("保存"), button:has-text("Save")'
            ).first

            if save_btn.count() > 0:
                if not test_mode:
                    save_btn.click()
                    page.wait_for_timeout(3000)
                else:
                    log("TEST_MODE=True: skipping click save.")
            else:
                log("Save button not found. You may need to adjust selectors with trace.")

            save_debug(page)
            log(f"Current URL: {page.url}")

        except Exception:
            save_debug(page)
            raise
        finally:
            # trace は原因究明に非常に有効（Artifacts回収前提）[2](https://techcommunity.microsoft.com/blog/azure-ai-foundry-blog/introducing-mai-image-2-efficient-faster-more-efficient-image-generation/4510918)
            context.tracing.stop(path=TRACE_FILE)
            browser.close()

if __name__ == "__main__":
    main()
