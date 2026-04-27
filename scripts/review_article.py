import os
import json
import re
from pathlib import Path
from openai import AzureOpenAI

REVIEW_PROMPT_PATH = Path("prompts/article_quality_review.md")
PASS_SCORE = int(os.getenv("PASS_SCORE", "80"))


def load_prompt(article_text: str) -> str:
    template = REVIEW_PROMPT_PATH.read_text(encoding="utf-8")
    return template.replace("{{ARTICLE}}", article_text)


def extract_json(text: str) -> dict:
    start = text.find("{")
    end = text.rfind("}")

    if start == -1 or end == -1:
        raise ValueError("JSON object not found in LLM response")

    return json.loads(text[start:end + 1])


def build_meta_block(result: dict, existing_article: str) -> str:
    paid = result.get("paid_potential", {})
    tags = result.get("recommended_tags", [])
    tags_text = " ".join(tags) if isinstance(tags, list) else str(tags)

    # 既存METAからカテゴリ等を拾う
    def pick(label: str, default: str = "") -> str:
        m = re.search(rf"^{label}：(.+)$", existing_article, flags=re.MULTILINE)
        return m.group(1).strip() if m else default

    return f"""---META---
カテゴリ：{pick("カテゴリ")}
ターゲット：{pick("ターゲット")}
角度：{pick("角度")}
有料化候補：{paid.get("is_paid_candidate", "不明")}
想定価格：{paid.get("suggested_price_yen", "未定")}
タグ：{tags_text}
レビュー：{result.get("total_score", "未評価")}点
推奨マガジン：{result.get("recommended_magazine", "")}
有料化するなら：{paid.get("suggested_paid_section", "")}
---END---"""


def replace_or_append_meta(article_text: str, result: dict) -> str:
    meta_block = build_meta_block(result, article_text)

    pattern = r"---META---.*?---END---"
    if re.search(pattern, article_text, flags=re.DOTALL):
        return re.sub(pattern, meta_block, article_text, flags=re.DOTALL).strip() + "\n"

    return article_text.strip() + "\n\n" + meta_block + "\n"


def format_review_markdown(result: dict) -> str:
    lines = []

    lines.append("# 記事品質レビュー")
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
    lines.append("## 推奨マガジン")
    lines.append(str(result.get("recommended_magazine", "")))

    return "\n".join(lines)


def review_article(article_path: Path, output_dir: Path) -> dict:
    article_text = article_path.read_text(encoding="utf-8")
    prompt = load_prompt(article_text)

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
                "content": "あなたはnote記事の編集者です。必ずJSONのみで回答してください。",
            },
            {
                "role": "user",
                "content": prompt,
            },
        ],
        temperature=0.2,
    )

    content = response.choices[0].message.content or ""
    result = extract_json(content)

    total_score = int(result.get("total_score", 0))
    result["pass"] = total_score >= PASS_SCORE

    output_dir.mkdir(parents=True, exist_ok=True)

    (output_dir / "review.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    (output_dir / "review.md").write_text(
        format_review_markdown(result) + "\n",
        encoding="utf-8",
    )

    # article.md末尾のMETAをレビュー結果で更新
    updated_article = replace_or_append_meta(article_text, result)
    article_path.write_text(updated_article, encoding="utf-8")

    return result


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
