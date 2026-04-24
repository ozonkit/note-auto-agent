from pathlib import Path
from PIL import Image

def center_crop(img, target_w, target_h):
    w, h = img.size
    left = (w - target_w) // 2
    top = (h - target_h) // 2
    return img.crop((left, top, left + target_w, top + target_h))

def main():
    run_id = Path("assets/images").iterdir().__next__().name
    base = Path("assets/images") / run_id

    raw = Image.open(base / "cover_raw.png")

    img_1920 = center_crop(raw, 1920, 324)
    img_1920.save(base / "cover_1920x324.png")

    img_1280 = img_1920.resize((1280, 210), Image.LANCZOS)
    img_1280.save(base / "cover_1280x210.png")

    print("[OK] note cover images created")

if __name__ == "__main__":
    main()
