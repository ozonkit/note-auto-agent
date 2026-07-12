# note-auto-agent

note記事の企画・本文生成・品質レビュー・見出し画像生成・note下書き保存までを、GitHub Actions上で半自動化する個人用プロジェクトです。

> **このREADMEの目的**  
> 数か月後に不具合が起きても、処理の全体像、必要なSecrets、認証更新方法、よくある障害と復旧手順を思い出せる状態にすること。

---

## 1. このシステムがすること

1. 記事テーマを受け取る
2. 記事構成を生成する
3. note本文を生成する
4. AIで品質レビューする
5. 基準未達なら一度リライトし、再レビューする
6. 見出し画像の生成プロンプトを作る
7. Azureの画像生成モデルで見出し画像を作る
8. Playwrightでnoteエディタを開く
9. タイトル・本文・見出し画像を入力する
10. noteへ**下書き保存**する
11. `themes.csv` の状態を更新する

原則として、**自動公開までは行わない**設計です。

公開前に人が以下を確認します。

- 事実関係
- AIっぽい表現
- 個人情報や固有名詞
- METAブロックの削除
- タグ
- マガジン
- 無料／有料設定
- 見出し画像
- 公開日時

---

## 2. 全体フロー

```text
手動入力 または themes.csv
        │
        ▼
generate_article.py
        │
        ├─ plan.md
        ├─ article.md
        ├─ image_prompt.txt
        └─ run_log.txt
        │
        ▼
review_article.py
        │
        ├─ review.json
        ├─ review.md
        └─ article.md の META 更新
        │
        ├─ 合格 ───────────────┐
        │                      │
        └─ 不合格               │
             │                 │
             ▼                 │
        rewrite_article.py     │
             │                 │
             ▼                 │
        review_article.py      │
             │                 │
             └─────────────────┘
                       │
                       ▼
          generate_image_azure.py
                       │
                       ▼
             crop_note_cover.py
                       │
                       ▼
     NOTE_AUTH_JSON_BASE64 を auth.json に復元
                       │
                       ▼
          post_to_note_draft.py
                       │
                       ▼
             noteへ下書き保存
```

---

## 3. ディレクトリ構成

```text
note-auto-agent/
├─ .github/
│  └─ workflows/
│     └─ *.yml
├─ assets/
│  └─ images/
│     └─ {RUN_ID}/
│        └─ cover_raw.png
├─ drafts/
│  └─ generated/
│     └─ {RUN_ID}/
│        ├─ plan.md
│        ├─ article.md
│        ├─ image_prompt.txt
│        ├─ review.json
│        └─ review.md
├─ prompts/
│  ├─ article_planner.md
│  ├─ article_writer.md
│  ├─ article_quality_review.md
│  └─ image_prompt.md
├─ scripts/
│  ├─ generate_article.py
│  ├─ review_article.py
│  ├─ rewrite_article.py
│  ├─ generate_image_azure.py
│  ├─ crop_note_cover.py
│  ├─ post_to_note_draft.py
│  ├─ create_note_auth.py
│  └─ save_note_auth_from_chrome.py
├─ themes.csv
├─ requirements.txt
├─ README.md
├─ run_log.txt          # 実行時に生成。Git管理しない
├─ auth.json            # 実行時に復元。絶対にGit管理しない
├─ debug.png            # 障害調査用。Git管理しない
├─ debug.html           # 障害調査用。Git管理しない
└─ trace.zip            # 障害調査用。Git管理しない
```

`save_note_auth_from_chrome.py` は、通常ChromeへCDP接続して認証情報を保存する方式を採用した場合のみ存在します。

---

## 4. 実行モード

### 4.1 手動テーマモード

GitHub Actionsの実行画面で `theme` を入力した場合に使用します。

主な入力値：

- `THEME`
- `CATEGORY`
- `TARGET`
- `ANGLE`
- `TONE`
- `WORDS`

`THEME` が設定されている場合、`themes.csv` のキューは使用しません。

### 4.2 CSVキューモード

`THEME` が空の場合、`themes.csv` から対象を取得します。

基本的な列：

