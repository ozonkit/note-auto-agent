import os
import json
from pathlib import Path
from playwright.sync_api import sync_playwright

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
    lines = md_text.splitlines()
    while lines and (lines[0].strip() == "" or lines[0].strip().startswith("```")):
        lines = lines[1:]
    title = fallback_title
    body_lines = lines[:]
    if lines and lines[0].startswith("# "):
        title = lines[0][2:].strip() or fallback_title
        body_lines = lines[1:]
        while body_lines and body_lines[0].strip() == "":
            body_lines = body_lines[1:]
    body = "\n".join(body_lines).strip()
    return title, body

def md_to_note_body(md: str) -> str:
    out = []
    for line in md.splitlines():
        if line.startswith("## "):
            out.append("■ " + line[3:])
            out.append("")
        else:
            out.append(line)
    return "\n".join(out)

def main():
    run_id = os.getenv("RUN_ID") or read_run_id()
    run_dir = Path(os.getenv("RUN_DIR", f"drafts/generated/{run_id}"))
    images_dir = Path(os.getenv("IMAGES_DIR", f"assets/images/{run_id}")
    )
    article_path = run_dir / "article.md"
    
    # assets/images/{run_id}/cover_raw.png を使用
    cover_path = images_dir / "cover_raw.png"


    if not Path(AUTH_FILE).exists():
        raise SystemExit("auth.json not found")
    if not article_path.exists():
        raise SystemExit(f"article.md not found: {article_path}")

    article_md = article_path.read_text(encoding="utf-8")
    title, body_md = split_title_and_body(article_md, f"Auto draft {run_id}")
    body_for_note = md_to_note_body(body_md)

    headless = os.getenv("HEADLESS", "false").lower() in ("1", "true", "yes", "y")

    log(f"RUN_ID={run_id}")
    log(f"TITLE={title}")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless, args=["--lang=ja-JP"])
        context = browser.new_context(locale="ja-JP", storage_state=AUTH_FILE)
        context.tracing.start(screenshots=True, snapshots=True, sources=False)

        page = context.new_page()
        page.set_default_timeout(180000)

        try:
            log("Open note editor...")
            page.goto(NEW_URL, wait_until="domcontentloaded")
            page.wait_for_load_state("networkidle")
            page.wait_for_timeout(1500)

            if "login" in page.url:
                raise RuntimeError("Not logged in. auth.json invalid.")

            # ===== タイトル入力 =====
            title_box = page.locator('textarea[placeholder="記事タイトル"]').first
            title_box.wait_for(state="visible", timeout=30000)
            title_box.click()
            title_box.fill(title)

            # ===== 本文入力 =====
            editor = page.locator("div.ProseMirror[contenteditable='true']").first
            editor.wait_for(state="visible", timeout=30000)
            editor.click()
            for line in body_for_note.splitlines():
                page.keyboard.type(line, delay=0)
                page.keyboard.press("Enter")

            # ===== アイキャッチ画像アップロード =====
            cover_path = images_dir / "cover_raw.png"
            
            if cover_path.exists():
                try:
                    # 画像アイコンのエリア（ドラッグ＆ドロップ対応領域）を取得
                    # 例: data-dragging="false" か aria-label="画像を追加" のdiv/button
                    drop_target = page.locator('div[data-dragging]').first
                    # drop_target = page.locator('button[aria-label="画像を追加"]').first
                    drop_target.wait_for(state="visible", timeout=5000)
            
                    # ファイルをドラッグ＆ドロップでアップロード
                    drop_target.set_input_files(str(cover_path))
                    page.wait_for_timeout(1500)
                    log("Cover image uploaded (cover_raw.png) via drag & drop.")
            
                except Exception as e:
                    log(f"Cover upload failed: {e}")
            else:
                log("cover_raw.png not found. Skipping cover upload.")



            # ===== 下書き保存 =====
            save_btn = page.locator('button:has-text("下書き保存")').first
            save_btn.wait_for(state="visible", timeout=30000)
            save_btn.click()
            page.wait_for_timeout(2000)  # 保存完了待ち

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
