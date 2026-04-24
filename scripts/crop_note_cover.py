from pathlib import Path
from PIL import Image

TARGET_W1, TARGET_H1 = 1920, 324  # 高品質
TARGET_W2, TARGET_H2 = 1280, 210  # 推奨

def crop_to_aspect_center(img, aspect_w, aspect_h):
    w, h = img.size
    target_ratio = aspect_w / aspect_h
    current_ratio = w / h

    if current_ratio > target_ratio:
        # 横が長い → 横を切る
        new_w = int(h * target_ratio)
        left = (w - new_w) // 2
        box = (left, 0, left + new_w, h)
    else:
        # 縦が長い → 縦を切る
        new_h = int(w / target_ratio)
        top = (h - new_h) // 2
        box = (0, top, w, top + new_h)

    return img.crop(box)

def main():
    # assets/images/{run_id}/cover_raw.png を探す
    images_root = Path("assets/images")
    run_dirs = sorted([p for p in images_root.glob("*") if p.is_dir()], reverse=True)
    if not run_dirs:
        raise SystemExit("No assets/images/{run_id} directory found")

    base = run_dirs[0]
    raw_path = base / "cover_raw.png"
    if not raw_path.exists():
        raise SystemExit(f"cover_raw.png not found: {raw_path}")

    raw = Image.open(raw_path).convert("RGB")

    # 1) note比率に合わせて中心トリミング（約 5.93:1）
    cropped = crop_to_aspect_center(raw, TARGET_W1, TARGET_H1)

    # 2) 高品質へリサイズ
    img_1920 = cropped.resize((TARGET_W1, TARGET_H1), Image.LANCZOS)
    img_1920.save(base / "cover_1920x324.png")

    # 3) 推奨へリサイズ
    img_1280 = img_1920.resize((TARGET_W2, TARGET_H2), Image.LANCZOS)
    img_1280.save(base / "cover_1280x210.png")

    print("[OK] note cover images created:", base)

if __name__ == "__main__":
    main()
