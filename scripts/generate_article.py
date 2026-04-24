import os
import json
from datetime import datetime
from pathlib import Path
from openai import OpenAI

ROOT = Path(__file__).resolve().parents[1]
PROMPTS = ROOT / "prompts"
OUTDIR = ROOT / "drafts" / "generated"


def load_prompt(path: Path, **kwargs) -> str:
    text = path.read_text(encoding="utf-8")
    for k, v in kwargs.items():
        text = text.replace("{{" + k + "}}", str(v))
    return text


def safe_read_text(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None


def main():
    theme = os.environ["THEME"]
    tone = os.environ.get("TONE", "note向け、自然体")
    words = os.environ.get("WORDS", "1800")

    # ✅ Azure OpenAI 用設定（テキスト生成）
    client = OpenAI(
        api_key=os.environ["AZURE_OPENAI_API_KEY"],
        base_url=f"{os.environ['AZURE_OPENAI_ENDPOINT'].rstrip('/')}/openai/v1/"
    )

    deployment = os.environ["AZURE_OPENAI_DEPLOYMENT"]

    run_id = datetime.now().strftime("%Y%m%d-%H%M%S")
    run_dir = OUTDIR / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    # 1) 記事設計
    planner_prompt = load_prompt(
        PROMPTS / "article_planner.md",
        THEME=theme,
        TONE=tone
    )

    plan = client.responses.create(
        model=deployment,  # ← 実モデル名ではなく deployment 名
        input=planner_prompt
    ).output_text.strip()

    (run_dir / "plan.md").write_text(plan + "\n", encoding="utf-8")

    # 2) 本文生成
    writer_prompt = load_prompt(
        PROMPTS / "article_writer.md",
        WORDS=words,
        TONE=tone
    )

    article = client.responses.create(
        model=deployment,
        input=f"## 設計\n{plan}\n\n{writer_prompt}"
    ).output_text.strip()

    (run_dir / "article.md").write_text(article + "\n", encoding="utf-8")

    # 3) 画像プロンプト生成（★追加：image_prompt.txt を作る）
    # prompts/image_prompt.md があればそれを使う。なければ簡易テンプレで生成。
    image_prompt_template = safe_read_text(PROMPTS / "image_prompt.md")
    if image_prompt_template is None:
        image_prompt_template = (
            "あなたはnoteの見出し画像（アイキャッチ）用の画像プロンプト作成者です。\n"
            "入力の記事内容（Markdown）を読み、画像生成モデルに渡す短いプロンプトを作ってください。\n\n"
            "出力:\n"
            "1行目: 画像プロンプト（短く具体的に）\n"
            "2行目: ネガティブプロンプト（なければ none）\n"
            "3行目: スタイル（例: minimal / flat / photorealistic）\n"
            "4行目: 画角（例: 3:1 / wide banner）\n"
        )

    # 画像生成（MAI-Image-2e）で使いやすいように、まず “1行目だけ” を使っても良い構造にする
    image_prompt_text = client.responses.create(
        model=deployment,
        input=(
            f"{image_prompt_template}\n\n"
            f"---\n"
            f"# 記事テーマ\n{theme}\n\n"
            f"# 記事本文（Markdown）\n{article}\n"
        )
    ).output_text.strip()

    (run_dir / "image_prompt.txt").write_text(image_prompt_text + "\n", encoding="utf-8")

    # ログ（run_id / deployment / theme + 生成物パスも残すと便利）
    (ROOT / "run_log.txt").write_text(
        json.dumps({
            "run_id": run_id,
            "deployment": deployment,
            "theme": theme,
            "tone": tone,
            "words": words,
            "paths": {
                "run_dir": str(run_dir.relative_to(ROOT)),
                "plan_md": str((run_dir / "plan.md").relative_to(ROOT)),
                "article_md": str((run_dir / "article.md").relative_to(ROOT)),
                "image_prompt_txt": str((run_dir / "image_prompt.txt").relative_to(ROOT)),
            }
        }, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8"
    )

    print("OK:", run_dir)


if __name__ == "__main__":
    main()