```csv
id,theme,category,target,angle,tone,words,status,run_id
1,noteを無理なく続ける方法,副業,note初心者,仕組み化,男性視点の自然体,1800,TODO,
```

列はコード側と一致させること。`tone` や `words` をCSV側から使用する場合は、GitHub Actionsのデフォルト入力値がCSV値を上書きしないよう注意します。

---

## 5. テーマのステータス

推奨する状態遷移：

```text
TODO
  ↓ 記事生成開始
DOING
  ├─ 失敗 → FAILED
  └─ note下書き保存成功 → DRAFTED
```

状態の意味：

| status | 意味 |
|---|---|
| `TODO` | 未処理 |
| `DOING` | 処理中 |
| `FAILED` | 生成・レビュー・投稿のどこかで失敗 |
| `DRAFTED` | noteへの下書き保存まで成功 |

過去コードには `GENERATED` が存在する場合があります。現行運用では、最終成功状態を `DRAFTED` に統一する方が分かりやすいです。

### 注意

最初の品質レビューに失敗した時点で一時的に `FAILED` になり、その後のリライト・再レビュー・下書き保存成功で `DRAFTED` に更新される場合があります。

---

## 6. RUN_IDと出力ファイル

1回の実行ごとに、次の形式で `RUN_ID` を発行します。

```text
YYYYMMDD-HHMMSS
```

例：

```text
20260712-082936
```

出力先：

```text
drafts/generated/20260712-082936/
assets/images/20260712-082936/
```

`run_log.txt` には、直近実行の情報をJSONで保存します。

例：

```json
{
  "run_id": "20260712-082936",
  "theme_id": "41",
  "theme": "note記事作成を無理なく続ける方法"
}
```

### 重要

`run_log.txt` は複数実行で上書きされる一時ファイルです。Git管理するとrebase競合の原因になるため、`.gitignore` に入れます。

---

## 7. 各スクリプトの役割

### `generate_article.py`

担当：

- 手動テーマまたは`themes.csv`の読込
- `TODO`を`DOING`へ変更
- 記事設計の生成
- 本文の生成
- 画像プロンプトの生成
- `run_log.txt`の出力

主な出力：

```text
plan.md
article.md
image_prompt.txt
run_log.txt
```

### `review_article.py`

担当：

- `article.md`の品質評価
- 点数と合否判定
- `review.json`と`review.md`の出力
- `article.md`末尾のMETA更新
- 不合格時のステータス更新

合格点：

```text
PASS_SCORE
```

コードのデフォルト値とGitHub Actions側の指定値が異なる可能性があるため、変更時は両方確認します。

### タグの出力形式

META内のタグは次の形式に統一します。

```text
タグ："note","習慣化","自動化","副業","アウトプット"
```

AIが以下のいずれで返しても正規化します。

```text
#note #習慣化
note,習慣化
["#note", "#習慣化"]
```

### `rewrite_article.py`

担当：

- 初回レビューで不合格になった記事の修正
- レビュー結果を参考に本文を再生成

原則として、無限リライトを避けるため自動リライトは1回までです。

### `generate_image_azure.py`

担当：

- `image_prompt.txt`を読み込む
- Azureの画像生成モデルへ送信する
- 見出し画像を保存する

主な出力：

```text
assets/images/{RUN_ID}/cover_raw.png
```

### `crop_note_cover.py`

担当：

- note見出し画像向けにサイズ・画角を調整する

出力ファイル名を変更した場合は、`post_to_note_draft.py`側の参照先も必ず変更します。

### `post_to_note_draft.py`

担当：

- `auth.json`を使ってnoteへログイン
- noteエディタを開く
- Markdownからタイトルと本文を分離
- 本文をnote向けのプレーンテキストに変換
- タイトル・本文・画像を入力
- 下書き保存
- 成功後、テーマを`DRAFTED`へ変更

現在の主要セレクタ例：

```python
textarea[placeholder="記事タイトル"]
div.ProseMirror[contenteditable='true']
button[aria-label="画像を追加"]
button:has-text("下書き保存")
```

note側の画面変更で最も壊れやすい部分です。

