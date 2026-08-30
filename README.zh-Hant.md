# povo2.0 promo automation（實驗性）

[简体中文](README.md) | 繁體中文 | [日本語](README.ja.md) | [English](README.en.md)

一個非官方、自行託管的 povo2.0 promo code 定時執行器。它可透過 GitHub Actions 完成電子郵件驗證碼登入、加密保存工作階段並依排程執行，也可部署成附有區域網路管理面板的 Docker 服務。

本倉庫是從公開原始碼產生的獨立部署副本，用於隔離保存加密帳戶狀態與 Repository Secret；通用程式碼和說明在公開上游倉庫維護。

> [!NOTE]
> 目前倉庫是維護者小號的私有執行實例，會保存該帳戶重新加密後的 `state/session.enc`；公開原始碼與更新仍以 [`povo2.0-promo-automation`](https://github.com/azarashi11037/povo2.0-promo-automation) 為準。

> [!WARNING]
> 本專案使用未公開、可能隨 povo2.0 App 更新而改變的介面，不受 povo2.0/KDDI 支援或認可。請只操作本人有權管理的帳戶，並自行確認適用條款。本專案不繞過驗證碼、TLS 驗證、Root 限制或存取控制。

## 使用者需要提供什麼

GitHub Actions 推薦模式只需要使用者提供：

1. povo2.0 登入電子郵件；
2. 郵件中最新的 6 位驗證碼；
3. 可重複使用的 promo code。

這些資料不會填入同一個公開表單。為避免電子郵件、驗證碼與兌換碼出現在 Actions 歷史中，必須透過 GitHub Repository Secrets 分兩個階段保存。初始化完成後，可刪除電子郵件、驗證碼及兌換碼 Secret，只長期保留加密金鑰 `POVO_BUNDLE_KEY`。

## 已實作

- 不需常駐 Android 虛擬機的兩階段電子郵件驗證碼登入；
- 以 AES-256-GCM 加密工作階段、裝置、兌換碼與排程狀態；
- 只在 GitHub-hosted runner 中暫時解密，工作結束後銷毀明文；
- 定期更新工作階段，只在到期後最多提交一次；
- 結果不明確時進入 `unknown` 並停止自動重試；
- 白名單式脫敏日誌，不輸出權杖、裝置 ID、使用者 ID 或兌換碼；
- 可選擇匯入既有 Android 工作階段檔案；
- Docker Worker 與預設只綁定 `127.0.0.1` 的管理面板；
- CI 語法檢查、單元測試、Compose 驗證與 Docker 建置。

## GitHub Actions 快速開始

1. Fork 本倉庫。
2. 到 **Settings → Actions → General → Workflow permissions**，允許 Actions 讀寫倉庫內容。
3. 到 **Settings → Secrets and variables → Actions** 建立：
   - `POVO_BUNDLE_KEY`：至少 20 個字元，建議隨機產生；
   - `POVO_LOGIN_EMAIL`：本人的 povo2.0 登入電子郵件。
4. 執行 **Start povo2.0 email login**，等待驗證碼郵件。
5. 立即建立：
   - `POVO_LOGIN_OTP`：最新郵件中的 6 位驗證碼；
   - `POVO_PROMO_CODE`：promo code。
6. 在 15 分鐘內執行 **Finish povo2.0 login and redeem once**。執行此工作流程即表示明確確認首次兌換；確認成功後，系統會自動將下一次時間設為成功時刻加 7 天 1 分鐘，不需手動輸入日期。
7. 確認倉庫出現 `state/session.enc` 後，刪除 `POVO_LOGIN_EMAIL`、`POVO_LOGIN_OTP` 與 `POVO_PROMO_CODE`，只保留 `POVO_BUNDLE_KEY`。

目前登入／帳戶檢查介面沒有經驗證且可靠的 promo 到期欄位。JWT 的到期時間只是短期登入權杖期限，不能視為方案到期時間。因此建議流程以首次兌換確認成功的時刻自動起算，不會猜測或誤讀到期時間。

之後 **povo2.0 session keeper** 每小時在非整點檢查一次。只有加密的下一次目標進入 65 分鐘視窗時才更新工作階段並留在 Runner 內等待，到目標分鐘後最多提交一次；其餘檢查不存取 povo API，也不提交檔案。GitHub cron 仍可能延遲或遺失任務，無法保證秒級準時。完整說明請參閱 [GitHub Actions 使用說明](docs/GITHUB_ACTIONS.zh-Hant.md)。

## Docker 自行託管

Docker 模式適合希望在自己的伺服器執行 Worker 與區域網路 WebUI 的使用者。使用前必須已合法取得與本人帳戶相符的 `credentials.xml` 和 `device.xml`。

```bash
cp .env.example .env
python3 tools/init_data.py --data-dir ./data
cp /your/authorized/path/credentials.xml ./data/credentials.xml
cp /your/authorized/path/device.xml ./data/device.xml
chmod 600 ./data/*
docker compose up -d --build
```

開啟 `http://127.0.0.1:17820/`，先執行唯讀驗證檢查。預設 `POVO_ENABLE_REDEMPTION=0`；確認工作階段及時間無誤後，才在 `.env` 改為：

```dotenv
POVO_ENABLE_REDEMPTION=1
```

## 安全界線

- 不要在 Issue、Pull Request、一般工作流程輸入、日誌或截圖中提交驗證資料。
- 不要把 `.env`、`data/`、XML、兌換碼或解密後的狀態加入 Git。
- Dashboard 只應綁定回環位址或可信內網；若要從公網存取，必須使用具身分驗證的 HTTPS 反向代理。
- 一次提交結果無法確認時，不要連續重新執行。
- 詳細要求請參閱 [SECURITY.md](SECURITY.md)。

## 已知限制

- 介面未公開，App 更新後可能失效；
- 帳戶同時存在多個 add-on 時可能回傳 `MULTIPLE_ADDONS_FOUND`，目前尚未解決；
- GitHub 排程可能排隊或延遲；
- 目前無法在登入後可靠讀取既有 promo 的到期時間；
- 兩階段登入仍需要使用者在 15 分鐘內手動提供郵件驗證碼；
- 本專案不是生產級或電信業者官方工具。

## 貢獻者

貢獻記錄請參閱 [CONTRIBUTORS.md](CONTRIBUTORS.md)。[@codex](https://github.com/codex) 以 OpenAI AI 程式設計助手身分參與架構、實作、測試、安全檢查與多語言文件，但不是人工維護者。

## 授權與免責聲明

本專案採用 [MIT License](LICENSE)。介面、欄位與業務規則可能變更；錯誤使用可能造成工作階段失效、重複提交或帳戶限制。專案作者不提供任何明示或暗示擔保，使用者自行承擔風險。
