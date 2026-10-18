# Market Info API working agreements

## Safety and authority

- Verify facts; leave unknowns explicit. Preserve unrelated dirty/untracked work; never read or expose secret environment values or commit credentials/private data. Only secret-free environment examples belong in Git.
- Reversible branch-local work proceeds without extra approval. Explain API/schema/dependency/schedule/instruction changes once before implementation. Diagnosis alone does not authorize implementation.
- Obtain explicit approval immediately before default-branch merge, deletion/overwrite, force push, production deploy, external publication or paid operations; state what remains and what is removed. Do not infer authorization from a checklist.
- Use a purpose-specific branch/PR against the actual default, one purpose per PR. Use squash merge after approval. Inspect branch/status before changes and merge; stage only intended files. Preserve generated/environment files unless intentionally changed. Use --body-file for multiline GitHub bodies.
- PRs record changes, related issue, actual checks/review and limitations. Inspect final diff, current base/head, checks and unresolved findings before approved merge. After merge, sync without overwriting dirty work; clean worktree/branches and prune only with deletion approval.

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
## Behavior validation

- Tier 0: meaning-preserving docs/comments/examples; final diff and relevant syntax/link checks. Tier 1: local internal logic; targeted lint/tests and independent review for behavior changes.
- Tier 2: API/UI, scheduled work or external I/O; affected lint/tests, relevant build and **executed changed-behavior UAT**. Tier 3: auth/billing/migrations/security/production or broad impact; related full suite/build, rollback/recovery and executed release/UAT checks. Use the highest applicable tier.
- Add practical regression/boundary tests for changed behavior. Scheduled work, public output and external delivery need real tests and documented commands; document a justified absence instead of installing a synthetic gate.
- For Tier 2+ externally observable behavior, record the operation/request, input, expected result, failure behavior and environment in the PR body **or** the relevant UAT document. Keep execution evidence in the PR, not permanent checked boxes. Before publication or a major release, check the applicable release checklist.
- High-risk or broad changes require the related full suite/build, recovery/rollback evidence and relevant UAT; local edits use targeted checks. Classify by actual meaning/operational impact, not extension or line count; unknown impact is not review-skippable.

## Review and local verification

- Meaning-preserving edits: final diff and relevant syntax/link/output checks. Behavior changes: one independent review. Auth/permissions/secrets/billing/migrations/production or broad impact: heightened review with specialist and rollback scrutiny.
- The agent chooses model/profile/effort and records review depth/reason in the PR. Failed invocations are not reviews and alone do not justify lowering depth; use an available method. Reassessed depth needs a reason. Re-review material changes, not typo/comment/evidence-only followups.
- Use affected repository checks; do not add dependencies or unrelated full suites just for verification. Failures, unresolved findings and missing required evidence block merge. Report untested coverage.
- Local validation is primary; optional Actions are skipped by default after checking enforced rules and repo exceptions. Existing automatic triggers remain: use [skip ci] only when permitted; do not dispatch/re-run by default. Record real run outcomes, using NOT_RUN only for no execution. Approval for merge, deletion, publication, deployment and paid operations remains required.

## CI scope

When adding/moving/reclassifying paths or changing CI/skip behavior, follow [the repository CI policy](docs/ci-scope-policy.md). Preserve domain/deploy/schedule workflows and unknown-path validation; do not repeat unchanged checks.
