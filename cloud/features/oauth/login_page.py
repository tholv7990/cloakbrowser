"""The hosted PKCE login page (GET /oauth/login).

Fully self-contained HTML — no server-side templating and, deliberately, no
server-side reflection of query parameters. The page's own JS reads redirect_uri /
code_challenge / state from the URL, POSTs credentials to /oauth/authorize, and
redirects to the (server-validated, loopback-only) redirect_uri with ?code&state.
Because nothing from the URL is echoed into the HTML, there is no XSS surface here.
"""

from __future__ import annotations

# Locks the page to its own inline CSS/JS + same-origin POST. No external anything.
LOGIN_CSP = (
    "default-src 'none'; "
    "style-src 'unsafe-inline'; "
    "script-src 'unsafe-inline'; "
    "connect-src 'self'; "
    "img-src 'self' data:; "
    "base-uri 'none'; "
    "form-action 'none'"
)

LOGIN_HTML = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex">
<title>Sign in to Plasma</title>
<style>
  :root{
    --bg:#f5f6f9; --glow:rgba(109,74,255,.16);
    --card:#ffffff; --card-border:#e5e7ee;
    --ink:#171a22; --muted:#6b7280; --field:#fbfbfd; --field-border:#d8dbe4;
    --accent:#6d4aff; --accent-ink:#ffffff; --danger:#c02c3a;
    --ring:rgba(109,74,255,.35);
  }
  @media (prefers-color-scheme:dark){
    :root{
      --bg:#0b0d12; --glow:rgba(139,109,255,.20);
      --card:#15171f; --card-border:#262a35;
      --ink:#e9ebf2; --muted:#9aa1af; --field:#0f1117; --field-border:#2c3140;
      --accent:#8b6dff; --accent-ink:#0b0d12; --danger:#ff6b78;
      --ring:rgba(139,109,255,.45);
    }
  }
  :root[data-theme="light"]{
    --bg:#f5f6f9; --glow:rgba(109,74,255,.16);
    --card:#ffffff; --card-border:#e5e7ee; --ink:#171a22; --muted:#6b7280;
    --field:#fbfbfd; --field-border:#d8dbe4; --accent:#6d4aff; --accent-ink:#fff;
    --danger:#c02c3a; --ring:rgba(109,74,255,.35);
  }
  :root[data-theme="dark"]{
    --bg:#0b0d12; --glow:rgba(139,109,255,.20);
    --card:#15171f; --card-border:#262a35; --ink:#e9ebf2; --muted:#9aa1af;
    --field:#0f1117; --field-border:#2c3140; --accent:#8b6dff; --accent-ink:#0b0d12;
    --danger:#ff6b78; --ring:rgba(139,109,255,.45);
  }
  *{box-sizing:border-box}
  html,body{height:100%}
  body{
    margin:0; background:var(--bg); color:var(--ink);
    font:15px/1.5 system-ui,-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;
    display:grid; place-items:center; padding:24px;
    background-image:radial-gradient(60% 55% at 50% 0%,var(--glow),transparent 70%);
    -webkit-font-smoothing:antialiased;
  }
  .card{
    width:100%; max-width:380px; background:var(--card);
    border:1px solid var(--card-border); border-radius:16px;
    padding:32px 30px 26px; box-shadow:0 12px 40px -18px rgba(20,20,50,.35);
  }
  .brand{display:flex; align-items:center; gap:10px; margin-bottom:22px}
  .mark{
    width:26px; height:26px; border-radius:8px; flex:0 0 auto;
    background:conic-gradient(from 210deg,#8b6dff,#4aa8ff,#b06dff,#8b6dff);
    box-shadow:0 0 18px -2px var(--ring);
  }
  .brand b{font-size:15px; letter-spacing:.2px}
  h1{margin:0 0 4px; font-size:20px; font-weight:640; letter-spacing:-.2px}
  .sub{margin:0 0 22px; color:var(--muted); font-size:13.5px}
  label{display:block; font-size:12.5px; font-weight:560; margin:0 0 6px; color:var(--muted)}
  .field{margin-bottom:16px}
  input{
    width:100%; padding:11px 12px; font-size:14.5px; color:var(--ink);
    background:var(--field); border:1px solid var(--field-border); border-radius:10px;
    outline:none; transition:border-color .15s, box-shadow .15s;
  }
  input:focus{border-color:var(--accent); box-shadow:0 0 0 3px var(--ring)}
  button{
    width:100%; margin-top:6px; padding:11px 14px; font-size:14.5px; font-weight:600;
    color:var(--accent-ink); background:var(--accent); border:0; border-radius:10px;
    cursor:pointer; transition:filter .15s, opacity .15s;
  }
  button:hover:not(:disabled){filter:brightness(1.06)}
  button:disabled{opacity:.6; cursor:default}
  .err{
    display:none; margin:0 0 14px; padding:9px 11px; font-size:13px;
    color:var(--danger); background:color-mix(in srgb,var(--danger) 12%,transparent);
    border:1px solid color-mix(in srgb,var(--danger) 35%,transparent); border-radius:9px;
  }
  .err.show{display:block}
  .foot{margin:18px 0 0; text-align:center; color:var(--muted); font-size:12px}
  @media (prefers-reduced-motion:reduce){*{transition:none!important}}
</style>
</head>
<body>
  <main class="card">
    <div class="brand"><span class="mark" aria-hidden="true"></span><b>Plasma</b></div>
    <h1>Sign in</h1>
    <p class="sub">Authorize this device to your Plasma account.</p>
    <div class="err" id="err" role="alert"></div>
    <form id="form" autocomplete="on" novalidate>
      <div class="field">
        <label for="email">Email</label>
        <input id="email" name="email" type="email" autocomplete="username"
               required autofocus inputmode="email" />
      </div>
      <div class="field">
        <label for="password">Password</label>
        <input id="password" name="password" type="password"
               autocomplete="current-password" required />
      </div>
      <button id="submit" type="submit">Sign in</button>
    </form>
    <p class="foot">Protected sign-in · you can close this window afterward</p>
  </main>
<script>
(function(){
  var q = new URLSearchParams(location.search);
  var redirectUri = q.get("redirect_uri");
  var codeChallenge = q.get("code_challenge");
  var state = q.get("state");
  var err = document.getElementById("err");
  var form = document.getElementById("form");
  var submit = document.getElementById("submit");

  function fail(msg){ err.textContent = msg; err.classList.add("show"); }

  var MESSAGES = {
    invalid_credentials: "Incorrect email or password.",
    account_unverified: "Verify your email address before signing in.",
    account_suspended: "This account is suspended.",
    throttled: "Too many attempts. Please wait a moment and try again.",
    invalid_request: "This sign-in link is invalid.",
  };

  if(!redirectUri || !codeChallenge){
    submit.disabled = true;
    fail("This sign-in link is invalid or has expired.");
    return;
  }

  form.addEventListener("submit", function(ev){
    ev.preventDefault();
    err.classList.remove("show");
    submit.disabled = true;
    submit.textContent = "Signing in\\u2026";
    fetch("/oauth/authorize", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({
        email: document.getElementById("email").value.trim(),
        password: document.getElementById("password").value,
        code_challenge: codeChallenge,
        redirect_uri: redirectUri,
      }),
    }).then(function(r){
      return r.json().then(function(data){ return {ok: r.ok, data: data}; });
    }).then(function(res){
      if(!res.ok){
        var code = res.data && res.data.error;
        fail(MESSAGES[code] || "Sign-in failed. Please try again.");
        submit.disabled = false; submit.textContent = "Sign in";
        return;
      }
      // Redirect to the server-validated (loopback-only) redirect_uri.
      var u = new URL(res.data.redirect_uri);
      u.searchParams.set("code", res.data.code);
      if(state) u.searchParams.set("state", state);
      location.assign(u.toString());
    }).catch(function(){
      fail("Could not reach the server. Check your connection and try again.");
      submit.disabled = false; submit.textContent = "Sign in";
    });
  });
})();
</script>
</body>
</html>
"""