---

## 8. Markdownからnote本文への変換

`post_to_note_draft.py`では、Markdownを完全再現するのではなく、note上で崩れにくいプレーンテキストへ寄せます。

例：

```text
## 見出し
```

↓

```text
■ 見出し
```

```text
- 箇条書き
```

↓

```text
・箇条書き
```

### 既知の注意点

`##` と `###` を両方 `■` に変換すると、見出しが連続して不自然になる場合があります。将来的には階層ごとに記号を分けるか、隣接見出しを整理する処理を検討します。

---

## 9. METAブロック

記事末尾に、公開前確認用の情報を付けます。

```text
---META---
カテゴリ：副業・アウトプット
ターゲット：noteを継続したい人
角度：仕組み化・習慣化
有料化候補：True
想定価格：480〜980円
タグ："note","習慣化","自動化","副業","アウトプット"
レビュー：88点
推奨マガジン：note運用と生活改善の記録
有料化するなら：具体的な自動化テンプレート
---END---
```

**公開前にMETAブロックを本文から削除すること。**

---

## 10. 必要なGitHub Secrets

GitHubで以下に登録します。

```text
Repository
→ Settings
→ Secrets and variables
→ Actions
→ Repository secrets
```

### 記事生成

| Secret | 用途 |
|---|---|
| `AZURE_OPENAI_API_KEY` | Azure OpenAI認証 |
| `AZURE_OPENAI_ENDPOINT` | Azure OpenAIエンドポイント |
| `AZURE_OPENAI_DEPLOYMENT` | 記事生成・レビュー用デプロイ名 |

### 画像生成

| Secret | 用途 |
|---|---|
| `AZURE_OPENAI_IMAGE_ENDPOINT` | 画像生成エンドポイント |
| `AZURE_OPENAI_IMAGE_DEPLOYMENT` | 画像生成デプロイ名 |

### note認証

| Secret | 用途 |
|---|---|
| `NOTE_AUTH_JSON_BASE64` | Base64化したPlaywright認証状態 |

APIバージョンは、Secretsではなくworkflowの環境変数として指定している場合があります。

---

## 11. 主な環境変数

| 変数 | 用途 |
|---|---|
| `THEME` | 手動記事テーマ |
| `CATEGORY` | カテゴリ |
| `TARGET` | 想定読者 |
| `ANGLE` | 切り口 |
| `TONE` | 文体 |
| `WORDS` | 目安文字数 |
| `PASS_SCORE` | 品質レビュー合格点 |
| `RUN_ID` | 実行ID |
| `RUN_DIR` | 記事出力先 |
| `IMAGES_DIR` | 画像出力先 |
| `HEADLESS` | Playwrightのヘッドレス設定 |
| `TEST_MODE` | テスト実行用 |
| `MAI_WIDTH` | 生成画像の幅 |
| `MAI_HEIGHT` | 生成画像の高さ |
| `UPLOAD_COVER` | 見出し画像アップロード制御用 |

### `UPLOAD_COVER`の注意

現行の`post_to_note_draft.py`が`UPLOAD_COVER`を参照していない場合、workflowで`true`／`false`を変更しても動作は変わりません。

現在は、実質的に以下でアップロード可否が決まります。

```python
if cover_path.exists():
    upload_cover_image(...)
```

環境変数で制御したい場合は、Python側にも条件分岐を追加します。

---

## 12. GitHub Actionsからの実行

```text
GitHub
→ note-auto-agent
→ Actions
→ 対象workflow
→ Run workflow
```

### 手動テーマで実行

`記事テーマ`を入力して実行します。

### CSVキューで実行

`記事テーマ`を空欄にして実行します。

その場合、`themes.csv`の`TODO`行を使用します。

---

## 13. note認証情報の更新

noteのログインCookieには期限があります。

次のエラーが出たら、認証情報を更新します。

```text
RuntimeError: Not logged in. auth.json invalid.
```

### 方法A：PlaywrightのChromeからログイン

ローカルPCで実行：

```powershell
python .\scripts\create_note_auth.py
```

