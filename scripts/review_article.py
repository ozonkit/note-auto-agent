import csv
import json
import os
import re
from pathlib import Path

from openai import AzureOpenAI


# =========================
# パス・設定
# =========================

ROOT = Path(__file__).resolve().parents[1]
REVIEW_PROMPT_PATH = ROOT / "prompts" / "article_quality_review.md"
THEMES_CSV = ROOT / "themes.csv"
RUN_LOG_PATH = ROOT / "run_log.txt"

PASS_SCORE = int(os.getenv("PASS_SCORE", "80"))


# =========================
# プロンプト・JSON処理
# =========================

def load_prompt(article_text: str) -> str:
    if not REVIEW_PROMPT_PATH.exists():
        raise FileNotFoundError(
            f"Review prompt not found: {REVIEW_PROMPT_PATH}"
        )

    template = REVIEW_PROMPT_PATH.read_text(encoding="utf-8")
    return template.replace("{{ARTICLE}}", article_text)


def extract_json(text: str) -> dict:
    """
    LLMがJSONの前後に余計な文字を返した場合に、
    最初の { から最後の } までを抜き出す。
    """
    start = text.find("{")
    end = text.rfind("}")

    if start == -1 or end == -1 or end < start:
        raise ValueError("JSON object not found in LLM response")

    return json.loads(text[start:end + 1])


# =========================
# タグ整形
# =========================

def format_tags(tags) -> str:
    """
    AIが返したタグを、次の形式に正規化する。

    "note","習慣化","自動化","副業","アウトプット"

    対応する入力例:
    - ["#note", "#習慣化"]
    - ["note", "習慣化"]
    - "#note #習慣化"
    - "#note, #習慣化"
    - '"note","習慣化"'
    """
    if not tags:
        return ""

    if isinstance(tags, list):
        raw_tags = tags
    else:
        raw_tags = re.split(r"[\s,、]+", str(tags))

    normalized_tags = []
    seen = set()

    for tag in raw_tags:
        cleaned = str(tag).strip()

        # 前後の引用符、カンマ、#を除去
        cleaned = cleaned.strip("\"'“”")
        cleaned = cleaned.strip(",、")
        cleaned = cleaned.lstrip("#")
        cleaned = cleaned.strip()

        if not cleaned:
            continue

        # タグ内にダブルクォートが入った場合は除去
        cleaned = cleaned.replace('"', "")

        if cleaned not in seen:
            normalized_tags.append(cleaned)
            seen.add(cleaned)

    return ",".join(f'"{tag}"' for tag in normalized_tags)


# =========================
# META処理
# =========================

def build_meta_block(result: dict, existing_article: str) -> str:
    paid = result.get("paid_potential", {})

    tags = result.get("recommended_tags", [])
    tags_text = format_tags(tags)

    def pick(label: str, default: str = "") -> str:
        """
        既存のMETAブロックから値を取得する。
        """
        pattern = rf"^{re.escape(label)}：(.*)$"
        match = re.search(
            pattern,
            existing_article,
            flags=re.MULTILINE,
        )

        return match.group(1).strip() if match else default

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
    """
    既存METAがあれば置き換え、なければ記事末尾に追加する。
    """
    meta_block = build_meta_block(result, article_text)
    pattern = r"---META---.*?---END---"

    if re.search(pattern, article_text, flags=re.DOTALL):
        updated = re.sub(
            pattern,
            meta_block,
            article_text,
            flags=re.DOTALL,
        )
        return updated.strip() + "\n"

    return article_text.strip() + "\n\n" + meta_block + "\n"


# =========================
# レビューMarkdown
# =========================

def format_review_markdown(result: dict) -> str:
    lines = [
        "# 記事品質レビュー",
        "",
        f"総合スコア：{result.get('total_score', 0)}点",
        f"合格判定：{'合格' if result.get('pass') else '要改善'}",
        "",
        "## 良い点",
    ]

    strengths = result.get("strengths", [])
    if strengths:
        for item in strengths:
            lines.append(f"- {item}")
    else:
        lines.append("- 特になし")

    lines.extend([
        "",
        "## 弱い点",
    ])

    weaknesses = result.get("weaknesses", [])
    if weaknesses:
        for item in weaknesses:
            lines.append(f"- {item}")
    else:
        lines.append("- 特になし")

    lines.extend([
        "",
        "## 改善案",
    ])

    improvements = result.get("improvements", [])
    if improvements:
        for item in improvements:
            lines.append(f"- {item}")
    else:
        lines.append("- 特になし")

    paid = result.get("paid_potential", {})

    lines.extend([
        "",
        "## 有料化判定",
        f"- 有料化候補：{paid.get('is_paid_candidate')}",
        f"- 理由：{paid.get('reason', '')}",
        f"- 有料化するなら：{paid.get('suggested_paid_section', '')}",
        f"- 想定価格：{paid.get('suggested_price_yen', '')}",
        "",
        "## 推奨タグ",
    ])

    recommended_tags = result.get("recommended_tags", [])

    if recommended_tags:
        if isinstance(recommended_tags, list):
            for tag in recommended_tags:
                lines.append(f"- {str(tag).lstrip('#')}")
        else:
            lines.append(f"- {recommended_tags}")
    else:
        lines.append("- 特になし")

    lines.extend([
        "",
        "## 推奨マガジン",
        str(result.get("recommended_magazine", "")),
    ])

    return "\n".join(lines)


