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

    for idx, row in enumerate(rows):
        if row.get("status", "").upper() == "TODO":
            row["status"] = "DOING"
            write_themes(rows)
            return row, idx

    raise RuntimeError("No TODO theme found in themes.csv")


def update_theme_status(theme_id: str | None, new_status: str, run_id: str | None = None) -> None:
    if not theme_id or not THEMES_CSV.exists():
        return

    rows = read_themes()
    changed = False

    for row in rows:
        if str(row.get("id")) == str(theme_id):
            row["status"] = new_status
            if "run_id" in row and run_id:
                row["run_id"] = run_id
            changed = True
            break

    if changed:
        write_themes(rows)


def main():
    tone = os.environ.get("TONE", "note向け、自然体")
    words = os.environ.get("WORDS", "1800")

    queue_mode = False
    theme_row = None
    theme_id = None

    # THEMEがあれば手動入力を優先
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
            raise RuntimeError("theme is empty in themes.csv")

    client = OpenAI(
        api_key=os.environ["AZURE_OPENAI_API_KEY"],
        base_url=f"{os.environ['AZURE_OPENAI_ENDPOINT'].rstrip('/')}/openai/v1/",
    )

    deployment = os.environ["AZURE_OPENAI_DEPLOYMENT"]

    run_id = datetime.now().strftime("%Y%m%d-%H%M%S")
    run_dir = OUTDIR / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    try:
        # 1) 記事設計
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

        # 2) 本文生成
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
            input=(
                f"## 記事テーマ\n{theme}\n\n"
                f"## カテゴリ\n{category}\n\n"
                f"## 想定読者\n{target}\n\n"
                f"## 切り口\n{angle}\n\n"
                f"## 設計\n{plan}\n\n"
                f"{writer_prompt}"
            ),
        ).output_text.strip()

        (run_dir / "article.md").write_text(article + "\n", encoding="utf-8")

        # 3) 画像プロンプト生成
        image_prompt_template = safe_read_text(PROMPTS / "image_prompt.md")
        if image_prompt_template is None:
            image_prompt_template = (
                "あなたはnoteの見出し画像用の画像プロンプト作成者です。\n"
                "記事内容を読み、画像生成モデルに渡す短いプロンプトを作ってください。\n\n"
                "条件:\n"
                "- 横長のnote見出し画像\n"
                "- 文字なし\n"
                "- 人物なし\n"
                "- 低彩度\n"
                "- シンプル\n\n"
                "出力:\n"
                "1行目: 画像プロンプト\n"
                "2行目: ネガティブプロンプト\n"
                "3行目: スタイル\n"
                "4行目: 画角\n"
            )

        image_prompt_text = client.responses.create(
            model=deployment,
            input=(
                f"{image_prompt_template}\n\n"
                f"---\n"
                f"# 記事テーマ\n{theme}\n\n"
                f"# カテゴリ\n{category}\n\n"
                f"# 想定読者\n{target}\n\n"
                f"# 切り口\n{angle}\n\n"
                f"# 記事本文\n{article}\n"
            ),
        ).output_text.strip()

        (run_dir / "image_prompt.txt").write_text(
            image_prompt_text + "\n",
            encoding="utf-8",
        )

        # run_log
        (ROOT / "run_log.txt").write_text(
            json.dumps(
                {
                    "run_id": run_id,
                    "deployment": deployment,
                    "queue_mode": queue_mode,
                    "theme_id": theme_id,
                    "theme": theme,
                    "category": category,
                    "target": target,
                    "angle": angle,
                    "tone": tone,
                    "words": words,
                    "paths": {
                        "run_dir": str(run_dir.relative_to(ROOT)),
                        "plan_md": str((run_dir / "plan.md").relative_to(ROOT)),
                        "article_md": str((run_dir / "article.md").relative_to(ROOT)),
                        "image_prompt_txt": str((run_dir / "image_prompt.txt").relative_to(ROOT)),
                    },
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )

        # 生成完了時点では DONE ではなく GENERATED にする
        # note投稿まで成功したら別スクリプト側で DONE にするのが理想
        if queue_mode:
            update_theme_status(theme_id, "GENERATED", run_id)

        print("OK:", run_dir)

    except Exception:
        if queue_mode:
            update_theme_status(theme_id, "FAILED", run_id)
        raise


if __name__ == "__main__":
    main()
