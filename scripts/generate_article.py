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

def main():
    theme = os.environ["THEME"]
    tone = os.environ.get("TONE", "note向け、自然体")
    words = os.environ.get("WORDS", "1800")

    # ✅ Azure OpenAI 用設定
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
    ).output_text

    (run_dir / "plan.md").write_text(plan, encoding="utf-8")

    # 2) 本文生成
    writer_prompt = load_prompt(
        PROMPTS / "article_writer.md",
        WORDS=words,
        TONE=tone
    )

    article = client.responses.create(
        model=deployment,
        input=f"## 設計\n{plan}\n\n{writer_prompt}"
    ).output_text

    (run_dir / "article.md").write_text(article, encoding="utf-8")

    # ログ
    (ROOT / "run_log.txt").write_text(
        json.dumps({
            "run_id": run_id,
            "deployment": deployment,
            "theme": theme
        }, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )

    print("OK:", run_dir)

if __name__ == "__main__":
    main()