# GitHub Actions 使用说明

简体中文 | [繁體中文](GITHUB_ACTIONS.zh-Hant.md) | [日本語](GITHUB_ACTIONS.ja.md) | [English](GITHUB_ACTIONS.en.md)

GitHub Actions 模式适合公开 Fork。仓库只保存认证加密的 `state/login.enc` 或 `state/session.enc`；邮箱、验证码、兑换码和明文会话不会提交到 Git、Artifact 或 Cache。

## 前置设置

1. Fork 仓库并启用 Actions。
2. 打开 **Settings → Actions → General**。
3. 在 **Workflow permissions** 选择 **Read and write permissions** 并保存。
4. 打开 **Settings → Secrets and variables → Actions**。

## 网页方式：邮箱验证码初始化

### 第一步：发送验证码

建立两个 Repository Secret：

- `POVO_BUNDLE_KEY`：至少 20 字符；建议使用随机 32 字节值，长期保留。
- `POVO_LOGIN_EMAIL`：本人 povo2.0 账户的登录邮箱。

进入 **Actions → Start povo2.0 email login → Run workflow**。成功后会收到邮件，仓库中会出现加密的 `state/login.enc`。

### 第二步：完成登录

只使用最新一封邮件，并立即建立：

- `POVO_LOGIN_OTP`：6 位验证码。
- `POVO_PROMO_CODE`：需要按计划使用的 promo code。

进入 **Actions → Finish povo2.0 login and redeem once → Run workflow**。运行这个明确命名的工作流即表示确认提交一次首次兑换。

验证码挑战有效期为 15 分钟。不要再次运行发码工作流后继续使用旧邮件；新发码会建立新的挑战。

首次兑换确认成功后，系统以成功分钟为起点，自动把 `next_due_at` 设为 7 天 1 分钟后；无需手动输入首次执行时间。随后 `state/login.enc` 会被 `state/session.enc` 替换。删除以下一次性 Secret：

- `POVO_LOGIN_EMAIL`
- `POVO_LOGIN_OTP`
- `POVO_PROMO_CODE`

只保留 `POVO_BUNDLE_KEY`。

登录后的账户检查目前没有提供经过验证、可靠的 promo 到期字段；JWT 到期时间只是短期登录令牌期限。因此本项目不会把 JWT 时间当成套餐到期时间，也不会猜测现有 promo 的期限。

## GitHub CLI 方式

以下命令会让 `gh secret set` 在终端中安全提示输入值，不要把 Secret 直接写在命令参数里：

```bash
openssl rand -base64 32 | gh secret set POVO_BUNDLE_KEY
gh secret set POVO_LOGIN_EMAIL
gh workflow run login-start.yml
```

收到最新邮件后：

```bash
gh secret set POVO_LOGIN_OTP
gh secret set POVO_PROMO_CODE
gh workflow run login-finish.yml
```

确认登录工作流成功后：

```bash
gh secret delete POVO_LOGIN_EMAIL
gh secret delete POVO_LOGIN_OTP
gh secret delete POVO_PROMO_CODE
```

可以用 `gh run list` 和 `gh run watch` 查看状态；日志只应显示脱敏结果。

## 初始化完成后如何运行

**povo2.0 session keeper** 每小时在 UTC 的第 32 分钟检查一次，避开整点高负载。执行逻辑为：

1. 在临时 Runner 中解密状态，但先不访问 povo API；
2. 若 `next_due_at` 仍在 65 分钟以外，立即结束，不刷新令牌、不产生提交；
3. 若已进入 65 分钟窗口，刷新会话并在 Runner 内等待；
4. 到目标分钟后走单次提交路径，并在提交前再次刷新；
5. 只有认证文件或调度状态实际变化时，才重新加密并提交；
6. 若前一个小时入口被延迟或丢弃，下一个小时入口会在到期后立即补偿。

例如目标分钟为 `:42` 时，`:32` 的小时入口会提前约 10 分钟准备。目标分钟随“7 天 1 分钟”规则变化后，提前量会在 0–60 分钟之间，但提交仍等待到目标分钟。所有入口都会检查 `next_due_at`、暂停状态和提交状态，因此不会重复兑换。GitHub cron 仍可能排队、延迟甚至被丢弃，不能保证秒级准时；若结果无法确认，状态会变为 `unknown` 并阻止自动重试。

## 仓库中保存什么

- `POVO_BUNDLE_KEY`：Repository Secret，长期解密钥匙。
- `state/login.enc`：仅在两阶段登录之间存在的短期挑战密文。
- `state/session.enc`：包含最小必要会话、设备、promo code 和调度状态的 AES-256-GCM 密文。

加密密钥通过 scrypt 从 `POVO_BUNDLE_KEY` 派生，并使用随机 salt、nonce。知道公开密文但不知道钥匙，不能直接还原内容。

## 备用：导入现有 Android 会话

如果邮箱登录接口因 App 更新失效，可以改用 **Import encrypted povo2.0 session**。需要临时建立：

- `POVO_CREDENTIALS_B64`
- `POVO_DEVICE_B64`
- `POVO_PROMO_CODE`
- 已有的 `POVO_BUNDLE_KEY`

```bash
base64 < credentials.xml | tr -d '\n' | gh secret set POVO_CREDENTIALS_B64
base64 < device.xml | tr -d '\n' | gh secret set POVO_DEVICE_B64
gh secret set POVO_PROMO_CODE
gh workflow run import-session.yml \
  -f next_due_at='2026-09-06T16:17:00+09:00'
```

成功后删除三个一次性导入 Secret。

## 故障恢复

- OTP 无效：确认使用的是最后一次发码后的最新邮件；重新开始时只运行一次发码工作流。
- `state/login.enc` 过期：重新运行 **Start povo2.0 email login**，旧验证码作废。
- 丢失 `POVO_BUNDLE_KEY`：无法恢复密文，只能重新登录或重新导入。
- 钥匙泄露：删除密文、轮换 Secret，并通过官方 App 更新账户会话。
- Bot 无法 push：检查 Workflow permissions 和默认分支保护规则。
- `MULTIPLE_ADDONS_FOUND`：当前未解决，不要连续重跑。

不要在 workflow input、Issue、Pull Request、Actions 日志或公开测试数据中提交认证材料。