ブラウザでnoteへログインし、ターミナルへ戻ってEnterを押します。

生成先：

```text
.auth/auth.json
```

### 方法B：普通のChromeへ接続して保存

Playwrightで開いたChromeだけreCAPTCHAへ接続できず、普段のChromeではログインできる場合に使用します。

1. Chromeをリモートデバッグ付きで起動
2. そのChromeでnoteへログイン
3. `save_note_auth_from_chrome.py`を実行
4. 起動中Chromeの認証状態を`.auth/auth.json`へ保存

例：

```powershell
python .\scripts\save_note_auth_from_chrome.py
```

### Base64化

```powershell
$bytes = [System.IO.File]::ReadAllBytes(".\.auth\auth.json")
$base64 = [Convert]::ToBase64String($bytes)
$base64 | Set-Clipboard
```

GitHubの`NOTE_AUTH_JSON_BASE64`を更新します。

### 絶対にしないこと

- `auth.json`をGitへコミットする
- `auth.json`をArtifactへアップロードする
- Cookie内容をActionsログへ表示する
- Base64文字列をチャットやIssueへ貼る

Base64は暗号化ではありません。

---

## 14. `.gitignore`

推奨内容：

```gitignore
# 認証情報
auth.json
.auth/

# 実行時ファイル
run_log.txt

# デバッグ
debug.html
debug.png
debug_*.html
debug_*.png
trace.zip

# Python
__pycache__/
*.pyc
.venv/
```

### 追跡済みファイルを管理対象から外す

`.gitignore`へ追加するだけでは、すでに追跡済みのファイルは除外されません。

```bash
git rm --cached run_log.txt
git rm --cached auth.json
git add .gitignore
git commit -m "chore: ignore runtime and auth files"
```

---

## 15. Git競合を防ぐ

### 発生した事象

`run_log.txt`をコミットした状態で、別の実行がリモートの`main`を更新すると、rebase時に次の競合が発生します。

```text
CONFLICT (content): Merge conflict in run_log.txt
error: could not apply ...
```

### 対策

1. `run_log.txt`をGit管理から外す
2. `git add .`を使わず、保存対象を明示する
3. 同時実行を防ぐ

workflow上部の例：

```yaml
concurrency:
  group: note-auto-agent-main
  cancel-in-progress: false
```

コミット対象の例：

```bash
git add themes.csv
git add "drafts/generated/${RUN_ID}"
git add "assets/images/${RUN_ID}"
```

以下は追加しません。

```text
auth.json
run_log.txt
debug.png
debug.html
trace.zip
```

---

## 16. GitHub Actionsのストレージ対策

次の警告が来た場合：

```text
You have used 90% of the Actions storage
```

主な原因：

- `trace.zip`
- `debug.png`
- `debug.html`
- 生成画像
- 生成記事
- Artifactの長期保存
- 成功時も`if: always()`でアップロードしている

### 推奨

Artifactは失敗時のみ保存します。

```yaml
- name: Upload debug artifacts
  if: failure()
  uses: actions/upload-artifact@v4
  with:
    name: debug-${{ github.run_id }}
    retention-days: 3
    path: |
      debug.png
      debug.html
      trace.zip
```

**`auth.json`はArtifactへ含めないこと。**

成功時に生成記事を保存したい場合も、対象を`RUN_ID`配下に限定します。

---

## 17. よくあるエラーと対応

### 17.1 `Not logged in. auth.json invalid.`

原因：

- noteのCookie期限切れ
- Secretの更新漏れ
- Base64復元失敗
- 復元先と読込先のパス不一致

確認：

```bash
test -s auth.json
```

JSONとして読めるか確認：

```bash
python -c "import json; d=json.load(open('auth.json')); print(len(d.get('cookies', [])))"
```

対応：

- ローカルで`auth.json`を再生成
- `NOTE_AUTH_JSON_BASE64`を更新
- workflowの復元先と`AUTH_FILE`を統一

---

### 17.2 Playwright画面だけreCAPTCHAへ接続できない

症状：

```text
reCAPTCHAサービスに接続できませんでした
```

普通のChromeではログインできる場合：

