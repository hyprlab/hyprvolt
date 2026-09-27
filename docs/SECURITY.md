# Security

## Reporting a problem

Report security problems privately, through GitHub's
[private vulnerability reporting](https://github.com/hyprlab/hyprvolt/security/advisories/new)
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
| Doing more than a role allows | Every route declares the role it needs (viewer, editor, admin), checked on the server; the app refuses to start with a route that declares none |
| Files that run script | Attachments are stored under generated names, served with `Content-Security-Policy: sandbox` (PDFs excepted) and `nosniff`; anything but images, PDFs and plain text downloads |
| HTML in documents | Markdown is rendered, then passed through the allowlist sanitizer; `[[slug]]` labels are escaped |
| A default password | There is none: the first account is created in the setup wizard |
| Stale pages | HTML is served `no-store` |
| Running as root | The container runs as an unprivileged user |
| A sign-in outliving a restore | A restore changes the session epoch in every sign-in id, so sessions and remember-me cookies from before it end, and nobody lands on another account with the same id |
| A hostile backup upload | Admins only; the archive is checked before anything is replaced: no paths outside its folder, no links or devices, extracted with Python's `data` filter, a SQLite integrity check, an admin account required; an attachment is only ever read from a name the app made, so an edited database can't point one at another file |
| A stolen database or backup | Secrets are encrypted (Fernet: AES-128-CBC with an HMAC) with a key that is not in the database and not in `flask backup`'s archive |
| A leaked API token | Only a SHA-256 of each token is stored; a token can be limited to reading, and whatever its role can't reveal a secret, download the secrets key or a backup, restore, or make tokens; it is revoked at once in Settings, a revoked one can be brought back only within ten minutes, and a restore revokes them all |
| A stolen session or remember-me cookie | Sign-in ids carry a stamp of the password: changing or resetting it ends every other session and cookie of the account |
| The certificate check as a way into the network | Only editors set a certificate's address or press Check now; the check opens a connection, makes a TLS handshake and reads the certificate presented, sending no request, following no redirect and keeping nothing but the certificate's details; one address at a time, with a five-second timeout, and the worker checks each certificate at most once a day |
| Seeing a password without cause | Beyond admins, secrets are a permission given per account; each reveal and copy is written to the record's history with who and when; API tokens can't read them |

## Out of scope

- The app sends no email, so there is no self-service password reset; an
  admin resets passwords in Settings, or with `flask reset-password`.
- There is no two-factor authentication yet.
- TLS is the reverse proxy's job.
- The certificate check reaches whatever the app's server can reach, as a
  port scanner could: an editor can learn from its answer whether a host and
  port on the internal network accept connections and speak TLS.
- The in-memory sign-in throttle resets when the container restarts.
- The Turnstile secret is stored in the database unencrypted, like every other
  setting; whoever can read the volume can read it. It is never sent to a
  browser.
- Documentation is readable by every signed-in account. Keep credentials out
  of notes and documents: they go in a record's Secrets tab.
