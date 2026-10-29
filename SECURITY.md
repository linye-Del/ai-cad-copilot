# Security Policy

## Supported versions

| Version | Supported |
|---|---|
| 0.2.x preview | Yes, best effort |
| Earlier v1.0.0 local tag | No |

## Reporting a vulnerability

Please use **GitHub Security Advisories** for this repository:

<https://github.com/linye-Del/ai-cad-copilot/security/advisories/new>

Do not open a public issue containing:

- API keys, tokens, passwords, proxy credentials;
- personal paths, usernames, desktop screenshots;
- working exploit details for the local bridge.

Include the affected version/commit, a minimal reproduction, and impact. You will receive a
best-effort response from the maintainer.

## Security model and non-goals

AI CAD Copilot is a **local, single-user prototype**:

- The backend binds to `127.0.0.1` by default and has **no authentication**.
- The FreeCAD add-on only accepts `ws://127.0.0.1` / `localhost` gateway URLs.
- CAD operations are allow-listed typed operations, not arbitrary Python.
- Do not expose the backend to a LAN or the public internet.
- Legacy model generation starts a local `FreeCADCmd` subprocess with a sanitized environment.

These controls are not a substitute for OS-level isolation, authentication, authorization,
or multi-tenant hardening.

## Secrets

- `.env` is ignored and must never be committed.
- If a secret is committed, rotate it first, then assess history cleanup. Removing the current
  file is not sufficient.
- `THIRD_PARTY_NOTICES.md` and `docs/github_release_audit.md` record the release-time scan.

## Optional AGPL component

PyMuPDF is **not** installed by default. It is AGPL-3.0/commercial dual-licensed. Enabling
`requirements-pdf.txt` is an explicit opt-in; assess the license obligations for your use case.
