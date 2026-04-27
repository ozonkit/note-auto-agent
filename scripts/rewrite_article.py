import os
import json
from pathlib import Path
from openai import AzureOpenAI

ROOT = Path(__file__).resolve().parents[1]
REWRITE_PROMPT_PATH = ROOT / "prompts" / "article_rewriter.md"


def read_run_id() -> str:
    path = ROOT / "run_log.txt"
    if not path.exists():
        raise RuntimeError("run_log.txt not found")
    return json.loads(path.read_text(encoding="utf-8"))["run_id"]


def load_prompt(article_text: str, review_text: str) -> str:
    template = REWRITE_PROMPT_PATH.read_text(encoding="utf-8")
    return (
        template
        .replace("{{ARTICLE}}", article_text)
        .replace("{{REVIEW}}", review_text)
    )


def main():
    run_id = os.getenv("RUN_ID") or read_run_id()
    run_dir = Path(os.getenv("RUN_DIR", ROOT / f"drafts/generated/{run_id}"))

    article_path = run_dir / "article.md"
    review_json_path = run_dir / "review.json"

    if not article_path.exists():
        raise SystemExit(f"article.md not found: {article_path}")

    if not review_json_path.exists():
        raise SystemExit(f"review.json not found: {review_json_path}")

    article_text = article_path.read_text(encoding="utf-8")
    review = json.loads(review_json_path.read_text(encoding="utf-8"))
    review_text = json.dumps(review, ensure_ascii=False, indent=2)

    prompt = load_prompt(article_text, review_text)

    client = AzureOpenAI(
        api_key=os.environ["AZURE_OPENAI_API_KEY"],
        azure_endpoint=os.environ["AZURE_OPENAI_ENDPOINT"],
        api_version=os.getenv("AZURE_OPENAI_API_VERSION", "2024-02-15-preview"),
    )

    response = client.chat.completions.create(
        model=os.environ["AZURE_OPENAI_DEPLOYMENT"],
        messages=[
            {
                "role": "system",
                "content": "あなたはnote記事の編集者です。改善後の記事本文のみを出力してください。",
            },
            {
                "role": "user",
                "content": prompt,
            },
        ],
        temperature=0.4,
    )

    rewritten = (response.choices[0].message.content or "").strip()

    if not rewritten:
        raise RuntimeError("rewritten article is empty")

    backup_path = run_dir / "article.before_rewrite.md"
    backup_path.write_text(article_text, encoding="utf-8")

    article_path.write_text(rewritten + "\n", encoding="utf-8")

    print(f"OK: rewritten article saved: {article_path}")
    print(f"Backup: {backup_path}")


if __name__ == "__main__":
    main()
