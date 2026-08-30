# GitHub Actions ガイド

[简体中文](GITHUB_ACTIONS.md) | [繁體中文](GITHUB_ACTIONS.zh-Hant.md) | 日本語 | [English](GITHUB_ACTIONS.en.md)

公開 Fork 向けの実行方法です。リポジトリに保存されるのは認証付き暗号化ファイル `state/login.enc` または `state/session.enc` だけです。メール、OTP、promo code、平文セッションは Git、Artifact、Cache に保存されません。

## 事前設定

1. リポジトリを Fork し、Actions を有効にします。
2. **Settings → Actions → General** を開きます。
3. **Workflow permissions** で **Read and write permissions** を選択します。
4. **Settings → Secrets and variables → Actions** を開きます。

## Web UI：メール OTP で初期化

### 1. OTP を送信する

Repository Secret を二つ作成します。

- `POVO_BUNDLE_KEY`：20 文字以上。ランダムな 32 バイト値を推奨し、長期保存します。
- `POVO_LOGIN_EMAIL`：自分の povo2.0 ログイン用メールアドレス。

**Actions → Start povo2.0 email login → Run workflow** を実行します。成功すると OTP メールが届き、暗号化された `state/login.enc` が作成されます。

### 2. ログインを完了する

必ず最新メールを使い、すぐに次の Repository Secret を作成します。

- `POVO_LOGIN_OTP`：6 桁 OTP。
- `POVO_PROMO_CODE`：スケジュール実行する promo code。

**Actions → Finish povo2.0 login and redeem once → Run workflow** を実行します。この明示的な名前の workflow を実行することが、初回交換を 1 回送信する確認になります。

OTP チャレンジは 15 分間だけ有効です。Start を再実行した場合、以前のメールは使わず、新しいメールだけを使用してください。

初回交換が確認済みの成功となった後、その成功分を起点として `next_due_at` が 7 日 1 分後に自動設定されます。初回日時の手入力は不要です。その後、`state/login.enc` が `state/session.enc` に置き換わります。`POVO_LOGIN_EMAIL`、`POVO_LOGIN_OTP`、`POVO_PROMO_CODE` を削除し、`POVO_BUNDLE_KEY` だけを残します。

ログイン後のアカウント確認 API には、検証済みで信頼できる promo の有効期限フィールドがありません。JWT の期限は短期ログイントークンの期限です。本プロジェクトは JWT の期限をプラン期限として扱わず、既存 promo の期限も推測しません。

## GitHub CLI

`gh secret set` は端末上で値を安全に入力できます。Secret をコマンド引数に直接書かないでください。

```bash
openssl rand -base64 32 | gh secret set POVO_BUNDLE_KEY
gh secret set POVO_LOGIN_EMAIL
gh workflow run login-start.yml
```

最新の OTP メールを受信した後：

```bash
gh secret set POVO_LOGIN_OTP
gh secret set POVO_PROMO_CODE
gh workflow run login-finish.yml
```

成功後：

```bash
gh secret delete POVO_LOGIN_EMAIL
gh secret delete POVO_LOGIN_OTP
gh secret delete POVO_PROMO_CODE
```

## 自動実行

**povo2.0 session keeper** は毎時 UTC 32 分に確認し、時刻の先頭に集中する負荷を避けます。一時 Runner で状態を復号しますが、`next_due_at` が 65 分以内に入った場合だけ povo API に接続してセッションを更新し、目標分まで待機します。それ以外は直ちに終了し、ファイルもコミットしません。前の時間帯の実行が遅延または欠落した場合は、次の毎時実行が期限後に補います。

たとえば目標分が `:42` の場合、`:32` の毎時実行が約 10 分前に準備します。その後は「7 日 1 分」規則により先行時間が 0～60 分の範囲で変わりますが、送信は必ず目標分まで待ちます。すべての入口が `next_due_at`、一時停止状態、送信状態を確認するため、重複交換は発生しません。GitHub cron は待機、遅延、欠落の可能性があり、秒単位の正確さは保証できません。結果を確認できない場合は `unknown` へ移行し、自動再試行を停止します。

## 保存されるもの

- `POVO_BUNDLE_KEY`：長期保存する Repository Secret。
- `state/login.enc`：ログインの二段階の間だけ存在する短期チャレンジ暗号文。
- `state/session.enc`：セッション、端末、promo code、スケジュール状態を含む AES-256-GCM 暗号文。

鍵は `POVO_BUNDLE_KEY` から scrypt で導出され、ランダムな salt と nonce を使用します。

## 代替インポートと復旧

メール API が変更された場合は **Import encrypted povo2.0 session** で、既存の正当な Android セッションを取り込めます。`POVO_CREDENTIALS_B64`、`POVO_DEVICE_B64`、`POVO_PROMO_CODE` を一時的に設定し、成功後に削除します。

- OTP が無効：最後に Start を実行した後の最新メールか確認します。
- `state/login.enc` が期限切れ：Start を一度だけ再実行します。
- `POVO_BUNDLE_KEY` を紛失：暗号文は復旧できないため、再ログインします。
- 鍵が漏えい：暗号文を削除して Secret をローテーションし、公式アプリでセッションを更新します。
- Bot が push できない：Workflow permissions とブランチ保護を確認します。
- `MULTIPLE_ADDONS_FOUND`：未解決のため、連続再実行しないでください。

認証情報を workflow input、Issue、Pull Request、Actions ログ、公開テストデータへ記載しないでください。
