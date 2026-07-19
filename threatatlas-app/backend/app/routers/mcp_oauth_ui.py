"""First-party browser login/consent page for the /mcp OAuth 2.1 flow.

ThreatAtlasOAuthProvider.authorize() stashes the validated authorization
request in a McpPendingAuthorization row and redirects the browser here
instead of to a third-party IdP — this is what lets "click Connect in your
MCP client" end with "logged into ThreatAtlas", nothing to copy.

Mounted on the main app (not under the root-mounted MCP sub-app), so these
paths must be registered before app.mount("/", mcp_app) in app/main.py.

The markup below intentionally mirrors the design tokens and layout of the
frontend's Login page (frontend/src/pages/Login.tsx + src/index.css) so an
end user isn't jarred by a visually distinct page mid-OAuth-flow.
"""

import html
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from mcp.server.auth.provider import construct_redirect_uri
from sqlalchemy.orm import Session

from app.auth.password import verify_password
from app.database import get_db
from app.models import User
from app.models.mcp_oauth import McpAuthorizationCode, McpOAuthClient, McpPendingAuthorization

router = APIRouter(tags=["mcp-oauth"])

AUTH_CODE_TTL = timedelta(minutes=10)

# lucide "network" icon (used in the header badge on the app's own login page)
_NETWORK_ICON = """
<svg xmlns="http://www.w3.org/2000/svg" width="32" height="32" viewBox="0 0 24 24"
     fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
  <rect x="16" y="16" width="6" height="6" rx="1"/>
  <rect x="2" y="16" width="6" height="6" rx="1"/>
  <rect x="9" y="2" width="6" height="6" rx="1"/>
  <path d="M5 16v-3a1 1 0 0 1 1-1h12a1 1 0 0 1 1 1v3"/>
  <path d="M12 12V8"/>
</svg>
"""

_ALERT_ICON = """
<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24"
     fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"
     style="flex-shrink:0">
  <circle cx="12" cy="12" r="10"/>
  <line x1="12" y1="8" x2="12" y2="12"/>
  <line x1="12" y1="16" x2="12.01" y2="16"/>
</svg>
"""

