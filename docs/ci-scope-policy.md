# CIの対象ファイルと更新手順

決定日: 2026-10-13。設定の正本は `.github/workflows/` のYAML。本文はその運用手順です。

## 既存YAMLの自動trigger判定（2026-10-13）

通常CIは、YAMLのpaths-ignoreに完全一致する説明専用ファイルだけの変更で起動を省きます。1件でも対象外のpathが混ざれば、既存の全検証を実行します。新規・未知のpathは既定で対象です。Markdown全体やdocs全体を除外しません。SQL・JSON・設定・コード・テスト・AGENTS/CLAUDE・本運用手順は既定で検証対象です。

PRはPR全体の累積差分で判定します。コードを含むPRへの説明文だけの追加pushも対象になり得ます。判定はファイルpathの照合であり、自然言語の意味・変更行数・AIの都度判断ではありません。

自動PR検証はworkflow名＋PR番号でconcurrencyをまとめ、古い実行をキャンセルします。pushはrun_idで分離し、独立したmain更新をキャンセルしません。即時に終了した失敗はキャンセルで消せません。設定は過去の実行に遡及適用されません。

## ファイルを追加・移動・用途変更したとき

1. 変更担当（開発者または実装AI）が新規・移動pathを確認する。何もしなければ、既存workflowの対象条件がそのまま適用される。
2. 通常CIから除外したい場合だけ、内容・runtime/build/testからの参照・実行手順/契約への影響を確認する。拡張子だけを理由に除外しない。
3. 説明専用と確認できたpathだけ、同じPRでpush/pull_request両方のpaths-ignoreへ完全一致で追加し、理由をPR本文に残す。既存のpaths限定workflowにはこの手順でpaths-ignoreを混在させない。
4. 除外済みファイルがruntime/build/testの入力になったら、利用コードと同じPRで除外を外す。rename時も新旧の除外リストを見直す。新pathを自動除外しない。
5. 説明-only、説明＋コード、SQL、JSON、新規folder、workflow変更の判定を確認し、Codexの独立レビューを受ける。必要なrequired checkに指定されている場合、workflow全体を省く方式を採用せずチェックを残す設計を先に確認する。
6. ローカルで変更範囲を検証してからまとめてpushする。内容不変のレビューやCI再実行を繰り返さない。古い作業branchの採用は各担当が最新default branchとの差分を確認して取り込み、他担当のbranchを勝手に更新しない。

## 対象を変えない境界

既存のpaths限定監査・SQL検証・Skill同期はそのpathsを維持します。手動・scheduled workflow、Cloud Build、Cloud Run、Windows Task Scheduler、公開・送信処理は今回のPR concurrency対象拡大に含めません。既存のjob名・検証コマンド・required checkを削除しません。

CI利用上限中に開始前failureとなったものは、検証成功にもコード不合格にも扱いません。利用上限の変更や課金追加はこの手順では行いません。現GitHub上の説明-only起動省略・連続PR cancellationの効果は、次の通常の開発イベントで確認してPR証拠へ記録します。検証だけのpush/PRを量産しません。

## テンプレートへの共通化

共通化の計画正本は [repo-templates #22](https://github.com/Yuichi-TanakaJP/repo-templates/issues/22)。現在はrepoごとのYAMLを個別に維持します。テンプレートはコピー方式であり、自動同期は未実装。今後は共通ガードとrepo固有jobs/allowlistを分離し、差分をレビューできるPRで更新する予定です。Python/SQL/UIの選択実行やrequired-check互換方式は別の設計・検証として扱います。

## 2026-10-18: local-first方針と既存自動triggerの区別

Owner承認の現行方針は、リスク相応のローカル検証と必要な独立レビューをmerge判断の基準にすること。Actionsは任意・agentからのdispatch/re-runは既定で行わない。実際の強制branch ruleと明示例外は先に確認し、無断でbypassしない。

このPRは既存workflowの自動push/PR triggerを変更しない。「Actions任意」はYAMLが自動的に手動専用へ変わったことを意味しない。上の2026-10-13のpath判定は、triggerが有効でskip指定がない場合の技術的な起動条件として残る。コード・設定・AGENTS/CLAUDE・未知pathの検証責任も残り、まずローカルでリスク相応に検証する。通常hosted実行をmergeの必須条件とする旧記述は、このowner決定で更新する。

強制hosted checkがないことを確認し、今回のようにowner方針に沿って自動Actionsを省略する場合は、commit messageへ `[skip ci]` を付ける。強制checkや固有例外がある場合はskipせず、その条件を満たす。これは既存YAML・job・deploy/schedule/publish triggerを一括変更する権限ではない。

push/PR後は実際のchecks/runsを確認する。自動runが起動した場合は、そのRUNNING/PASS/FAIL/CANCELLED等の実状態を記録し、NOT_RUNと書かない。NOT_RUNは本当に未実行の場合だけ。Vercel previewや自動Codex reviewはActionsと別に記録する。ローカル失敗・未解決指摘・必要証拠不足はHOLD。削除・本番deploy・公開・課金・mergeの承認は従来どおり。
