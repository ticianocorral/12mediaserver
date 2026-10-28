"""HTML servido pelo proprio Python (nao vem do index.html)."""

from .config import MIN_PASSWORD_LEN
from . import branding as _branding


# Logo de texto (o mesmo de static/wordmark.svg, sem animacao), embutido porque
# a tela de entrada nao pode depender de arquivo estatico antes do login.
_WORDMARK = '''<svg class="wordmark" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 124 25" role="img" aria-label="__MARCA__"><style>.wm-on{fill:#ff2a2a}.wm-off{fill:#3d0f12}</style><g transform="translate(0,1) scale(2.1)"><rect class="wm-off" x="1" y="0" width="4" height="1" rx=".4"/><rect class="wm-on" x="5" y="1" width="1" height="4" rx=".4"/><rect class="wm-on" x="5" y="6" width="1" height="4" rx=".4"/><rect class="wm-off" x="1" y="10" width="4" height="1" rx=".4"/><rect class="wm-off" x="0" y="6" width="1" height="4" rx=".4"/><rect class="wm-off" x="0" y="1" width="1" height="4" rx=".4"/><rect class="wm-off" x="1" y="5" width="4" height="1" rx=".4"/></g><g transform="translate(14,1) scale(2.1)"><rect class="wm-on" x="1" y="0" width="4" height="1" rx=".4"/><rect class="wm-on" x="5" y="1" width="1" height="4" rx=".4"/><rect class="wm-off" x="5" y="6" width="1" height="4" rx=".4"/><rect class="wm-on" x="1" y="10" width="4" height="1" rx=".4"/><rect class="wm-on" x="0" y="6" width="1" height="4" rx=".4"/><rect class="wm-off" x="0" y="1" width="1" height="4" rx=".4"/><rect class="wm-on" x="1" y="5" width="4" height="1" rx=".4"/></g><g transform="translate(34,1) scale(2.1)"><rect class="wm-on" x="1" y="0" width="4" height="1" rx=".4"/><rect class="wm-on" x="5" y="1" width="1" height="4" rx=".4"/><rect class="wm-on" x="5" y="6" width="1" height="4" rx=".4"/><rect class="wm-on" x="1" y="10" width="4" height="1" rx=".4"/><rect class="wm-on" x="0" y="6" width="1" height="4" rx=".4"/><rect class="wm-on" x="0" y="1" width="1" height="4" rx=".4"/><rect class="wm-off" x="1" y="5" width="4" height="1" rx=".4"/></g><g transform="translate(48,1) scale(2.1)"><rect class="wm-on" x="1" y="0" width="4" height="1" rx=".4"/><rect class="wm-on" x="5" y="1" width="1" height="4" rx=".4"/><rect class="wm-on" x="5" y="6" width="1" height="4" rx=".4"/><rect class="wm-on" x="1" y="10" width="4" height="1" rx=".4"/><rect class="wm-on" x="0" y="6" width="1" height="4" rx=".4"/><rect class="wm-on" x="0" y="1" width="1" height="4" rx=".4"/><rect class="wm-off" x="1" y="5" width="4" height="1" rx=".4"/></g><rect class="wm-on" x="29" y="8.2" width="3" height="3"/><rect class="wm-on" x="29" y="14.8" width="3" height="3"/><text x="68" y="11.2" font-family="Futura,'Century Gothic','Arial Black',Helvetica,sans-serif" font-weight="900" font-size="11" textLength="55" lengthAdjust="spacing" fill="#f2ecdc">MEDIA</text><text x="68" y="23.6" font-family="Futura,'Century Gothic','Arial Black',Helvetica,sans-serif" font-weight="900" font-size="11" textLength="55" lengthAdjust="spacing" fill="#f2ecdc">SERVER</text></svg>'''


