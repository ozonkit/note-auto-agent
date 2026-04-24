import os
import base64
from pathlib import Path
import requests

ROOT = Path(__file__).resolve().parents[1]

def main():
    run_dir = Path(os.environ["RUN_DIR"])
    prompt_file = run_dir / "image_prompt.txt"
    if not prompt_file.exists():
        raise SystemExit(f"image_prompt.txt not found: {prompt_file}")

    # 1行目だけ使う（あなたの image_prompt.txt が4行構成でもOK）
    prompt_lines = prompt_file.read_text(encoding="utf-8").splitlines()
    prompt = prompt_lines[0].strip() if prompt_lines else ""
    if not prompt:
        raise SystemExit("Empty image prompt")

    out_dir = ROOT / "assets" / "images" / run_dir.name
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "cover_raw.png"

    endpoint = os.environ["AZURE_OPENAI_IMAGE_ENDPOINT"].rstrip("/")  # 例: https://xxx.services.ai.azure.com
    api_key = os.environ["AZURE_OPENAI_API_KEY"]
    deployment = os.environ["AZURE_OPENAI_IMAGE_DEPLOYMENT"]

    # ✅ MAI image generation API endpoint
    url = f"{endpoint}/mai/v1/images/generations"  # ←これが正しい [1](https://learn.microsoft.com/ja-jp/azure/foundry/foundry-models/how-to/use-foundry-models-mai)

    # ✅ MAIのサイズ制約：width,height>=768 & width*height<=1,048,576 [1](https://learn.microsoft.com/ja-jp/azure/foundry/foundry-models/how-to/use-foundry-models-mai)
    width = int(os.environ.get("MAI_WIDTH", "1365"))
    height = int(os.environ.get("MAI_HEIGHT", "768"))
    if width < 768 or height < 768 or width * height > 1048576:
        raise SystemExit(f"Invalid size for MAI: {width}x{height} (min 768, max pixels 1,048,576)")

    payload = {
        "model": deployment,   # ← model は「デプロイ名」 [1](https://learn.microsoft.com/ja-jp/azure/foundry/foundry-models/how-to/use-foundry-models-mai)
        "prompt": prompt,
        "width": width,
        "height": height
    }

    resp = requests.post(
        url,
        headers={
            "Content-Type": "application/json",
            "api-key": api_key,  # APIキー認証 [1](https://learn.microsoft.com/ja-jp/azure/foundry/foundry-models/how-to/use-foundry-models-mai)
        },
        json=payload,
        timeout=180
    )
    resp.raise_for_status()
    result = resp.json()

    data = result.get("data", [])
    if not data or "b64_json" not in data[0]:
        raise SystemExit(f"Unexpected response format: {result}")

    out_path.write_bytes(base64.b64decode(data[0]["b64_json"]))
    print(f"[OK] RAW image saved: {out_path} ({width}x{height})")

if __name__ == "__main__":
    main()