# =========================
# 記事レビュー
# =========================

def review_article(article_path: Path, output_dir: Path) -> dict:
    article_text = article_path.read_text(encoding="utf-8")
    prompt = load_prompt(article_text)

    client = AzureOpenAI(
        api_key=os.environ["AZURE_OPENAI_API_KEY"],
        azure_endpoint=os.environ["AZURE_OPENAI_ENDPOINT"],
        api_version=os.getenv(
            "AZURE_OPENAI_API_VERSION",
            "2024-02-15-preview",
        ),
    )

    response = client.chat.completions.create(
        model=os.environ["AZURE_OPENAI_DEPLOYMENT"],
        messages=[
            {
                "role": "system",
                "content": (
                    "あなたはnote記事の編集者です。"
                    "必ず有効なJSONのみで回答してください。"
                ),
            },
            {
                "role": "user",
                "content": prompt,
            },
        ],
        temperature=0.2,
    )

    content = response.choices[0].message.content or ""

    if not content.strip():
        raise RuntimeError("Azure OpenAI returned empty review content")

    result = extract_json(content)

    try:
        total_score = int(result.get("total_score", 0))
    except (TypeError, ValueError):
        total_score = 0

    result["total_score"] = total_score
    result["pass"] = total_score >= PASS_SCORE

    output_dir.mkdir(parents=True, exist_ok=True)

    review_json_path = output_dir / "review.json"
    review_md_path = output_dir / "review.md"

    review_json_path.write_text(
        json.dumps(
            result,
            ensure_ascii=False,
            indent=2,
        ) + "\n",
        encoding="utf-8",
    )

    review_md_path.write_text(
        format_review_markdown(result) + "\n",
        encoding="utf-8",
    )

    # article.md末尾のMETAをレビュー結果で更新
    updated_article = replace_or_append_meta(
        article_text,
        result,
    )

    article_path.write_text(
        updated_article,
        encoding="utf-8",
    )

    return result


# =========================
# themes.csv更新
# =========================

def update_theme_status(
    theme_id: str | None,
    new_status: str,
    run_id: str | None = None,
) -> None:
    if not theme_id:
        print(
            "WARNING: theme_id is empty. "
            "themes.csv status was not updated."
        )
        return

    if not THEMES_CSV.exists():
        print(
            f"WARNING: themes.csv not found: {THEMES_CSV}"
        )
        return

    with THEMES_CSV.open(
        "r",
        encoding="utf-8-sig",
        newline="",
    ) as file:
        reader = csv.DictReader(file)
        fieldnames = reader.fieldnames
        rows = list(reader)

    if not fieldnames:
        raise RuntimeError("themes.csv has no header")

    updated = False

    for row in rows:
        if str(row.get("id", "")) == str(theme_id):
            row["status"] = new_status

            if "run_id" in fieldnames and run_id:
                row["run_id"] = run_id

            updated = True
            break

    if not updated:
        print(
            f"WARNING: theme_id={theme_id} "
            "was not found in themes.csv"
        )
        return

    with THEMES_CSV.open(
        "w",
        encoding="utf-8",
        newline="",
    ) as file:
        writer = csv.DictWriter(
            file,
            fieldnames=fieldnames,
        )
        writer.writeheader()
        writer.writerows(rows)

    print(
        f"Theme status updated: "
        f"id={theme_id}, status={new_status}"
    )


# =========================
# run_log取得
# =========================

def read_run_meta() -> tuple[str | None, str | None]:
    if not RUN_LOG_PATH.exists():
        raise RuntimeError(
            f"run_log.txt not found: {RUN_LOG_PATH}"
        )

    data = json.loads(
        RUN_LOG_PATH.read_text(encoding="utf-8")
    )

    return data.get("run_id"), data.get("theme_id")


# =========================
# メイン処理
# =========================

def main():
    log_run_id, theme_id = read_run_meta()

    # GitHub Actionsから渡されたRUN_IDを優先
    run_id = os.getenv("RUN_ID") or log_run_id

    if not run_id:
        raise RuntimeError(
            "run_id was not found in environment variables "
            "or run_log.txt"
        )

    default_run_dir = ROOT / "drafts" / "generated" / run_id

    run_dir = Path(
        os.getenv(
            "RUN_DIR",
            str(default_run_dir),
        )
    )

    article_path = run_dir / "article.md"

    if not article_path.exists():
        raise SystemExit(
            f"article.md not found: {article_path}"
        )

    result = review_article(
        article_path,
        run_dir,
    )

    print(
        json.dumps(
            result,
            ensure_ascii=False,
            indent=2,
        )
    )

    if not result["pass"]:
        update_theme_status(
            theme_id,
            "FAILED",
            run_id,
        )

        raise SystemExit(
            "Article quality check failed. "
            f"score={result.get('total_score')}, "
            f"pass_score={PASS_SCORE}"
        )


if __name__ == "__main__":
    main()