_PAGE_STYLES = """
:root {
  --background: #faf9f7;
  --foreground: #000000;
  --card: #ffffff;
  --card-foreground: #000000;
  --primary: #01418d;
  --primary-foreground: #ffffff;
  --muted: #eee9df;
  --muted-foreground: #9f9b93;
  --destructive: #e84c56;
  --destructive-foreground: #ffffff;
  --border: #dad4c8;
  --input: #dad4c8;
  --ring: #01418d;
  --font-sans: 'Plus Jakarta Sans Variable', 'Plus Jakarta Sans', ui-sans-serif, system-ui, -apple-system, Arial, sans-serif;
  --shadow-lg: rgba(0,0,0,0.12) 0px 2px 4px, rgba(0,0,0,0.06) 0px -1px 2px inset, rgba(0,0,0,0.06) 0px -0.5px 1px;
}
@media (prefers-color-scheme: dark) {
  :root {
    --background: #1a1916;
    --foreground: #faf9f7;
    --card: #242320;
    --card-foreground: #faf9f7;
    --primary: #3bd3fd;
    --primary-foreground: #000000;
    --muted: #1f1e1b;
    --muted-foreground: #9f9b93;
    --destructive: #fc7981;
    --destructive-foreground: #000000;
    --border: #3a3835;
    --input: #3a3835;
    --ring: #3bd3fd;
  }
}
* { box-sizing: border-box; }
body {
  margin: 0;
  min-height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 1rem;
  background: linear-gradient(to bottom right, var(--background), color-mix(in srgb, var(--muted) 40%, var(--background)), var(--background));
  color: var(--foreground);
  font-family: var(--font-sans);
  line-height: 1.5;
}
.card {
  width: 100%;
  max-width: 26rem;
  background: var(--card);
  color: var(--card-foreground);
  border: 1px solid color-mix(in srgb, var(--border) 60%, transparent);
  border-radius: 1rem;
  box-shadow: var(--shadow-lg);
  animation: fadeInUp 0.4s ease-out both;
}
.card-header { text-align: center; padding: 2rem 2rem 1.5rem; }
.card-content { padding: 0 2rem 2rem; }
.icon-badge {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 4rem;
  height: 4rem;
  margin: 0 auto 1rem;
  border-radius: 1rem;
  background: linear-gradient(to bottom right, var(--primary), color-mix(in srgb, var(--primary) 80%, transparent));
  color: var(--primary-foreground);
  box-shadow: var(--shadow-lg);
}
h1.title {
  margin: 0;
  font-size: 1.875rem;
  font-weight: 800;
  letter-spacing: -0.02em;
}
p.subtitle { margin: 0.5rem 0 0; color: var(--muted-foreground); font-size: 1rem; }
form { display: flex; flex-direction: column; gap: 1.25rem; }
.field { display: flex; flex-direction: column; gap: 0.5rem; }
label { font-size: 0.875rem; font-weight: 600; }
input[type="email"], input[type="password"] {
  height: 2.75rem;
  width: 100%;
  padding: 0 0.75rem;
  font-size: 0.9375rem;
  font-family: inherit;
  color: var(--foreground);
  background: transparent;
  border: 1px solid color-mix(in srgb, var(--border) 60%, transparent);
  border-radius: 0.5rem;
  outline: none;
  transition: border-color 0.15s ease;
}
input[type="email"]:focus, input[type="password"]:focus {
  border-color: var(--ring);
  box-shadow: 0 0 0 3px color-mix(in srgb, var(--ring) 25%, transparent);
}
.btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 0.5rem;
  width: 100%;
  height: 2.75rem;
  border-radius: 0.5rem;
  border: 1px solid transparent;
  font-size: 0.9375rem;
  font-weight: 500;
  font-family: inherit;
  cursor: pointer;
  transition: all 0.15s ease;
}
.btn-primary {
  background: var(--primary);
  color: var(--primary-foreground);
  box-shadow: var(--shadow-lg);
}
.btn-primary:hover { background: color-mix(in srgb, var(--primary) 80%, transparent); }
.btn-outline {
  background: var(--background);
  color: var(--foreground);
  border-color: color-mix(in srgb, var(--border) 60%, transparent);
}
.btn-outline:hover { background: var(--muted); }
.btn-row { display: flex; gap: 0.5rem; }
.btn-row .btn { width: auto; flex: 1; }
.alert-error {
  display: flex;
  align-items: center;
  gap: 0.625rem;
  font-size: 0.875rem;
  color: var(--destructive);
  background: color-mix(in srgb, var(--destructive) 10%, transparent);
  border: 1px solid color-mix(in srgb, var(--destructive) 20%, transparent);
  border-radius: 0.5rem;
  padding: 0.875rem;
}
.footnote { margin-top: 1.5rem; text-align: center; font-size: 0.875rem; color: var(--muted-foreground); }
.footnote strong { color: var(--foreground); }
@keyframes fadeInUp {
  from { opacity: 0; transform: translateY(16px) scale(0.98); }
  to   { opacity: 1; transform: translateY(0) scale(1); }
}
"""


def _shell(title: str, body: str) -> str:
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>{html.escape(title)}</title>
  <style>{_PAGE_STYLES}</style>
</head>
<body>
  <div class="card">
    {body}
  </div>
