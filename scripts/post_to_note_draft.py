import os
import json
import re
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
    """
    noteエディタに貼り付けやすい形へ変換する。
    Markdownを完全再現するのではなく、note上で崩れにくいプレーンテキスト寄りにする。
    """
    out = []

    for raw_line in md.splitlines():
        line = raw_line.rstrip()

        # コードフェンスは除去
        if line.strip().startswith("```"):
            continue

        # h2, h3
        if line.startswith("## "):
            out.append("■ " + line[3:].strip())
            out.append("")
            continue

        if line.startswith("### "):
            out.append("■ " + line[4:].strip())
            out.append("")
            continue

        # 引用
        if line.startswith("> "):
            out.append("“" + line[2:].strip() + "”")
            out.append("")
            continue

        # 箇条書き：note側で崩れにくい「・」に寄せる
        if line.startswith("- "):
            line = "・" + line[2:].strip()

        # 番号付きリストはそのまま少し整える
        line = re.sub(r"^\d+\.\s+", lambda m: m.group(0), line)

        # Markdown太字 **xxx** を note入力用に除去
        # 太字装飾より、記事崩れ防止を優先
        line = re.sub(r"\*\*(.*?)\*\*", r"\1", line)

        # Markdown斜体 *xxx* も除去
        line = re.sub(r"(?<!\*)\*(?!\*)(.*?)(?<!\*)\*(?!\*)", r"\1", line)

        out.append(line)

    text = "\n".join(out).strip()

    # 空行が多すぎる場合の整理
    text = re.sub(r"\n{4,}", "\n\n\n", text)

    return text


def paste_text(page, locator, text: str):
    """
    ProseMirrorに安定して本文を入れる。
    1行ずつtypeすると、箇条書きやMarkdown記号が崩れやすいので貼り付け方式にする。
    """
    locator.click()

    # Chromium上でclipboard権限を使わずに貼り付けるため、execCommandを使う
    page.evaluate(
        """
        async (text) => {
            await navigator.clipboard.writeText(text);
        }
        """,
        text,
    )

    modifier = "Meta" if os.getenv("RUNNER_OS", "").lower() == "macos" else "Control"
    page.keyboard.press(f"{modifier}+V")
    page.wait_for_timeout(1000)


def click_first_visible(page, locators, timeout=5000):
    last_error = None

    for locator in locators:
        try:
            target = locator.first
            target.wait_for(state="visible", timeout=timeout)
            target.click()
            return True
        except Exception as e:
            last_error = e

    if last_error:
        raise last_error

    return False


def upload_cover_image(page, cover_path: Path):
    """
    noteの見出し画像アップロード。
    filechooser方式を優先し、保存ボタンはモーダル内にスコープして押す。
    """
    log("Start cover image upload...")

    # 画像追加ボタン
    image_icon = page.locator('button[aria-label="画像を追加"]').first
    image_icon.wait_for(state="visible", timeout=10000)
    image_icon.click()
    page.wait_for_timeout(500)

    # アップロードボタン候補
    upload_candidates = [
        page.get_by_role("button", name=re.compile("画像をアップロード|アップロード")),
        page.get_by_text(re.compile("画像をアップロード|アップロード")),
        page.locator('button.sc-131cded0-7.kwxNSB'),
    ]

    with page.expect_file_chooser(timeout=15000) as fc_info:
        clicked = click_first_visible(page, upload_candidates, timeout=5000)
        if not clicked:
            raise RuntimeError("Upload button not clicked")

    file_chooser = fc_info.value
    file_chooser.set_files(str(cover_path.resolve()))
    log(f"Cover image selected: {cover_path.resolve()}")

    page.wait_for_timeout(1500)

    # トリミングモーダルを待つ
    modal = page.locator(".ReactModal__Overlay").filter(has_text="保存").nth(-1)
    modal.wait_for(state="visible", timeout=30000)

    # 画像読み込み待ち
    modal.locator("img").first.wait_for(state="visible", timeout=30000)
    page.wait_for_timeout(1000)

    # 保存ボタン
    save_btn = modal.get_by_role("button", name="保存")
    save_btn.wait_for(state="visible", timeout=30000)

    handle = save_btn.element_handle()
    if handle is None:
        raise RuntimeError("Save button handle not found")

    page.wait_for_function(
        """btn => btn && !btn.disabled && btn.getAttribute('aria-disabled') !== 'true'""",
        arg=handle,
        timeout=30000,
    )

    save_btn.scroll_into_view_if_needed()

    try:
        save_btn.click(timeout=10000)
    except Exception:
        log("Normal click failed. Try JS click.")
        page.evaluate("(btn) => btn.click()", handle)

    modal.wait_for(state="detached", timeout=30000)
    log("Cover image edit saved.")


def main():
    run_id = os.getenv("RUN_ID") or read_run_id()
    run_dir = Path(os.getenv("RUN_DIR", ROOT / f"drafts/generated/{run_id}"))
    images_dir = Path(os.getenv("IMAGES_DIR", ROOT / f"assets/images/{run_id}"))
    
    article_path = run_dir / "article.md"
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
        browser = p.chromium.launch(
            headless=headless,
            args=["--lang=ja-JP"],
        )

        context = browser.new_context(
            locale="ja-JP",
            storage_state=AUTH_FILE,
            permissions=["clipboard-read", "clipboard-write"],
        )

        context.tracing.start(
            screenshots=True,
            snapshots=True,
            sources=False,
        )

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
            log("Title filled.")

            # ===== 本文入力 =====
            editor = page.locator("div.ProseMirror[contenteditable='true']").first
            editor.wait_for(state="visible", timeout=30000)

            paste_text(page, editor, body_for_note)
            log("Body pasted.")

            page.wait_for_timeout(1500)

            # ===== アイキャッチ画像アップロード =====
            print(f"IMAGE_PATH={cover_path}")
            if cover_path.exists():
                try:
                    upload_cover_image(page, cover_path)
                except Exception as e:
                    log(f"Cover upload failed: {e}")
                    save_debug(page)
            else:
                log("cover_raw.png not found. Skipping cover upload.")

            # ===== 下書き保存 =====
            draft_save_btn = page.locator('button:has-text("下書き保存")').first
            draft_save_btn.wait_for(state="visible", timeout=30000)
            draft_save_btn.click()

            page.wait_for_timeout(3000)

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
