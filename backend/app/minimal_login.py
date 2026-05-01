"""Minimal HTML login page when Next.js static export is not bundled.

Served only if ``frontend/out`` is missing — see ``app.main`` registration.
Matches ``aoe_auth_token`` storage in ``frontend/src/lib/auth.ts``.
"""

from __future__ import annotations

import json


def render_minimal_login_html(service_url_path_prefix: str) -> str:
    """Return self-contained HTML that POSTs to the login API under ``prefix``."""
    prefix = (service_url_path_prefix or "").rstrip("/")
    api_login = f"{prefix}/api/v1/auth/login" if prefix else "/api/v1/auth/login"
    home = f"{prefix}/" if prefix else "/"

    api_js = json.dumps(api_login)
    home_js = json.dumps(home)
    pfx_js = json.dumps(prefix)

    # Single line breaks only where needed for readability; no user-controlled HTML.
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1"/>
  <title>AOE — Sign in</title>
  <style>
    body {{
      font-family: system-ui, sans-serif;
      max-width: 22rem;
      margin: 3rem auto;
      padding: 0 1rem;
    }}
    h1 {{ font-size: 1.25rem; }}
    label {{ display: block; margin-top: 0.75rem; font-size: 0.875rem; }}
    input {{ width: 100%; box-sizing: border-box; margin-top: 0.25rem; padding: 0.5rem; }}
    button {{ margin-top: 1rem; width: 100%; padding: 0.5rem 1rem; cursor: pointer; }}
    .err {{ color: #b91c1c; font-size: 0.875rem; margin-top: 0.5rem; }}
    .hint {{ font-size: 0.75rem; color: #64748b; margin-top: 1rem; }}
  </style>
</head>
<body>
  <h1>Arango-OntoExtract</h1>
  <p style="color:#64748b;font-size:0.875rem;">
    Fallback login (static UI not bundled). Use email and password.
  </p>
  <form id="f">
    <label>Email<input type="email" id="email" autocomplete="username" required /></label>
    <label>Password<input
      type="password"
      id="password"
      autocomplete="current-password"
      required
    /></label>
    <button type="submit">Sign in</button>
    <p id="err" class="err" hidden></p>
  </form>
  <p class="hint">Production API requires POST JSON to <code>{api_login}</code>.</p>
  <script>
(function () {{
  var TOKEN_KEY = 'aoe_auth_token';
  var api = {api_js};
  var home = {home_js};
  var pfx = {pfx_js};
  document.getElementById('f').onsubmit = function (e) {{
    e.preventDefault();
    var err = document.getElementById('err');
    err.hidden = true;
    var email = document.getElementById('email').value.trim();
    var password = document.getElementById('password').value;
    fetch(api, {{
      method: 'POST',
      headers: {{ 'Content-Type': 'application/json' }},
      body: JSON.stringify({{ email: email, password: password }}),
    }}).then(function (r) {{
      return r.json().then(function (body) {{ return {{ ok: r.ok, body: body }}; }});
    }}).then(function (x) {{
      if (!x.ok) {{
        var msg = (x.body && x.body.error && x.body.error.message)
          || x.body.detail
          || 'Login failed';
        err.textContent = msg;
        err.hidden = false;
        return;
      }}
      var token = x.body.token;
      if (!token) {{
        err.textContent = 'No token in response';
        err.hidden = false;
        return;
      }}
      localStorage.setItem(TOKEN_KEY, token);
      var secure = location.protocol === 'https:';
      document.cookie = TOKEN_KEY + '=' + encodeURIComponent(token) + '; path=/; SameSite=Lax' +
        (secure ? '; Secure' : '');
      var q = new URLSearchParams(location.search);
      var redir = q.get('redirect');
      if (redir && redir.charAt(0) === '/') {{
        location.href = (pfx || '') + redir;
      }} else {{
        location.href = home;
      }}
    }}).catch(function () {{
      err.textContent = 'Network error';
      err.hidden = false;
    }});
  }};
}})();
  </script>
</body>
</html>
"""
