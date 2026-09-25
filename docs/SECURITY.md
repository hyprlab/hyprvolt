# Security

## Reporting a problem

Report security problems privately, through GitHub's
[private vulnerability reporting](https://github.com/hyprlab/hyprprem/security/advisories/new)
(Security, then "Report a vulnerability"), or by email to
hyprlab@proton.me. Please don't open a public issue.

Expect a reply within a week. A fix ships as an urgent patch release
([RELEASING.md](RELEASING.md#urgent-patches)), the reporter is credited in the
changelog unless they ask not to be, and an embargo the reporter proposes is
respected, ending when the fixed release ships. Serious issues get a GitHub
Security Advisory, and a CVE where one is warranted.

Only the latest stable release receives security fixes.

## What the app defends against

| Threat | Defense |
| --- | --- |
| Cross-site request forgery | A per-session token on every POST, PUT, PATCH and DELETE, compared in constant time |
| Cross-site scripting | Jinja autoescaping; user text rendered with `textContent` in JavaScript; foreign HTML through an allowlist sanitizer |
| Clickjacking | `X-Frame-Options: DENY` |
| Password guessing | Salted hashes (Werkzeug's scrypt/pbkdf2); a throttle of eight failures per account and address per fifteen minutes; optional Cloudflare Turnstile, turned on in Settings > Security only after a challenge passes with the new keys |
| Open redirects | The post-sign-in `next` must be a same-site path |
| Session theft | `HttpOnly` and `SameSite=Lax` cookies; `Secure` with `SESSION_COOKIE_SECURE=1` |
| Reading other accounts' data | Every record route checks ownership and answers 404, not 403 |
| A default password | There is none: the first account is created in the setup wizard |
| Stale pages | HTML is served `no-store` |
| Running as root | The container runs as an unprivileged user |

## Out of scope

- The app sends no email, so there is no self-service password reset; an
  admin resets passwords in Settings, or with `flask reset-password`.
- There is no two-factor authentication yet.
- TLS is the reverse proxy's job.
- The in-memory sign-in throttle resets when the container restarts.
- The Turnstile secret is stored in the database unencrypted, like every other
  setting; whoever can read the volume can read it. It is never sent to a
  browser.
