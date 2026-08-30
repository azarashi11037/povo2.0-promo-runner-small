# povo2.0 promo automation（実験的）

[简体中文](README.md) | [繁體中文](README.zh-Hant.md) | 日本語 | [English](README.en.md)

povo2.0 の promo code を指定時刻に処理するための、非公式かつセルフホスト型のツールです。GitHub Actions でメール OTP ログイン、セッションの暗号化保存、スケジュール実行を行えるほか、LAN 管理画面付きの Docker サービスとしても利用できます。

このリポジトリは公開ソースから作成した独立デプロイであり、暗号化済みアカウント状態と Repository Secret を分離保存します。共通コードと説明は公開 upstream で保守します。

> [!NOTE]
> このリポジトリはメンテナーのサブアカウント用プライベート実行インスタンスであり、再暗号化された `state/session.enc` を保存します。公開ソースと更新は引き続き [`povo2.0-promo-automation`](https://github.com/azarashi11037/povo2.0-promo-automation) を正本とします。

> [!WARNING]
> 本プロジェクトは非公開 API を使用しており、povo2.0/KDDI によるサポートまたは承認を受けていません。API はアプリ更新により変更される可能性があります。自分が管理権限を持つアカウントだけを使用し、適用される規約を自分で確認してください。OTP、TLS 検証、Root 制限、アクセス制御を回避する機能はありません。

## 利用者が入力するもの

推奨する GitHub Actions モードでは、次の情報だけを使用します。

1. povo2.0 のログイン用メールアドレス
2. 最新メールに記載された 6 桁の OTP
3. 再利用可能な promo code

これらを一つの公開フォームへまとめて入力する方式ではありません。メールアドレス、OTP、コードを Actions 履歴に残さないため、GitHub Repository Secrets を使って二段階で設定します。初期化後はメール、OTP、コードの Secret を削除し、長期保存するのは暗号化キー `POVO_BUNDLE_KEY` だけです。

## 実装済みの機能

- Android VM を常時起動しない二段階メール OTP ログイン
- セッション、端末情報、コード、スケジュール状態の AES-256-GCM 暗号化
- GitHub-hosted runner 内だけでの一時復号と、ジョブ終了時の平文破棄
- 定期的なセッション更新と、期限到来後の最大 1 回だけの送信
- 結果が不明な場合に `unknown` へ移行し、自動再試行を停止
- トークン、端末 ID、ユーザー ID、コードを出力しない許可リスト方式のログ
- 既存 Android セッションファイルを取り込む代替手段
- Docker Worker と、既定で `127.0.0.1` のみにバインドする管理画面
- CI による構文確認、単体テスト、Compose 検証、Docker ビルド

## GitHub Actions クイックスタート

1. このリポジトリを Fork します。
2. **Settings → Actions → General → Workflow permissions** で、Actions にリポジトリへの読み書きを許可します。
3. **Settings → Secrets and variables → Actions** で次を作成します。
   - `POVO_BUNDLE_KEY`：20 文字以上。ランダム生成を推奨します。
   - `POVO_LOGIN_EMAIL`：自分の povo2.0 ログイン用メールアドレス。
4. **Start povo2.0 email login** を実行し、OTP メールを待ちます。
5. メール到着後、すぐに次を作成します。
   - `POVO_LOGIN_OTP`：最新メールの 6 桁 OTP。
   - `POVO_PROMO_CODE`：promo code。
6. 15 分以内に **Finish povo2.0 login and redeem once** を実行します。この workflow の実行が初回交換の明示的な確認となり、成功時刻の 7 日 1 分後が次回時刻として自動設定されます。日時の手入力は不要です。
7. `state/session.enc` が作成されたことを確認し、`POVO_LOGIN_EMAIL`、`POVO_LOGIN_OTP`、`POVO_PROMO_CODE` を削除します。`POVO_BUNDLE_KEY` は残します。

現在のログイン／アカウント確認 API には、検証済みで信頼できる promo の有効期限フィールドがありません。JWT の期限は短期ログイントークンの期限であり、プランの期限ではありません。そのため、推測した期限ではなく、確認済みの初回交換成功時刻を起点にします。

以後、**povo2.0 session keeper** が毎時、時刻の先頭を避けて確認します。暗号化された次回目標が 65 分以内に入った場合だけセッションを更新して Runner 内で待機し、目標分に達してから最大 1 回送信します。それ以外の確認は povo API に接続せず、ファイルもコミットしません。GitHub cron は遅延または欠落する可能性があり、秒単位の正確さは保証できません。詳細は [GitHub Actions ガイド](docs/GITHUB_ACTIONS.ja.md) を参照してください。

## Docker セルフホスト

自分のサーバーで Worker と LAN WebUI を運用したい場合のモードです。自分のアカウントに対応する `credentials.xml` と `device.xml` を、正当な方法ですでに取得している必要があります。

```bash
cp .env.example .env
python3 tools/init_data.py --data-dir ./data
cp /your/authorized/path/credentials.xml ./data/credentials.xml
cp /your/authorized/path/device.xml ./data/device.xml
chmod 600 ./data/*
docker compose up -d --build
```

`http://127.0.0.1:17820/` を開き、最初に読み取り専用の認証確認を実行します。既定値は `POVO_ENABLE_REDEMPTION=0` です。セッションと日時を確認した後に限り、`.env` を次のように変更します。

```dotenv
POVO_ENABLE_REDEMPTION=1
```

## セキュリティ境界

- Issue、Pull Request、通常の workflow input、ログ、スクリーンショットへ認証情報を記載しないでください。
- `.env`、`data/`、XML、コード、復号済み状態を Git に追加しないでください。
- Dashboard はループバックまたは信頼できる LAN のみに公開してください。外部公開には認証付き HTTPS リバースプロキシが必要です。
- 送信結果を確認できない場合は、連続して再実行しないでください。
- 詳細は [SECURITY.md](SECURITY.md) を参照してください。

## 既知の制限

- 非公開 API のため、アプリ更新後に動作しなくなる可能性があります。
- 複数の add-on があるアカウントでは `MULTIPLE_ADDONS_FOUND` が返る場合があり、未解決です。
- GitHub のスケジュール実行は待機または遅延する場合があります。
- 現在、ログイン後に既存 promo の有効期限を確実に読み取ることはできません。
- メール OTP は利用者が 15 分以内に手動で設定する必要があります。
- 本プロジェクトは本番品質または通信事業者の公式ツールではありません。

## コントリビューター

貢献者情報は [CONTRIBUTORS.md](CONTRIBUTORS.md) を参照してください。OpenAI の AI コーディングアシスタント [@codex](https://github.com/codex) が、設計、実装、テスト、セキュリティ確認、多言語ドキュメントを支援しました。人間のメンテナーではありません。

## ライセンスと免責事項

本プロジェクトは [MIT License](LICENSE) で公開されています。API、フィールド、業務ルールは変更される可能性があります。誤った利用により、セッション失効、重複送信、アカウント制限が発生する可能性があります。作者は明示・黙示を問わず保証を行わず、利用者が自己責任で使用するものとします。