def _login_page(setup=False):
    """Tela de entrada. Em modo setup cria o primeiro administrador, e exige o
    codigo impresso no log do servidor — assim quem esta na rede mas nao tem
    acesso ao computador nao consegue tomar a conta inicial."""
    marca = _branding.get()
    cor = marca["cor"]
    cor_hover = _branding._clarear(cor)
    cor_rgb = "%d,%d,%d" % (int(cor[1:3], 16), int(cor[3:5], 16), int(cor[5:7], 16))
    if setup:
        heading = "Criar o administrador"
        sub = ("Primeiro acesso. O codigo de 6 digitos aparece no terminal onde "
               "o %s esta rodando." % marca["nome"])
        action = "/api/auth/setup"
        button = "Criar conta e entrar"
        extra_top = (
            '<label for="appname">Nome do app</label>'
            '<input id="appname" type="text" maxlength="40" autocomplete="off" '
            'required placeholder="Ex.: Familia Corral">'
            '<label for="code">Codigo de instalacao</label>'
            '<input id="code" type="text" inputmode="numeric" pattern="[0-9]{6}" '
            'maxlength="6" autocomplete="off" required placeholder="000000">')
        extra_bottom = (
            '<label for="confirm">Repita a senha</label>'
            '<input id="confirm" type="password" autocomplete="new-password" '
            'required minlength="%d">' % MIN_PASSWORD_LEN)
        hint = ("O nome do app tambem vira a pasta da biblioteca na nuvem/HD "
                "— escolha com cuidado, nao da pra mudar depois. Depois disso "
                "nao existe auto-cadastro: contas novas so pelo painel de "
                "administracao.")
        autocomplete = "new-password"
    else:
        heading = "Entrar"
        sub = "Use a conta que o administrador criou para voce."
        action = "/api/auth/login"
        button = "Entrar"
        extra_top = ""
        extra_bottom = ""
        hint = ("Esqueceu a senha? Peca a um administrador para redefinir. "
                "Se ninguem mais tiver acesso, apague "
                "<code>~/.cache/media-server/auth.json</code> no computador e o "
                "primeiro acesso volta.")
        autocomplete = "current-password"

    page = """<!DOCTYPE html>
<html lang="pt-BR"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex">
<title>__MARCA__</title>
<link rel="icon" href="/favicon.svg">
<style>
  :root { color-scheme: dark; }
  * { box-sizing: border-box; }
  body {
    margin: 0; min-height: 100vh; display: flex; align-items: center;
    justify-content: center; padding: 24px;
    background: radial-gradient(1200px 600px at 50% -10%, #26262a 0%, #0e0e10 60%);
    color: #f2ecdc;
    font-family: Roboto, ui-sans-serif, system-ui, -apple-system, "Segoe UI", sans-serif;
  }
  .card {
    width: 100%; max-width: 390px; background: rgba(26,26,29,.92);
    border: 1px solid #2e2e33; border-radius: 14px; padding: 34px 30px 30px;
    box-shadow: 0 24px 60px -20px rgba(0,0,0,.8);
  }
  .brand { margin: 0; line-height: 0; }
  .wordmark { height: 34px; width: auto; display: block; }
  h1 { font-size: 19px; font-weight: 600; margin: 18px 0 6px; }
  p.sub { margin: 0 0 22px; font-size: 14px; line-height: 1.5; color: #a8a296; }
  label {
    display: block; font-size: 12px; text-transform: uppercase;
    letter-spacing: .08em; color: #8f8a7e; margin: 0 0 6px;
  }
  input {
    width: 100%; padding: 12px 13px; margin-bottom: 16px; font-size: 15px;
    color: #f2ecdc; background: #121214; border: 1px solid #36363b;
    border-radius: 8px; font-family: inherit;
  }
  #code { letter-spacing: .5em; font-family: ui-monospace, Menlo, monospace; text-align: center; }
  input:focus { outline: none; border-color: __COR__; box-shadow: 0 0 0 3px rgba(__COR_RGB__,.18); }
  button {
    width: 100%; padding: 12px; font-size: 15px; font-weight: 600; color: #fff;
    background: __COR__; border: 0; border-radius: 8px; cursor: pointer; font-family: inherit;
  }
  button:hover { background: __COR_HOVER__; }
  button:disabled { opacity: .6; cursor: default; }
  .msg { margin: 14px 0 0; padding: 10px 12px; border-radius: 8px; font-size: 13.5px; line-height: 1.45; display: none; }
  .msg.err { display: block; background: #2c1214; color: #f5a19b; border: 1px solid #55211f; }
  .msg.ok  { display: block; background: #10241a; color: #7fce9f; border: 1px solid #1f4a33; }
  .hint { margin: 20px 0 0; font-size: 12px; line-height: 1.55; color: #6f6a60; }
  .hint code { color: #a8a296; }
</style>
</head><body>
  <form class="card" id="form" autocomplete="on">
    <div class="brand">__WORDMARK__</div>
    <h1>__HEADING__</h1>
    <p class="sub">__SUB__</p>
    __EXTRA_TOP__
    <label for="username">Usuario</label>
    <input id="username" type="text" autocomplete="username" required
           autocapitalize="none" spellcheck="false" autofocus>
    <label for="password">Senha</label>
    <input id="password" type="password" autocomplete="__AC__" required minlength="__MIN__">
    __EXTRA_BOTTOM__
    <button id="btn" type="submit">__BUTTON__</button>
    <div class="msg" id="msg"></div>
    <p class="hint">__HINT__</p>
  </form>
<script>
  var form = document.getElementById('form');
  var msg = document.getElementById('msg');
  var btn = document.getElementById('btn');
  function show(text, kind) { msg.textContent = text; msg.className = 'msg ' + kind; }
  form.addEventListener('submit', async function (ev) {
    ev.preventDefault();
    var body = {
      username: document.getElementById('username').value.trim().toLowerCase(),
      password: document.getElementById('password').value
    };
    var confirmEl = document.getElementById('confirm');
    if (confirmEl && body.password !== confirmEl.value) {
      show('As senhas nao conferem.', 'err'); return;
    }
    if (body.password.length < __MIN__) {
      show('A senha precisa ter pelo menos __MIN__ caracteres.', 'err'); return;
    }
    var codeEl = document.getElementById('code');
    if (codeEl) body.code = codeEl.value.trim();
    var appnameEl = document.getElementById('appname');
    if (appnameEl) body.nome = appnameEl.value.trim();
    btn.disabled = true;
    try {
      var res = await fetch('__ACTION__', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body)
      });
      var data = await res.json().catch(function () { return {}; });
      if (res.ok && data.status === 'ok') {
        show('Tudo certo, entrando...', 'ok');
        // Preserva a query: o app de TV entra por /?tv=1 e sem isto o
        // login o devolveria em modo normal, sem navegacao por controle.
        window.location.replace('/' + window.location.search);
        return;
      }
      show(data.error || 'Nao foi possivel entrar.', 'err');
    } catch (e) {
      show('Falha de conexao com o servidor.', 'err');
    }
    btn.disabled = false;
  });
</script>
</body></html>"""
    for token, value in (
        ("__HEADING__", heading), ("__SUB__", sub), ("__ACTION__", action),
        ("__BUTTON__", button), ("__EXTRA_TOP__", extra_top),
        ("__EXTRA_BOTTOM__", extra_bottom), ("__HINT__", hint),
        ("__AC__", autocomplete), ("__MIN__", str(MIN_PASSWORD_LEN)),
        ("__WORDMARK__", _WORDMARK), ("__MARCA__", marca["nome"]), ("__COR__", cor),
        ("__COR_HOVER__", cor_hover), ("__COR_RGB__", cor_rgb),
    ):
        page = page.replace(token, value)
    return page
