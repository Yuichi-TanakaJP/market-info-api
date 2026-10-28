# CIの実行方針

ローカル検証と独立レビューをmerge判断の基本とする。GitHub ActionsのCIは
workflow_dispatchによる手動実行のみ。lint・test・import確認は維持する。
未実行はNOT_RUN。将来必須checkを導入する場合は手動実行方針と整合させる。

Cloud BuildはActionsと独立しmain更新で本番配備を起動する。
コミットのタイトル・本文（squash本文を含む）に `[skip ci]` / `[ci skip]` を使わない。
これらはCloud Buildも止めるためActionsの省略には使わない。

ファイル追加・移動時は必要なローカル検証を更新する。手動CIはpathによる除外をせず全検証を行う。
Cloud Build・Cloud Run・定期実行の設定変更・起動の承認は従来どおり。
配備確認は [Cloud Run手順](gcp-cloud-run-setup.md) を参照する。
