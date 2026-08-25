# Frontend Embed V1 Hardening Report

**Repository:** `NeoKirito/DbQuery`

**Base:** `df6ec86cab8eb07c2112c59374fd5ff99c29998a`

**Source branch:** `origin/feat/frontend-embed-v1` at `14f4171d44b70f105a10849e74e02a8d261d4594`

**Working branch:** `fix/frontend-embed-v1-hardening`

**Final code HEAD:** `dbb355fd6d426d1b947823c17646970f2fddd3bc` (`fix(web): harden frontend embed session isolation`)

**Ahead / Behind at report generation:** `1 / 0` relative to `origin/feat/frontend-embed-v1`.

**Worktree at report generation:** clean before creation of this audit report. The report itself is committed separately after review of its content.

## Conclusion

> **READY_FOR_MERGE**

The two required P0 issues are closed in code and covered by Flask regression tests plus a real Chromium smoke test. The real browser path uses a PEIS-like same-origin host, mounts DBQuery below `/dbquery`, performs a same-origin session probe without an `Origin` header, completes frontend login, loads a live iframe page, and verifies that DBQuery logout preserves the host `session` cookie. No SQL Server is started or contacted; authentication and form loading use a controlled in-process fixture so that browser, Cookie, `SCRIPT_NAME`, iframe and fetch behavior remain real Chromium behavior.

## P0-1: Cookie Isolation — PASS

DBQuery now defaults to the independent `dbquery_session` Cookie name. `DBQUERY_SESSION_COOKIE_NAME` overrides the name, while `DBQUERY_SESSION_COOKIE_PATH` supports both standalone `/` and the recommended `/dbquery` reverse-proxy scope. The application explicitly configures `SESSION_COOKIE_NAME`, `SESSION_COOKIE_PATH`, `SESSION_COOKIE_HTTPONLY`, `SESSION_COOKIE_SAMESITE` and `SESSION_COOKIE_SECURE`.

| Evidence | Result |
|---|---|
| Host generic `session=PEIS_SESSION_VALUE` survives DBQuery frontend login | PASS |
| DBQuery frontend login sets `dbquery_session` with `HttpOnly` | PASS |
| Embed logout invalidates DBQuery session only | PASS |
| `Secure=true` emits `Secure`; `SameSite=None` is explicit | PASS |
| Chromium Cookie store shows host `/` cookie and DBQuery `/dbquery` cookie separately | PASS |

A warning is logged when `DBQUERY_SESSION_COOKIE_SAMESITE=None` is configured without `DBQUERY_SESSION_COOKIE_SECURE=true`, because cross-site browser Cookies require Secure transport.

## P0-2: Same-Origin `GET /session` — PASS

`GET /api/integration/session` continues to require an exact configured `Origin` whenever the header is present. When the header is absent, only that non-mutating endpoint may use the narrow same-origin fallback: `Sec-Fetch-Site: same-origin` is accepted, `cross-site` and `same-site` are denied, and legacy fallback permits only an explicitly allowed request host, an exact same-origin Referer, or an existing DBQuery session. `POST /frontend-login`, `POST /embed-url` and `POST /logout` retain the strict exact-Origin allowlist and reject missing or hostile Origins.

| Evidence | Result |
|---|---|
| Same-origin session probe without `Origin` and with `Sec-Fetch-Site: same-origin` | PASS |
| Legacy no-Fetch-Metadata fallback only for configured host | PASS |
| Cross-site no-Origin session probe | DENIED as expected |
| Hostile Origin session probe and login | DENIED as expected |
| Missing-Origin frontend login | DENIED as expected |
| Chromium SDK session request contains no `Origin` header and succeeds | PASS |

## Browser Smoke — PASS

The smoke test is `tests/test_frontend_embed_browser.py::test_same_origin_subpath_embed_smoke_in_real_chromium`. It starts a local PEIS-like WSGI host at `/host` and mounts the real DBQuery Flask application through `DispatcherMiddleware` at `/dbquery`. It launches the installed Chromium executable using Playwright and calls `DBQueryEmbed.mount()` from a host page.

The smoke verifies loading `dbquery-embed.js`, unauthenticated session probing, frontend authentication, `dbquery_session` issuance, context-only iframe URL issuance, actual iframe query controls, no password in the DOM or iframe URL, no browser storage use, preservation of the host cookie, and isolated logout. It deliberately creates no screenshots, traces, HARs or browser-report files.

## P1 Hardening

| Topic | Result | Evidence |
|---|---|---|
| Proxy rate-limit granularity | PASS | Failed-login key is normalized `client_ip|username`; tests prove user A can be limited without immediately blocking user B at the same address. |
| Forwarded client IP | PASS | `DBQUERY_TRUST_PROXY_FOR` is a separate explicit one-hop opt-in; `X-Forwarded-For` is ignored by default. `DBQUERY_TRUST_PROXY_PREFIX` remains independent. |
| URL business-value exposure | PASS | `/embed/<form>` rejects bare form parameter names. `/api/integration/embed-url` creates a high-entropy, short-lived, session/user/form-bound `ctx`; iframe URLs contain no `tjh` or other validated business values. |
| Context reuse / expiry | PASS | Tests deny a second session and expired Context. URLs with appended business/hidden values are rejected. |
| `external_allowed` and hidden fields | PASS | Server validates external values before context issue; hidden and non-external fields are not accepted. |
| `options_sql` | PASS | Existing serialization/render regression proves dynamic metadata remains browser-safe and does not expose SQL. |
| SameSite / Secure | PASS | Explicit cookie config and test coverage; documentation warns about `None` without Secure. |
| Documentation priority | PASS | README and legacy frontend-ticket guide now rank Backend Signed SSO first, Embed V1 second, and legacy ticket third. |

## Regression Coverage

| Area | Result |
|---|---|
| Desktop login and form editor | PASS in full Python suite (offscreen Qt) |
| Backend Signed SSO | PASS in existing host integration tests |
| Legacy frontend-ticket | PASS in existing frontend integration tests |
| Dynamic options and `options_sql` non-exposure | PASS |
| Query and export flows | PASS in existing Web regression suite |
| Existing forms, parser and `web_enabled` controls | PASS |

## Test and Hygiene Gates

| Gate | Result |
|---|---|
| `QT_QPA_PLATFORM=offscreen python -m pytest -q` | **91 passed, 0 failed, 0 skipped** |
| Real Chromium browser smoke | **PASS** |
| `python -m compileall -q .` | PASS |
| `node --check static/js/dbquery-embed.js` | PASS |
| `node --check static/js/app.js` | PASS |
| `git diff --check` | PASS |
| High-confidence secret / password / token scan | PASS |
| Tracked `config.ini`, browser reports, screenshots, traces, HARs, Python cache | None found |

## Deployment Notes

The recommended deployment is `https://peis.example.com/` for PEIS and `https://peis.example.com/dbquery/` for DBQuery. Configure an isolated Cookie name and scoped path through the environment, enable Secure transport behind the controlled HTTPS proxy, and enable only the proxy trust switches that correspond to a real, trusted proxy behavior. The exact recommended variables and security boundary are documented in [README.md](README.md).

No production domain, user password, token, database URI, local `config.ini`, browser screenshot, trace or SQL Server connection was introduced into this branch.
