# AGENTS.md

このリポジトリでの Git 運用手順を固定する。
目的は「コミット、push、レビュー確認、マージ、pull/prune、branch delete」を毎回同じ手順で正確に実行すること。

## 黄金律（must）

1. **推測しない** — コードや既存ドキュメントで確認できないことは事実として書かない・変えない。不明点は「To verify」として残すか、ユーザーに確認する。
2. **変更は最小限・安全に** — 必要な箇所だけ変える。依頼されていない広範なリファクタをしない。
3. **秘密情報を出力しない** — `.env` の値・API キー・認証情報は表示・ログ出力・コミットのいずれもしない。

## 0. 基本ルール

- `main` へ直接コミットしない。必ず feature ブランチで作業する。
- 1 PR = 1 目的。無関係な差分は混ぜない。
- 変更前後で `git status --short` を確認する。
- PRマージ前に `git status --short` を確認し、未コミット差分が残っていないことを必ず確認する。
- Issue はタイトルだけで「何の話か」が分かるように書く（例: `feat(scope): ...`, `fix(scope): ...`）。
- `gh issue create` / `gh pr create` で複数行本文を渡すときは `--body-file` を使う。
- `.env` は絶対にコミットしない。`.env.example` のみコミット対象。
- コード変更では、リポジトリに定義済みの lint/test コマンドから変更範囲に必要なものを実行する。確認のためだけに依存を追加しない。

## Task Request Format

- 新しい依頼は、可能な限り先頭に次のヘッダー形式を付ける。

```text
[repo:market-info-api] [type:<report|fix|review|investigation|docs>] [target:<artifact_or_scope>] [action:<specific_work>]
```

## 1. 作業開始

```bash
git fetch --prune
git switch main
git merge --ff-only origin/main
git switch -c feature/<topic>
git status --short
```

## 2. 実装と確認

```bash
# 実装後、下記の品質ゲートに応じて必要なコマンドだけ実行する
git status --short
```

### リスク別品質ゲート（must）

変更の影響と可逆性で Tier を決める。迷った場合は1段階上を使う。既存のCIやリポ固有ルールがより厳しい場合はそちらを優先する。

| Tier | 変更例 | 必須確認 | AIレビュー / UAT |
|---|---|---|---|
| 0 非実行変更 | docs、コメント、文言、設定例 | diff、必要な構文・リンク確認 | 原則不要 |
| 1 低リスク | 局所的な内部ロジック、機械的変更 | 対象lint・対象テスト | 挙動変更時のみ簡易確認 |
| 2 中リスク | API挙動、定期処理、外部入出力 | 対象lint・影響範囲テスト・必要なbuild | 独立レビュー1回、変更した挙動のUAT |
| 3 高リスク | 認証、データ移行、公開、セキュリティ | 関連フルスイート、build、ロールバック確認 | 高強度レビュー、UAT/リリース確認必須 |

- バグ修正には原則として再発防止テストを付ける。新機能の異常系・境界値は、実装に存在するリスクに対応して追加する。
- API契約や外部入出力の変更はTier 2以上として扱う。
- 低リスクで可逆な変更に、無関係な全テスト・build・新規依存導入を追加しない。

### 動作確認・UAT

- Tier 2以上でAPI利用者が観測する挙動を追加・変更した場合、操作またはリクエスト、入力、期待結果、異常時の挙動、確認環境をPR本文または該当UAT文書に記載する。
- 実施結果は恒久手順書へ書き込まず、PR本文に残す。

## 3. コミット

```bash
git branch --show-current
# `main` と表示されたらコミット禁止。feature ブランチへ切り直してからやり直す。
git add <file1> <file2>
git commit -m "feat(scope): summary"
git status --short
```

## 4. push

```bash
git push -u origin feature/<topic>
```

## 5. PR 作成

```bash
gh pr create --base main --head feature/<topic> --title "<title>" --body-file <tmpfile.md>
```

PR 本文に必ず記載する項目:

- 概要
- 変更内容
- 確認項目（lint/動作確認）
- 関連 Issue（例: `Closes #xx`）

