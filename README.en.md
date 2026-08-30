# povo2.0 promo automation (experimental)

[简体中文](README.md) | [繁體中文](README.zh-Hant.md) | [日本語](README.ja.md) | English

An unofficial, self-hosted scheduler for povo2.0 promo codes. It can use GitHub Actions to perform email OTP login, store the session in an encrypted bundle, and run on a schedule. A Docker deployment with a LAN management dashboard is also available.

This repository is an isolated deployment generated from the public source. It keeps encrypted account state and Repository Secrets separate while shared code and documentation remain maintained upstream.

> [!NOTE]
> This private repository is the maintainer's isolated small-account runner and stores that account's re-encrypted `state/session.enc`. Public source and updates remain canonical in [`povo2.0-promo-automation`](https://github.com/azarashi11037/povo2.0-promo-automation).

> [!WARNING]
> This project uses undocumented APIs that may change with povo2.0 app updates. It is not supported or endorsed by povo2.0/KDDI. Use only accounts you are authorized to manage and review the applicable terms yourself. The project does not bypass OTP, TLS verification, root restrictions, or access controls.

## What the user provides

The recommended GitHub Actions flow needs only:

1. the povo2.0 login email address;
2. the latest six-digit OTP received by email;
3. a reusable promo code.

These values are not entered together in a public form. To keep the email address, OTP, and promo code out of Actions history, they are stored as GitHub Repository Secrets in two stages. After initialization, the email, OTP, and promo-code secrets can be deleted; only `POVO_BUNDLE_KEY` must remain.

## Implemented features

- Two-stage email OTP login without a continuously running Android VM
- AES-256-GCM encryption for the session, device data, promo code, and schedule state
- Plaintext available only inside an ephemeral GitHub-hosted runner
- Periodic session refresh and at most one submission after an event becomes due
- Fail-closed `unknown` state when the result cannot be confirmed
- Allowlist-based logs that omit tokens, device IDs, user IDs, and promo codes
- Optional import of an existing authorized Android session
- Docker worker and a dashboard bound to `127.0.0.1` by default
- CI syntax checks, unit tests, Compose validation, and Docker builds

## GitHub Actions quick start

1. Fork this repository.
2. In **Settings → Actions → General → Workflow permissions**, allow Actions to read and write repository contents.
3. In **Settings → Secrets and variables → Actions**, create:
   - `POVO_BUNDLE_KEY`: at least 20 characters; a random value is recommended.
   - `POVO_LOGIN_EMAIL`: your povo2.0 login email address.
4. Run **Start povo2.0 email login** and wait for the OTP email.
5. Immediately create:
   - `POVO_LOGIN_OTP`: the six-digit code from the latest email.
   - `POVO_PROMO_CODE`: the promo code.
6. Within 15 minutes, run **Finish povo2.0 login and redeem once**. Running this workflow explicitly confirms the first redemption. After confirmed success, the next due time is automatically set to 7 days and 1 minute after that success; no date entry is required.
7. After `state/session.enc` appears, delete `POVO_LOGIN_EMAIL`, `POVO_LOGIN_OTP`, and `POVO_PROMO_CODE`. Keep `POVO_BUNDLE_KEY`.

The current login/account-check endpoint has no verified, reliable promo-expiration field. JWT expiry is only the short-lived login-token expiry and must not be treated as the plan expiry. The recommended flow therefore starts from the confirmed first-redemption time instead of guessing or misreading an expiration date.

The **povo2.0 session keeper** then checks hourly away from the top of the hour. Only when the encrypted target is within 65 minutes does it refresh the session and wait inside the runner, submitting at most once after the target minute arrives. Other checks neither call the povo API nor commit files. GitHub cron can still be delayed or dropped and cannot guarantee second-level timing. See the [GitHub Actions guide](docs/GITHUB_ACTIONS.en.md).

## Docker self-hosting

Docker mode is intended for users who want the worker and LAN WebUI on their own server. It requires authorized `credentials.xml` and `device.xml` files that match the user's own account.

```bash
cp .env.example .env
python3 tools/init_data.py --data-dir ./data
cp /your/authorized/path/credentials.xml ./data/credentials.xml
cp /your/authorized/path/device.xml ./data/device.xml
chmod 600 ./data/*
docker compose up -d --build
```

Open `http://127.0.0.1:17820/` and run the read-only authentication check first. Redemption is disabled by default with `POVO_ENABLE_REDEMPTION=0`. Only after verifying the session and schedule should `.env` be changed to:

```dotenv
POVO_ENABLE_REDEMPTION=1
```

## Security boundary

- Never submit authentication material in issues, pull requests, normal workflow inputs, logs, or screenshots.
- Never commit `.env`, `data/`, XML files, promo codes, or decrypted state.
- Bind the dashboard only to loopback or a trusted LAN. Remote exposure requires an authenticated HTTPS reverse proxy.
- Do not repeatedly rerun a submission whose result is uncertain.
- See [SECURITY.md](SECURITY.md) for details.

## Known limitations

- Undocumented APIs may stop working after an app update.
- Accounts with multiple add-ons may return `MULTIPLE_ADDONS_FOUND`; this is unresolved.
- GitHub scheduled jobs may queue or run late.
- The expiration of an existing promo cannot currently be read reliably after login.
- The user must still provide the email OTP manually within 15 minutes.
- This is not a production-grade or carrier-supported tool.

## Contributors

See [CONTRIBUTORS.md](CONTRIBUTORS.md). OpenAI's AI coding assistant [@codex](https://github.com/codex) assisted with architecture, implementation, testing, security review, and multilingual documentation. It is not a human maintainer.

## License and disclaimer

This project is licensed under the [MIT License](LICENSE). APIs, fields, and business rules may change. Misuse can invalidate sessions, cause duplicate submissions, or trigger account restrictions. The software is provided without warranty; users assume all risk.
