import os
import json
import csv
from datetime import datetime
from pathlib import Path
from openai import OpenAI

ROOT = Path(__file__).resolve().parents[1]
PROMPTS = ROOT / "prompts"
OUTDIR = ROOT / "drafts" / "generated"
THEMES_CSV = ROOT / "themes.csv"


# =========================
# 共通処理
# =========================

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


# =========================
# テーマ管理
# =========================

def read_themes() -> list[dict]:
    if not THEMES_CSV.exists():
        raise FileNotFoundError(f"themes.csv not found: {THEMES_CSV}")

    with THEMES_CSV.open("r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def write_themes(rows: list[dict]) -> None:
    if not rows:
        return

    fieldnames = list(rows[0].keys())

    with THEMES_CSV.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def get_next_theme_from_queue() -> tuple[dict, int]:
    rows = read_themes()

    # ① TODO優先
    for idx, row in enumerate(rows):
        if row.get("status", "").upper() == "TODO":
            row["status"] = "DOING"
            write_themes(rows)
            return row, idx

    # ② DOINGをリトライ（条件付き）
    for idx, row in enumerate(rows):
        if row.get("status", "").upper() == "DOING":
            return row, idx

    raise RuntimeError("No TODO or DOING theme found")


def update_theme_status(theme_id: str | None, new_status: str, run_id: str | None = None) -> None:
    if not theme_id or not THEMES_CSV.exists():
        return

    rows = read_themes()

    for row in rows:
        if str(row.get("id")) == str(theme_id):
            row["status"] = new_status
            if "run_id" in row and run_id:
                row["run_id"] = run_id
            break

    write_themes(rows)


# =========================
# META埋め込み
# =========================

def append_meta(article: str, meta: dict) -> str:
    meta_block = f"""

---META---
カテゴリ：{meta.get('category','')}
ターゲット：{meta.get('target','')}
角度：{meta.get('angle','')}
有料化候補：未評価
想定価格：未定
タグ：
レビュー：未評価
---END---
"""
    return article.strip() + "\n" + meta_block


# =========================
# メイン処理
# =========================

def main():
    tone = os.environ.get("TONE", "note向け、自然体")
    words = os.environ.get("WORDS", "1800")

    queue_mode = False
    theme_row = None
    theme_id = None

    if os.environ.get("THEME"):
        theme = os.environ["THEME"]
        category = os.environ.get("CATEGORY", "")
        target = os.environ.get("TARGET", "")
        angle = os.environ.get("ANGLE", "")
    else:
        queue_mode = True
        theme_row, _ = get_next_theme_from_queue()

        theme_id = theme_row.get("id")
        theme = theme_row.get("theme", "")
        category = theme_row.get("category", "")
        target = theme_row.get("target", "")
        angle = theme_row.get("angle", "")

        if not theme:
            raise RuntimeError("theme is empty")

    client = OpenAI(
        api_key=os.environ["AZURE_OPENAI_API_KEY"],
        base_url=f"{os.environ['AZURE_OPENAI_ENDPOINT'].rstrip('/')}/openai/v1/",
    )

    deployment = os.environ["AZURE_OPENAI_DEPLOYMENT"]

    run_id = datetime.now().strftime("%Y%m%d-%H%M%S")
    run_dir = OUTDIR / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    try:
        # ===== 設計 =====
        planner_prompt = load_prompt(
            PROMPTS / "article_planner.md",
            THEME=theme,
            TONE=tone,
            CATEGORY=category,
            TARGET=target,
            ANGLE=angle,
        )

        plan = client.responses.create(
            model=deployment,
            input=planner_prompt,
        ).output_text.strip()

        (run_dir / "plan.md").write_text(plan + "\n", encoding="utf-8")

        # ===== 本文 =====
        writer_prompt = load_prompt(
            PROMPTS / "article_writer.md",
            WORDS=words,
            TONE=tone,
            CATEGORY=category,
            TARGET=target,
            ANGLE=angle,
        )

        article = client.responses.create(
            model=deployment,
            input=f"{plan}\n\n{writer_prompt}",
        ).output_text.strip()

        # 👇 META追加
        article = append_meta(article, {
            "category": category,
            "target": target,
            "angle": angle,
        })

        (run_dir / "article.md").write_text(article + "\n", encoding="utf-8")

        # ===== 画像プロンプト =====
        image_prompt_template = safe_read_text(PROMPTS / "image_prompt.md")

        image_prompt_text = client.responses.create(
            model=deployment,
            input=f"{image_prompt_template}\n\n{article}",
        ).output_text.strip()

        (run_dir / "image_prompt.txt").write_text(
            image_prompt_text + "\n",
            encoding="utf-8",
        )

        # ===== ログ =====
        (ROOT / "run_log.txt").write_text(
            json.dumps(
                {
                    "run_id": run_id,
                    "theme_id": theme_id,
                    "theme": theme,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

        # if queue_mode:
        #     update_theme_status(theme_id, "GENERATED", run_id)

        print("OK:", run_dir)

    except Exception:
        if queue_mode:
            update_theme_status(theme_id, "FAILED", run_id)
        raise


if __name__ == "__main__":
    main()