- 自動起動Chromeと通常Chromeでネットワーク設定が異なる
- 社内プロキシやセキュリティ設定の影響

対応：

- 普通のChromeでログイン
- CDP接続方式で認証状態を保存
- reCAPTCHAの自動回避はしない

---

### 17.3 `No module named playwright`

原因：

- Playwright未インストール
- 仮想環境違い
- 社内プロキシでpipがPyPIへ到達できない

確認：

```powershell
python -c "from playwright.sync_api import sync_playwright; print('OK')"
```

社内プロキシが原因の場合：

- 許可された外部回線を使用
- 会社の正式なプロキシ設定を確認
- 別PCでwheelを取得してオフラインインストール
- インストール済みGoogle Chromeを`channel="chrome"`で使用

---

### 17.4 `No TODO or DOING theme found`

原因：

- `themes.csv`に処理対象がない
- statusのスペル違い
- 文字コードやヘッダー違い

対応：

```csv
status
TODO
```

を確認します。

---

### 17.5 品質レビューで停止する

症状：

```text
Article quality check failed
```

確認：

```text
drafts/generated/{RUN_ID}/review.md
drafts/generated/{RUN_ID}/review.json
```

確認項目：

- `PASS_SCORE`
- リライトが実行されたか
- 2回目レビューが成功したか
- `review_article.py`が初回失敗時にジョブ全体を止めていないか

---

### 17.6 見出し画像のアップロードに失敗する

原因：

- note側のDOM変更
- 画像追加ボタンの`aria-label`変更
- アップロードメニューの文言変更
- トリミングモーダルの構造変更
- 保存ボタンの活性化待ち不足

確認ファイル：

```text
debug.png
debug.html
trace.zip
```

修正候補：

```python
button[aria-label="画像を追加"]
.ReactModal__Overlay
button[name="保存"]
```

---

### 17.7 タイトルまたは本文入力に失敗する

note側UI変更の可能性があります。

確認するセレクタ：

```python
textarea[placeholder="記事タイトル"]
div.ProseMirror[contenteditable='true']
button:has-text("下書き保存")
```

Chromeの開発者ツールで現行DOMを確認し、ロケータを更新します。

---

### 17.8 Git push時にrebase競合する

症状：

```text
CONFLICT (content)
git rebase --continue
```

対応：

- `run_log.txt`を管理対象から外す
- workflowへ`concurrency`を追加
- 生成物のコミット対象を限定
- 同じテーマが複数実行されていないか確認

---

## 18. デバッグファイル

| ファイル | 用途 |
|---|---|
| `debug.png` | エラー時点の画面 |
| `debug.html` | エラー時点のDOM |
| `trace.zip` | Playwright操作履歴 |
| `review.json` | AIレビューの構造化結果 |
| `review.md` | 人間向けレビュー |
| `run_log.txt` | 直近RUN_ID・テーマ |

デバッグファイルは通常Git管理しません。

`trace.zip`は容量が大きいため、原則として失敗時のみ作成・保存します。

---

## 19. ローカル実行

### 仮想環境

```powershell
python -m venv .venv
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\.venv\Scripts\Activate.ps1
```

### 依存関係

```powershell
python -m pip install -r requirements.txt
python -m pip install playwright
```

インストール済みChromeを使用する場合、コード側を以下にします。

```python
browser = p.chromium.launch(
    headless=False,
    channel="chrome",
)
```

### 個別実行例

```powershell
python .\scripts\generate_article.py
python .\scripts\review_article.py
python .\scripts\rewrite_article.py
python .\scripts\generate_image_azure.py
python .\scripts\crop_note_cover.py
python .\scripts\post_to_note_draft.py
```

ローカルでは、必要な環境変数と`auth.json`を準備します。

---

## 20. セキュリティ

以下はリポジトリ、Artifact、Actionsログへ出さないこと。

- Azure OpenAI APIキー
- Azureエンドポイントの機密情報
- `auth.json`
- `NOTE_AUTH_JSON_BASE64`
- noteのCookie
- 個人情報を含む下書き
- 公開前の法的・家庭内資料

