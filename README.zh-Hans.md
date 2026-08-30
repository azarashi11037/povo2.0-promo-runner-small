# povo2.0 promo automation（实验性）

简体中文 | [繁體中文](README.zh-Hant.md) | [日本語](README.ja.md) | [English](README.en.md)

一个非官方、自托管的 povo2.0 promo code 定时执行器。支持通过 GitHub Actions 完成邮箱验证码登录、加密保存会话并按计划执行，也可以部署为带局域网管理面板的 Docker 服务。

本仓库定位为公开源码与部署模板，不承载维护者正在使用的账户状态。每个使用者应在自己的独立运行仓库中保存加密的 `state/session.enc` 和 Repository Secret，从而让源码维护与实际账户运行相互隔离。

> [!WARNING]
> 本项目使用未公开、可能随 povo2.0 App 更新而变化的接口，不受 povo2.0/KDDI 支持或认可。请只操作本人有权管理的账户，并自行确认适用条款。项目不绕过验证码、TLS 校验、Root 限制或访问控制。

## 用户需要提供什么

GitHub Actions 推荐模式只需要用户提供：

1. povo2.0 登录邮箱；
2. 邮件收到的最新 6 位验证码；
3. 可重复使用的 promo code。

这些内容不是填在同一个公开表单中。为了避免邮箱、验证码和兑换码出现在 Actions 历史里，它们必须通过 GitHub Repository Secrets 分两步保存。初始化完成后，可以删除邮箱、验证码和兑换码 Secret，只长期保留加密钥匙 `POVO_BUNDLE_KEY`。

## 已实现

- 无需常驻 Android 虚拟机的两阶段邮箱验证码登录；
- AES-256-GCM 加密的会话、设备、兑换码和调度状态；
- GitHub-hosted runner 中临时解密，任务结束后销毁明文；
- 定期刷新会话，仅在到期后最多提交一次；
- 结果不明确时进入 `unknown` 并停止自动重试；
- 白名单式脱敏日志，不输出令牌、设备 ID、用户 ID 或兑换码；
- 备用的 Android 会话文件导入方式；
- Docker Worker 与默认仅绑定 `127.0.0.1` 的管理面板；
- CI 中的语法检查、单元测试、Compose 校验和 Docker 构建。

## GitHub Actions 快速开始

1. Fork 本仓库。
2. 在 **Settings → Actions → General → Workflow permissions** 中允许 Actions 读写仓库内容。
3. 在 **Settings → Secrets and variables → Actions** 中建立：
   - `POVO_BUNDLE_KEY`：至少 20 字符，建议随机生成；
   - `POVO_LOGIN_EMAIL`：本人的 povo2.0 登录邮箱。
4. 运行 **Start povo2.0 email login**，等待验证码邮件。
5. 立即建立：
   - `POVO_LOGIN_OTP`：最新邮件中的 6 位验证码；
   - `POVO_PROMO_CODE`：promo code。
6. 在 15 分钟内运行 **Finish povo2.0 login and redeem once**。运行此工作流即表示明确确认首次兑换；确认成功后，系统自动将下一次时间设为成功时刻加 7 天 1 分钟，无需手动填写日期。
7. 确认仓库出现 `state/session.enc` 后，删除 `POVO_LOGIN_EMAIL`、`POVO_LOGIN_OTP` 和 `POVO_PROMO_CODE`，只保留 `POVO_BUNDLE_KEY`。

当前登录/账户检查接口没有已验证可靠的 promo 到期字段。JWT 的过期时间只是短期登录令牌期限，不能当作套餐到期时间。因此推荐流程以首次兑换确认成功的时刻自动起算，而不会猜测或误读到期时间。

之后 **povo2.0 session keeper** 每小时在非整点检查一次。只有加密的下次目标进入 65 分钟窗口时才刷新会话并留在 Runner 内等待，到目标分钟后最多提交一次；其余检查不访问 povo API，也不提交文件。GitHub cron 仍可能延迟或丢弃任务，不能保证秒级执行。完整说明见 [GitHub Actions 使用说明](docs/GITHUB_ACTIONS.md)。

## Docker 自托管

Docker 模式适合希望在自己服务器上运行 Worker 和局域网 WebUI 的用户。它需要已经合法取得、与本人账户匹配的 `credentials.xml` 和 `device.xml`。

```bash
cp .env.example .env
python3 tools/init_data.py --data-dir ./data
cp /your/authorized/path/credentials.xml ./data/credentials.xml
cp /your/authorized/path/device.xml ./data/device.xml
chmod 600 ./data/*
docker compose up -d --build
```

打开 `http://127.0.0.1:17820/`，先执行只读认证检查。默认 `POVO_ENABLE_REDEMPTION=0`；确认会话和时间无误后，才在 `.env` 中改为：

```dotenv
POVO_ENABLE_REDEMPTION=1
```

## 安全边界

- 不要在 Issue、Pull Request、工作流普通输入、日志或截图中提交认证信息。
- 不要把 `.env`、`data/`、XML、兑换码或解密后的状态加入 Git。
- Dashboard 只应绑定回环地址或可信内网；公网访问必须加认证 HTTPS 反向代理。
- 一次提交结果无法确认时，不要连续重跑。
- 详细要求见 [SECURITY.md](SECURITY.md)。

## 已知限制

- 接口未公开，App 更新后可能失效；
- 账户同时存在多个 add-on 时可能返回 `MULTIPLE_ADDONS_FOUND`，目前尚未解决；
- GitHub 定时任务可能排队或延迟；
- 当前无法在登录后可靠读取现有 promo 的到期时间；
- GitHub 两阶段工作流仍需要用户在 15 分钟内手动提供邮件验证码；
- 本项目不能视为生产级或运营商官方工具。

## 测试

```bash
python3 -m unittest discover -s tests -v
docker compose config
docker compose build
```

## 贡献者

项目贡献记录见 [CONTRIBUTORS.md](CONTRIBUTORS.md)。[@codex](https://github.com/codex) 作为 OpenAI 的 AI 编程助手参与了架构、实现、测试、安全检查和多语言文档，但不是人工维护者。

## 开源协议与免责声明

本项目采用 [MIT License](LICENSE)。接口、字段和业务规则可能变化；错误使用可能造成会话失效、重复提交或账户限制。项目作者不提供任何明示或暗示担保，使用者自行承担风险。
