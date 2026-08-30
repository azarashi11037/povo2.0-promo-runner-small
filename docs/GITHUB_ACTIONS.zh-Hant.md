# GitHub Actions 使用說明

[简体中文](GITHUB_ACTIONS.md) | 繁體中文 | [日本語](GITHUB_ACTIONS.ja.md) | [English](GITHUB_ACTIONS.en.md)

GitHub Actions 模式適合公開 Fork。倉庫只保存經驗證加密的 `state/login.enc` 或 `state/session.enc`；電子郵件、驗證碼、兌換碼及明文工作階段不會提交到 Git、Artifact 或 Cache。

## 前置設定

1. Fork 倉庫並啟用 Actions。
2. 開啟 **Settings → Actions → General**。
3. 在 **Workflow permissions** 選擇 **Read and write permissions** 並保存。
4. 開啟 **Settings → Secrets and variables → Actions**。

## 網頁方式：電子郵件驗證碼初始化

### 第一步：發送驗證碼

建立兩個 Repository Secret：

- `POVO_BUNDLE_KEY`：至少 20 個字元；建議使用隨機 32 位元組值並長期保留。
- `POVO_LOGIN_EMAIL`：本人 povo2.0 帳戶的登入電子郵件。

進入 **Actions → Start povo2.0 email login → Run workflow**。成功後會收到郵件，倉庫中會出現加密的 `state/login.enc`。

### 第二步：完成登入

只使用最新一封郵件，並立即建立：

- `POVO_LOGIN_OTP`：6 位驗證碼。
- `POVO_PROMO_CODE`：要依排程使用的 promo code。

進入 **Actions → Finish povo2.0 login and redeem once → Run workflow**。執行這個明確命名的工作流程即表示確認提交一次首次兌換。

驗證碼挑戰有效期為 15 分鐘。不要重新執行發碼工作流程後繼續使用舊郵件；新發碼會建立新的挑戰。

首次兌換確認成功後，系統會以成功分鐘為起點，自動把 `next_due_at` 設為 7 天 1 分鐘後；不需手動輸入首次執行時間。之後 `state/login.enc` 會由 `state/session.enc` 取代。刪除 `POVO_LOGIN_EMAIL`、`POVO_LOGIN_OTP` 與 `POVO_PROMO_CODE`，只保留 `POVO_BUNDLE_KEY`。

登入後的帳戶檢查目前沒有提供經驗證且可靠的 promo 到期欄位；JWT 到期時間只是短期登入權杖期限。因此本專案不會把 JWT 時間視為方案到期時間，也不會猜測既有 promo 的期限。

## GitHub CLI 方式

`gh secret set` 會在終端機安全提示輸入值，不要把 Secret 直接寫入命令參數：

```bash
openssl rand -base64 32 | gh secret set POVO_BUNDLE_KEY
gh secret set POVO_LOGIN_EMAIL
gh workflow run login-start.yml
```

收到最新郵件後：

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

## 自動執行

**povo2.0 session keeper** 每小時在 UTC 第 32 分鐘檢查，避開整點高負載。它先在臨時 Runner 解密狀態，但只有 `next_due_at` 進入 65 分鐘視窗時才存取 povo API、更新工作階段並等待到目標分鐘；其餘檢查立即結束，也不提交檔案。若前一個入口被延遲或遺失，下一個小時入口會在到期後立即補償。

例如目標分鐘為 `:42` 時，`:32` 的每小時入口會提前約 10 分鐘準備。之後提前量會隨「7 天 1 分鐘」規則在 0–60 分鐘間變化，但提交仍等待到目標分鐘。所有入口都會檢查 `next_due_at`、暫停狀態及提交狀態，因此不會重複兌換。GitHub cron 仍可能排隊、延遲或遺失，無法保證秒級準時；結果無法確認時會進入 `unknown` 並停止自動重試。

## 保存內容與復原

- `POVO_BUNDLE_KEY`：長期 Repository Secret。
- `state/login.enc`：登入兩階段之間的短期挑戰密文。
- `state/session.enc`：AES-256-GCM 加密的工作階段、裝置、promo code 與排程狀態。

若遺失 `POVO_BUNDLE_KEY`，密文無法復原，只能重新登入。若金鑰外洩，請刪除密文、輪替 Secret，並透過官方 App 更新工作階段。Bot 無法 push 時，請檢查 Workflow permissions 與分支保護。

備用的既有 Android 工作階段匯入方式及完整故障排除，請參考[簡體中文完整說明](GITHUB_ACTIONS.md)中的相同命令；所有 Secret 名稱與工作流程名稱在各語言版本中一致。