## 6. レビュー確認と対応

```bash
# Tier 2以上は Codex CLI review を1回実施する
codex review --base main
gh pr view <PR番号> --comments
```

- P1/P0 指摘は優先対応する。
- 修正後は同じブランチで再コミットし push する。
- レビュー後の修正が小さく局所的なら再レビューは不要。スコープ拡大、重要な挙動変更、高リスク領域への波及がある場合だけ再実行する。

## 7. マージ

```bash
git status --short
gh pr merge <PR番号> --squash --delete-branch
```

## 8. ローカル同期（pull/prune）

```bash
git fetch --prune
git switch main
git merge --ff-only origin/main
```

## 9. ブランチ削除（local）

```bash
git branch --merged main
git branch -d feature/<topic>
```

## 10. トラブル時

- `index.lock` が残っている場合: 別 Git プロセスが無いことを確認して `.git/index.lock` を削除。
- 無関係差分がある場合: そのファイルは add しない。必要なら `git stash push -- <file>` で一時退避。

## リポ固有ルール

ここから下に、このリポジトリ固有の運用ルールを追記する。
上の共通部は repo-templates（`AGENTS.md.<種別>`）由来のコピー。共通的に有益な改善はテンプレ側にも反映すること。

### 一次情報源

- エンドポイント仕様の一次情報源は `/docs`（OpenAPI）。response_model・summary・docstring を優先し、docs/ はそれを補足する。

### ドキュメント記述ルール

#### api-contract.md に書くもの
- エラーコードの意味と mini-tools 側の対応
- TTL 設計ルール・設計根拠
- manifest 形式の差異（endpoint グループ間のバリエーション）
- インシデント記録と再発防止策
- 認証の現状と将来構想

#### api-usage.md に書くもの
- エンドポイント別のレスポンス例（実物に近い形）
- curl コマンド集
- キャッシュ TTL の参照表（api-contract.md の設計ルールと整合させること）

#### README.md / docs/README.md に書くもの
- README.md: プロジェクト概要・エンドポイント一覧・起動方法・環境変数
- docs/README.md: ドキュメント一覧と配置ルールのみ

#### 書いてはいけないもの
- 調査ログ・作業メモ（git commit message か PR description に書く）
- 廃止済みの仕様（削除して git history に任せる）

### コード変更ルール

#### response_model の変更
- `market_info` が実際に publish する JSON の shape と一致させること
- 簡略化した型（`list[str]` など）は使わない
- nullable フィールドは `T | None` で明示する
- 変更前に `tests/` のフィクスチャが実 payload shape を反映しているか確認する

#### キャッシュ
- TTL 値は `app/cache.py` の `_MANIFEST_TTL`（21600秒=6時間）/ `_DAY_TTL`（86400秒=24時間）で一元管理する
- router で直接数値を書かない

#### テスト
- router unit test は `tests/fixtures/` の実 artifact shape（real_shape）を使う回帰ケースを必ず含める
- 簡略 mock だけで終わらせない

#### 新しいエンドポイントを追加する場合
1. `app/routers/` に router ファイルを追加
2. `app/main.py` に `include_router` を追記
3. `docs/api-contract.md` の「更新単位」テーブルに追記
4. `docs/api-usage.md` にレスポンス例と curl コマンドを追記
5. `README.md` のエンドポイント一覧に追記
6. `tests/` にフィクスチャと回帰テストを追加

### Git / PR の追加ルール

- Tier 2以上のコード変更は、PR前に `ruff check .` と影響範囲の `pytest` を実行する。Tier 3または広範な変更では関連フルスイートを実行する
- 小さなドキュメント修正のみ、かつオーナーが明示的に許可した場合に限り PR を省略できる

### デプロイ

- main へのマージで GCP Cloud Run が自動デプロイされる
- 設定変更（環境変数・スケール）は Cloud Run コンソールで行う
- 詳細は [`docs/gcp-cloud-run-setup.md`](docs/gcp-cloud-run-setup.md) を参照
