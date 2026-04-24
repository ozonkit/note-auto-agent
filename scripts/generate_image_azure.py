import os
import base64
from pathlib import Path
from openai import OpenAI

ROOT = Path(__file__).resolve().parents[1]

def main():
    run_dir = Path(os.environ["RUN_DIR"])
    prompt_file = run_dir / "image_prompt.txt"

    if not prompt_file.exists():
        raise SystemExit("image_prompt.txt not found")

    prompt = prompt_file.read_text(encoding="utf-8").strip()

    out_dir = ROOT / "assets" / "images" / run_dir.name
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "cover_raw.png"

    # ✅ MAI-Image-2e 用 endpoint を使う
    client = OpenAI(
        api_key=os.environ["AZURE_OPENAI_API_KEY"],
        base_url=f"{os.environ['AZURE_OPENAI_IMAGE_ENDPOINT'].rstrip('/')}/openai/v1/"
    )

    result = client.images.generate(
        model=os.environ["AZURE_OPENAI_IMAGE_DEPLOYMENT"],
        prompt=prompt,
        size="1920x640"   # 3:1（後でトリミング）
    )

    img_b64 = result.data[0].b64_json
    out_path.write_bytes(base64.b64decode(img_b64))

    print("[OK] RAW image saved:", out_path)

if __name__ == "__main__":
    main()
