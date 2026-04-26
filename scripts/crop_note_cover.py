from pathlib import Path

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

    # ✅ 何もしない（そのまま使う）
    print("[OK] cover_raw.png will be used as note eyecatch:", raw_path)

if __name__ == "__main__":
    main()