</body>
</html>"""


def _load_pending(db: Session, req: str) -> McpPendingAuthorization | None:
    pending = db.query(McpPendingAuthorization).filter(McpPendingAuthorization.id == req).first()
    if pending is None or pending.expires_at < datetime.now(timezone.utc):
        return None
    return pending


def _expired_response() -> HTMLResponse:
    body = f"""
    <div class="card-header">
      <div class="icon-badge">{_NETWORK_ICON}</div>
      <h1 class="title">Link expired</h1>
      <p class="subtitle">This authorization request has expired. Please retry from your MCP client.</p>
    </div>
    """
    return HTMLResponse(_shell("ThreatAtlas — Expired", body), status_code=400)


def _login_page(req: str, error: str | None = None) -> str:
    req_attr = html.escape(req, quote=True)
    error_html = (
        f'<div class="alert-error">{_ALERT_ICON}<span>{html.escape(error)}</span></div>' if error else ""
    )
    body = f"""
    <div class="card-header">
      <div class="icon-badge">{_NETWORK_ICON}</div>
      <h1 class="title">OWASP ThreatAtlas</h1>
      <p class="subtitle">Sign in to connect your MCP client</p>
    </div>
    <div class="card-content">
      <form method="post" action="/oauth/login">
        <input type="hidden" name="req" value="{req_attr}" />
        <div class="field">
          <label for="email">Email</label>
          <input id="email" type="email" name="email" placeholder="you@example.com" required autofocus />
        </div>
        <div class="field">
          <label for="password">Password</label>
          <input id="password" type="password" name="password" placeholder="Enter your password" required />
        </div>
        {error_html}
        <button type="submit" class="btn btn-primary">Sign In</button>
      </form>
    </div>
    """
    return _shell("ThreatAtlas — Sign in", body)


def _consent_page(req: str, client: McpOAuthClient | None, user: User) -> str:
    req_attr = html.escape(req, quote=True)
    client_label = html.escape((client.client_name or client.client_id) if client else "An application")
    user_email = html.escape(user.email)
    body = f"""
    <div class="card-header">
      <div class="icon-badge">{_NETWORK_ICON}</div>
      <h1 class="title">Authorize access</h1>
      <p class="subtitle"><strong>{client_label}</strong> wants to access your ThreatAtlas account
      (<strong>{user_email}</strong>).</p>
    </div>
    <div class="card-content">
      <form method="post" action="/oauth/consent">
        <input type="hidden" name="req" value="{req_attr}" />
        <div class="btn-row">
          <button type="submit" name="action" value="deny" class="btn btn-outline">Deny</button>
          <button type="submit" name="action" value="approve" class="btn btn-primary">Approve</button>
        </div>
      </form>
    </div>
    """
    return _shell("ThreatAtlas — Authorize", body)


@router.get("/oauth/login", response_class=HTMLResponse)
def oauth_login_form(req: str, request: Request, db: Session = Depends(get_db)):
    pending = _load_pending(db, req)
    if pending is None:
        return _expired_response()

    user_id = request.session.get("user_id")
    if user_id:
        user = db.query(User).filter(User.id == user_id, User.is_active.is_(True)).first()
        if user is not None:
            client = db.query(McpOAuthClient).filter(McpOAuthClient.client_id == pending.client_id).first()
            return HTMLResponse(_consent_page(req, client, user))

    return HTMLResponse(_login_page(req))


@router.post("/oauth/login", response_class=HTMLResponse)
async def oauth_login_submit(request: Request, db: Session = Depends(get_db)):
    form = await request.form()
    req = str(form.get("req", ""))
    email = str(form.get("email", ""))
    password = str(form.get("password", ""))

    pending = _load_pending(db, req)
    if pending is None:
        return _expired_response()

    user = db.query(User).filter(User.email == email).first()
    if user is None or not user.hashed_password or not verify_password(password, user.hashed_password) or not user.is_active:
        return HTMLResponse(_login_page(req, error="Incorrect email or password"), status_code=401)

    request.session["user_id"] = user.id

    client = db.query(McpOAuthClient).filter(McpOAuthClient.client_id == pending.client_id).first()
    return HTMLResponse(_consent_page(req, client, user))


@router.post("/oauth/consent")
async def oauth_consent(request: Request, db: Session = Depends(get_db)):
    form = await request.form()
    req = str(form.get("req", ""))
    action = str(form.get("action", ""))

    pending = _load_pending(db, req)
    if pending is None:
        return _expired_response()

    user_id = request.session.get("user_id")
    user = db.query(User).filter(User.id == user_id, User.is_active.is_(True)).first() if user_id else None
    if user is None:
        return RedirectResponse(f"/oauth/login?req={req}", status_code=303)

    redirect_uri = pending.redirect_uri
    state = pending.state

    if action != "approve":
        db.delete(pending)
        db.commit()
        return RedirectResponse(
            construct_redirect_uri(redirect_uri, error="access_denied", state=state), status_code=302
        )

    code = secrets.token_urlsafe(32)
    db.add(
        McpAuthorizationCode(
            code=code,
            client_id=pending.client_id,
            subject=str(user.id),
            redirect_uri=redirect_uri,
            redirect_uri_provided_explicitly=pending.redirect_uri_provided_explicitly,
            scopes=pending.scopes,
            code_challenge=pending.code_challenge,
            resource=pending.resource,
            expires_at=datetime.now(timezone.utc) + AUTH_CODE_TTL,
        )
    )
    db.delete(pending)
    db.commit()

    return RedirectResponse(construct_redirect_uri(redirect_uri, code=code, state=state), status_code=302)
