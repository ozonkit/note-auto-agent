from pathlib import Path

from playwright.sync_api import sync_playwright


ROOT = Path(__file__).resolve().parents[1]
AUTH_DIR = ROOT / ".auth"
AUTH_PATH = AUTH_DIR / "auth.json"


def main() -> None:
    AUTH_DIR.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=False,
        )

        context = browser.new_context()
        page = context.new_page()

        print("noteのログイン画面を開きます。")

        page.goto(
            "https://note.com/login",
            wait_until="domcontentloaded",
            timeout=60_000,
        )

        print()
        print("1. 開いたブラウザでnoteにログインしてください。")
        print("2. ログイン完了後、このターミナルへ戻ってください。")
        print("3. Enterキーを押してください。")
        print()

        input("ログインが完了したらEnter: ")

        print("ログイン状態を確認しています。")

        page.goto(
            "https://editor.note.com/new",
            wait_until="domcontentloaded",
            timeout=60_000,
        )

        page.wait_for_timeout(3_000)

        print("現在のURL:", page.url)

        if "login" in page.url.lower():
            browser.close()
            raise RuntimeError(
                "ログイン状態を確認できませんでした。"
                "ブラウザでnoteへのログインを完了してください。"
            )

        context.storage_state(path=str(AUTH_PATH))

        print()
        print("auth.jsonを保存しました。")
        print(AUTH_PATH)
        print()

        browser.close()


if __name__ == "__main__":
    main()
