# note-auto-agent
スマホでテーマ入力
↓
github actions
↓
llm api（gemini, claude, openai）
↓
記事設計・草案生成
↓
画像プロンプト生成
↓
画像生成
↓
md保存
↓
playwrightでnote下書き
↓
失敗時はログスクショ保存

適宜、github copilot cliで、cicdを対応可否調査

## プロジェクト構成

note-auto-agent/
├─ .github/
│  └─ workflows/
│     └─ note-draft.yml
├─ prompts/
│  ├─ article_planner.md
│  └─ article_writer.md
├─ scripts/
│  └─ generate_article.py
├─ drafts/
│  └─ generated/
├─ requirements.txt
└─ README.md

## 使い方

1. 依存パッケージをインストール

```bash
python -m pip install --upgrade pip
pip install -r requirements.txt
```

2. 環境変数を設定

```bash
set OPENAI_API_KEY=your_api_key
```

3. 記事を生成

```bash
python scripts/generate_article.py --theme "記事のテーマ"
```

生成された下書きは `drafts/generated/` に保存されます。
