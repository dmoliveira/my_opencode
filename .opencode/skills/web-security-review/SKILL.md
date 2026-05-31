---
name: web-security-review
description: Use when reviewing or hardening web app auth, authorization, session, input handling, HTML rendering, upload, or state-changing endpoint security for issues such as IDOR, XSS, CSRF, secret exposure, or multi-tenant access bugs.
license: MIT
compatibility: opencode claude-code
---

## Goal

Review implemented web application code and flows from a bug-hunter perspective, then surface the highest-risk security findings without drifting into generic style review or broad speculative checklists.

## Use When

- the user asks for a security review, scan, audit, or hardening pass
- the change touches auth, sessions, authorization, tenant isolation, or role checks
- the task includes user-controlled input, HTML rendering, uploads, redirects, cookies, or state-changing endpoints
- a web PR, route, controller, API, middleware, or template needs blocker-first security review before ship

## Do Not Use When

- the task is non-web or has no meaningful security surface
- the work is still early planning with no implementation or diff to review
- the user only wants general code quality or UX feedback
- the main need is browser execution rather than code-level security reasoning

## First Steps

- Identify the trust boundaries: unauthenticated user, authenticated user, admin, organization, tenant, external service.
- Identify the data and actions that must be protected.
- Review the current diff, touched routes, and validation evidence before broadening scope.
- Prefer concrete exploit paths over generic best-practice lists.
- Prefer the touched surface first; only widen the review when the same trust boundary clearly spans other files or routes.

## Priority Review Areas

### Access control and tenant isolation
- verify resource ownership on every read/write path
- check organization or tenant scoping at the data layer
- look for IDOR, horizontal access, and vertical privilege escalation
- check mass-assignment or over-broad update payloads
- verify role or membership changes invalidate stale access appropriately

### Session, auth, and secrets
- check cookie flags, token lifetime, revocation, and logout/deactivation handling
- ensure secrets and server credentials stay out of client-visible code and logs
- verify password reset, email verification, OAuth, and login flows for abuse paths

### XSS and unsafe rendering
- inspect every user-controlled input that reaches HTML, markdown, templates, PDFs, email content, or admin viewers
- verify context-appropriate escaping or sanitization
- check rich text, markdown, SVG, filenames, query params, and third-party content
- call out dangerous uses of raw HTML sinks or framework escape bypasses

### CSRF and state-changing requests
- verify CSRF protection on every state-changing endpoint that uses cookies or ambient auth
- check SameSite, Secure, and HttpOnly cookie posture
- flag GET endpoints with side effects
- verify login and pre-auth endpoints are not skipped from CSRF reasoning by accident

### Input handling and unsafe file/data flows
- check upload validation, content-type trust, path handling, redirect targets, and parser assumptions
- inspect deserialization, template evaluation, shell/process calls, and query construction when relevant

## Working Rules

- Prioritize exploitable findings and broken trust boundaries before lower-risk hygiene.
- Report only issues you can tie to a concrete attack path, missing control, or unsafe assumption.
- Distinguish definite vulnerability, plausible risk, and follow-up hardening clearly.
- Prefer file- and route-specific findings over a generic checklist dump.
- Keep remediation minimal and practical; do not propose broad rewrites unless required for safety.
- Limit routine output to the highest-value findings instead of exhaustively restating every category checked.
- When user-visible behavior matters, pair this skill with browser validation or ship-readiness review instead of guessing from code alone.

## Output

When reporting findings:

1. Start with overall verdict: `blocked`, `needs follow-up`, or `no blocker found`.
2. List blocker findings first, then non-blocking hardening follow-ups only if they materially matter.
3. For each finding, include:
   - affected file/path or route
   - issue type
   - why it is exploitable or risky
   - smallest sensible remediation
4. If no real finding exists, say so plainly instead of padding the report.

## Evidence / Done

- Security findings are tied to specific code paths or behaviors.
- Highest-risk auth/input/rendering issues were checked for the touched surface.
- Blockers are separated from hardening follow-ups.
- Recommendations preserve functionality while tightening security.

## References

- `AGENTS.md`
- `.opencode/skills/review-ship-readiness/SKILL.md`
- `https://github.com/BehiSecc/VibeSec-Skill/blob/main/SKILL.md`
