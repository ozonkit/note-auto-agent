import os
import json
from pathlib import Path
from openai import OpenAI

REVIEW_PROMPT_PATH = Path("prompts/article_quality_review.md")

PASS_SCORE = int(os.getenv("PASS_SCORE", "80"))


def load_prompt(article_text: str) -> str:
    template = REVIEW_PROMPT_PATH.read_text(encoding="utf-8")
    return template.replace("{{ARTICLE}}", article_text)


def extract_json(text: str) -> dict:
    """
    LLMが余計な文字を返した場合に備えてJSON部分だけ抜き出す。
    """
    start = text.find("{")
    end = text.rfind("}")

    if start == -1 or end == -1:
        raise ValueError("JSON object not found in LLM response")

    return json.loads(text[start:end + 1])


def review_article(article_path: Path, output_dir: Path) -> dict:
    client = AzureOpenAI(
        api_key=os.environ["AZURE_OPENAI_API_KEY"],
        azure_endpoint=os.environ["AZURE_OPENAI_ENDPOINT"],
        api_version=os.getenv("AZURE_OPENAI_API_VERSION", "2024-02-15-preview")
    )
    
    response = client.chat.completions.create(
        model=os.environ["AZURE_OPENAI_DEPLOYMENT"],  # ←ここ重要
        messages=[
            {"role": "system", "content": "あなたはnote記事の編集者です。JSONのみで回答してください。"},
            {"role": "user", "content": prompt}
        ],
        temperature=0.2,
    )

    content = response.choices[0].message.content
    result = extract_json(content)

    total_score = int(result.get("total_score", 0))
    result["pass"] = total_score >= PASS_SCORE

    output_dir.mkdir(parents=True, exist_ok=True)

    review_json_path = output_dir / "review.json"
    review_md_path = output_dir / "review.md"

    review_json_path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )

    review_md_path.write_text(
        format_review_markdown(result),
        encoding="utf-8"
    )

    return result


def format_review_markdown(result: dict) -> str:
    lines = []

    lines.append(f"# 記事品質レビュー")
    lines.append("")
    lines.append(f"総合スコア：{result.get('total_score')}点")
    lines.append(f"合格判定：{'合格' if result.get('pass') else '要改善'}")
    lines.append("")

    lines.append("## 良い点")
    for item in result.get("strengths", []):
        lines.append(f"- {item}")

    lines.append("")
    lines.append("## 弱い点")
    for item in result.get("weaknesses", []):
        lines.append(f"- {item}")

    lines.append("")
    lines.append("## 改善案")
    for item in result.get("improvements", []):
        lines.append(f"- {item}")

    paid = result.get("paid_potential", {})
    lines.append("")
    lines.append("## 有料化判定")
    lines.append(f"- 有料化候補：{paid.get('is_paid_candidate')}")
    lines.append(f"- 理由：{paid.get('reason')}")
    lines.append(f"- 有料化するなら：{paid.get('suggested_paid_section')}")
    lines.append(f"- 想定価格：{paid.get('suggested_price_yen')}")

    lines.append("")
    lines.append("## 推奨タグ")
    for tag in result.get("recommended_tags", []):
        lines.append(f"- {tag}")

    lines.append("")
    lines.append(f"## 推奨マガジン")
    lines.append(str(result.get("recommended_magazine", "")))

    return "\n".join(lines)


def main():
    run_id = os.getenv("RUN_ID")
    if not run_id:
        run_id = json.loads(Path("run_log.txt").read_text(encoding="utf-8"))["run_id"]

    run_dir = Path(os.getenv("RUN_DIR", f"drafts/generated/{run_id}"))
    article_path = run_dir / "article.md"

    if not article_path.exists():
        raise SystemExit(f"article.md not found: {article_path}")

    result = review_article(article_path, run_dir)

    print(json.dumps(result, ensure_ascii=False, indent=2))

    if not result["pass"]:
        raise SystemExit(
            f"Article quality check failed. score={result.get('total_score')}"
        )


if __name__ == "__main__":
    main()