Secretsを変更した後は、古い値が残っていないか確認します。

---

## 21. 運用チェックリスト

### 実行前

- [ ] `themes.csv`の対象行が正しい
- [ ] `status`が`TODO`
- [ ] Azure関連Secretsが有効
- [ ] `NOTE_AUTH_JSON_BASE64`が有効
- [ ] Actionsストレージに余裕がある
- [ ] 同一workflowが実行中ではない

### 実行後

- [ ] GitHub Actionsが成功
- [ ] noteに下書きが作成された
- [ ] タイトルが正しい
- [ ] 本文の改行が崩れていない
- [ ] 見出し画像が入っている
- [ ] METAを削除した
- [ ] AIが作った事実を確認した
- [ ] タグを設定した
- [ ] マガジンを設定した
- [ ] 有料／無料範囲を確認した
- [ ] 公開日時を確認した
- [ ] `themes.csv`が`DRAFTED`になった

---

## 22. 変更時に一緒に確認するファイル

### 記事の文体を変える

```text
prompts/article_writer.md
prompts/article_planner.md
scripts/rewrite_article.py
```

### レビュー基準を変える

```text
prompts/article_quality_review.md
scripts/review_article.py
.github/workflows/*.yml
```

### タグ形式を変える

```text
scripts/review_article.py
```

### 画像サイズ・構図を変える

```text
prompts/image_prompt.md
scripts/generate_image_azure.py
scripts/crop_note_cover.py
scripts/post_to_note_draft.py
```

### note投稿画面が変わった

```text
scripts/post_to_note_draft.py
debug.html
debug.png
trace.zip
```

### テーマ管理を変える

```text
themes.csv
scripts/generate_article.py
scripts/review_article.py
scripts/post_to_note_draft.py
```

### Gitへの保存方法を変える

```text
.github/workflows/*.yml
.gitignore
```

---

## 23. 現時点の既知課題

- [ ] `PASS_SCORE`の設定場所を1か所へ統一する
- [ ] `TONE`と`WORDS`の手動入力・CSV優先順位を明確にする
- [ ] `UPLOAD_COVER`をPython側で実際に参照する
- [ ] `run_log.txt`をGit管理から完全に外す
- [ ] `auth.json`をArtifact対象から完全に外す
- [ ] Artifactを失敗時のみ保存する
- [ ] Artifactの保持期間を短くする
- [ ] workflowへ`concurrency`を追加する
- [ ] `##`と`###`のnote上での表示を分ける
- [ ] noteセレクタ変更時のテスト手順を作る
- [ ] 生成済みRUN_IDだけを再投稿する手動workflowを作る
- [ ] CSV更新とGit push競合への対策を強化する

---

## 24. 不具合発生時の調査順序

1. GitHub Actionsの失敗ステップを確認
2. `RUN_ID`を確認
3. `review.md`またはエラーログを確認
4. `debug.png`を確認
5. `debug.html`でnote側DOMを確認
6. 必要な場合だけ`trace.zip`を確認
7. `auth.json`の期限切れを確認
8. Secrets名・復元先を確認
9. `themes.csv`のstatusを確認
10. Git競合がないか確認

---

## 25. README更新ルール

仕様変更時は、コードだけでなくこのREADMEも更新します。

最低限更新する箇所：

- 全体フロー
- 必要なSecrets
- 環境変数
- ステータス遷移
- 出力ファイル
- 認証更新方法
- 既知課題
- 更新履歴

---

## 26. 更新履歴

| 日付 | 内容 |
|---|---|
| 2026-07-12 | 初版作成。記事生成、品質レビュー、画像生成、note下書き保存、認証更新、Git競合、Artifact容量問題を整理 |

---

## 27. 最後に

このプロジェクトは、記事を完全自動で公開するためではなく、**記事作成の重い部分を仕組みに任せ、人が最後の品質と公開判断を担うためのもの**です。

不具合が起きた時は、まず以下を確認します。

```text
1. auth.json
2. note側の画面変更
3. RUN_IDと出力パス
4. themes.csvのstatus
5. Git競合
6. Artifact容量
```
