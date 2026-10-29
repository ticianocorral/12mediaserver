"""HTML servido pelo proprio Python (nao vem do index.html)."""

from .config import MIN_PASSWORD_LEN
from . import branding as _branding


# Logo de texto (o mesmo de static/wordmark.svg, sem animacao), embutido porque
# a tela de entrada nao pode depender de arquivo estatico antes do login.
# Jost embutida no app (static/fonts): as telas de entrada carregam antes de
# existir sessao, entao a fonte sai de uma rota publica.
_FONT_FACE = """@font-face { font-family: "Jost"; font-style: normal; font-weight: 400 700;
  font-display: swap; src: url("/static/fonts/jost-latin.woff2") format("woff2"); }
"""

_WORDMARK = '''<svg class="wordmark" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 124 25" role="img" aria-label="__MARCA__"><style>.wm-on{fill:#ff2a2a}.wm-off{fill:#3d0f12}</style><g transform="translate(0,1) scale(2.1)"><rect class="wm-off" x="1" y="0" width="4" height="1" rx=".4"/><rect class="wm-on" x="5" y="1" width="1" height="4" rx=".4"/><rect class="wm-on" x="5" y="6" width="1" height="4" rx=".4"/><rect class="wm-off" x="1" y="10" width="4" height="1" rx=".4"/><rect class="wm-off" x="0" y="6" width="1" height="4" rx=".4"/><rect class="wm-off" x="0" y="1" width="1" height="4" rx=".4"/><rect class="wm-off" x="1" y="5" width="4" height="1" rx=".4"/></g><g transform="translate(14,1) scale(2.1)"><rect class="wm-on" x="1" y="0" width="4" height="1" rx=".4"/><rect class="wm-on" x="5" y="1" width="1" height="4" rx=".4"/><rect class="wm-off" x="5" y="6" width="1" height="4" rx=".4"/><rect class="wm-on" x="1" y="10" width="4" height="1" rx=".4"/><rect class="wm-on" x="0" y="6" width="1" height="4" rx=".4"/><rect class="wm-off" x="0" y="1" width="1" height="4" rx=".4"/><rect class="wm-on" x="1" y="5" width="4" height="1" rx=".4"/></g><g transform="translate(34,1) scale(2.1)"><rect class="wm-on" x="1" y="0" width="4" height="1" rx=".4"/><rect class="wm-on" x="5" y="1" width="1" height="4" rx=".4"/><rect class="wm-on" x="5" y="6" width="1" height="4" rx=".4"/><rect class="wm-on" x="1" y="10" width="4" height="1" rx=".4"/><rect class="wm-on" x="0" y="6" width="1" height="4" rx=".4"/><rect class="wm-on" x="0" y="1" width="1" height="4" rx=".4"/><rect class="wm-off" x="1" y="5" width="4" height="1" rx=".4"/></g><g transform="translate(48,1) scale(2.1)"><rect class="wm-on" x="1" y="0" width="4" height="1" rx=".4"/><rect class="wm-on" x="5" y="1" width="1" height="4" rx=".4"/><rect class="wm-on" x="5" y="6" width="1" height="4" rx=".4"/><rect class="wm-on" x="1" y="10" width="4" height="1" rx=".4"/><rect class="wm-on" x="0" y="6" width="1" height="4" rx=".4"/><rect class="wm-on" x="0" y="1" width="1" height="4" rx=".4"/><rect class="wm-off" x="1" y="5" width="4" height="1" rx=".4"/></g><rect class="wm-on" x="29" y="8.2" width="3" height="3"/><rect class="wm-on" x="29" y="14.8" width="3" height="3"/><text x="68" y="11.2" font-family="Futura,'Century Gothic','Arial Black',Helvetica,sans-serif" font-weight="900" font-size="11" textLength="55" lengthAdjust="spacing" fill="#f2ecdc">MEDIA</text><text x="68" y="23.6" font-family="Futura,'Century Gothic','Arial Black',Helvetica,sans-serif" font-weight="900" font-size="11" textLength="55" lengthAdjust="spacing" fill="#f2ecdc">SERVER</text></svg>'''


def _login_page(setup=False, codigo=None):
    """Tela de entrada. Em modo setup cria o primeiro administrador, e exige o
    codigo impresso no log do servidor — assim quem esta na rede mas nao tem
    acesso ao computador nao consegue tomar a conta inicial."""
    marca = _branding.get()
    cor = marca["cor"]
    cor_hover = _branding._clarear(cor)
    cor_rgb = "%d,%d,%d" % (int(cor[1:3], 16), int(cor[3:5], 16), int(cor[5:7], 16))
    if setup:
        heading = "Criar a conta"
        if codigo:
            # Quem abre a pagina no proprio computador ja tem acesso a maquina,
            # entao o codigo (que existe para barrar a rede) vem preenchido.
            sub = ("Primeiro acesso. Como voce esta neste computador, o codigo "
                   "ja veio preenchido. Esta e a conta unica da casa: depois "
                   "voce cria os perfis de cada pessoa.")
        else:
            sub = ("Primeiro acesso. O codigo de 6 digitos aparece no terminal "
                   "onde o %s esta rodando. Esta e a conta unica da casa: depois "
                   "voce cria os perfis de cada pessoa." % marca["nome"])
        action = "/api/auth/setup"
        button = "Criar conta e entrar"
        extra_top = (
            '<label for="code">Codigo de instalacao</label>'
            '<input id="code" type="text" inputmode="numeric" pattern="[0-9]{6}" '
            'maxlength="6" autocomplete="off" required placeholder="000000"%s>'
            % (' value="%s"' % codigo if codigo else ""))
        extra_bottom = (
            '<label for="confirm">Repita a senha</label>'
            '<input id="confirm" type="password" autocomplete="new-password" '
            'required minlength="%d">'
            '<label for="perfil">Nome do seu perfil</label>'
            '<input id="perfil" type="text" maxlength="20" autocomplete="off" '
            'placeholder="Ex.: Ticiano">' % MIN_PASSWORD_LEN)
        hint = ("Depois disso nao existe auto-cadastro. Os perfis (com avatar, "
                "perfil infantil e PIN) voce cria na tela de escolha de perfil.")
        autocomplete = "new-password"
    else:
        heading = "Entrar"
        sub = "Entre com o login da casa. Depois voce escolhe quem esta assistindo."
        action = "/api/auth/login"
        button = "Entrar"
        extra_top = ""
        extra_bottom = ""
        hint = ("Esqueceu a senha? Apague "
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
__FONTE__
  :root { color-scheme: dark; }
  * { box-sizing: border-box; }
  body {
    margin: 0; min-height: 100vh; display: flex; align-items: center;
    justify-content: center; padding: 24px;
    background: radial-gradient(1200px 600px at 50% -10%, #26262a 0%, #0e0e10 60%);
    color: #f2ecdc;
    font-family: "Jost", Futura, "Century Gothic", "Segoe UI", Roboto, ui-sans-serif, sans-serif;
  }
  .card {
    width: 100%; max-width: 390px; background: rgba(26,26,29,.92);
    border: 1px solid #2e2e33; border-radius: 6px; padding: 34px 30px 30px;
    box-shadow: 0 3px 0 0 rgba(0,0,0,.6);
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
    var perfilEl = document.getElementById('perfil');
    if (perfilEl) body.perfil = perfilEl.value.trim();
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
        ("__FONTE__", _FONT_FACE), ("__BUTTON__", button), ("__EXTRA_TOP__", extra_top),
        ("__EXTRA_BOTTOM__", extra_bottom), ("__HINT__", hint),
        ("__AC__", autocomplete), ("__MIN__", str(MIN_PASSWORD_LEN)),
        ("__WORDMARK__", _WORDMARK), ("__MARCA__", marca["nome"]), ("__COR__", cor),
        ("__COR_HOVER__", cor_hover), ("__COR_RGB__", cor_rgb),
    ):
        page = page.replace(token, value)
    return page


_PROFILES_CSS = """
  :root { color-scheme: dark; --bg:#0e0e10; --bg2:#1a1a1d; --surface:#212125; --panel:#2a2a2e; --edge:#3b3b40;
    --cream:#efe6d0; --text:#f2ecdc; --text2:#a8a296; --cor:__COR__; --cor-hover:__COR_HOVER__;
    --font:"Jost", Futura, "Century Gothic", "Segoe UI", Roboto, ui-sans-serif, sans-serif; }
  * { box-sizing:border-box; margin:0; padding:0; }
  body { min-height:100vh; background:var(--bg); color:var(--text); font-family:var(--font); font-size:17px;
    display:flex; flex-direction:column; align-items:center; padding:28px 20px 40px; }
  :focus-visible { outline:2px solid var(--cream); outline-offset:3px; }
  .wordmark { height:40px; width:auto; display:block; }
  header { width:100%; max-width:980px; display:flex; justify-content:space-between; align-items:center; gap:12px; }
  .link { background:none; border:0; color:var(--text2); font:inherit; font-size:15px; cursor:pointer; padding:6px 4px; }
  .link:hover { color:var(--text); text-decoration:underline; }
  main { flex:1; width:100%; max-width:980px; display:flex; flex-direction:column; align-items:center; justify-content:center; padding:24px 0; }
  h1 { font-size:clamp(30px,5vw,44px); font-weight:600; text-align:center; line-height:1.1; }
  .sub { margin-top:8px; color:var(--text2); text-align:center; font-size:16px; }
  .grid { margin-top:38px; display:flex; flex-wrap:wrap; gap:26px 28px; justify-content:center; }
  .perfil { width:132px; background:none; border:0; color:var(--text2); font:inherit; cursor:pointer; text-align:center; }
  .perfil .av { position:relative; width:132px; height:132px; border-radius:6px; overflow:hidden; border:2px solid transparent;
    box-shadow:0 3px 0 0 rgba(0,0,0,.65); transition:transform .18s ease, border-color .18s ease; }
  .perfil .av img { width:100%; height:100%; display:block; }
  .perfil:hover .av, .perfil:focus-visible .av { border-color:var(--cream); transform:translateY(-3px); }
  .perfil:hover, .perfil:focus-visible { color:var(--text); }
  .perfil .nome { margin-top:12px; font-size:18px; font-weight:500; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
  .perfil .tags { margin-top:2px; font-size:13px; color:var(--text2); min-height:18px; }
  .lock { position:absolute; right:6px; bottom:6px; width:26px; height:26px; border-radius:4px; background:rgba(14,14,16,.85);
    display:flex; align-items:center; justify-content:center; }
  .lock svg { width:15px; height:15px; stroke:var(--cream); fill:none; stroke-width:2; }
  .editando .av::after { content:""; position:absolute; inset:0; background:rgba(14,14,16,.55); }
  .editando .lapis { display:flex; }
  .lapis { display:none; position:absolute; inset:0; align-items:center; justify-content:center; z-index:2; }
  .lapis svg { width:34px; height:34px; stroke:var(--cream); fill:none; stroke-width:2; }
  .novo .av { background:var(--surface); display:flex; align-items:center; justify-content:center; }
  .novo .av span { font-size:64px; font-weight:300; color:var(--text2); line-height:1; }
  .acoes { margin-top:44px; display:flex; gap:14px; flex-wrap:wrap; justify-content:center; }
  .btn { padding:12px 26px; border-radius:4px; font:inherit; font-weight:600; font-size:16px; cursor:pointer;
    border:1px solid var(--edge); background:var(--panel); color:var(--text); box-shadow:0 3px 0 0 rgba(0,0,0,.65);
    transition:background .18s ease; }
  .btn:hover { background:var(--edge); }
  .btn:active { transform:translateY(2px); box-shadow:0 1px 0 0 rgba(0,0,0,.65); }
  .btn.primario { background:var(--cor); border-color:transparent; color:#fff; }
  .btn.primario:hover { background:var(--cor-hover); }
  .btn.perigo { color:#ff8a78; }
  .btn:disabled { opacity:.55; cursor:default; }
  .modal { position:fixed; inset:0; background:rgba(5,5,5,.85); display:none; align-items:center; justify-content:center; padding:16px; z-index:10; }
  .modal.on { display:flex; }
  .caixa { width:100%; max-width:460px; max-height:92vh; overflow-y:auto; background:var(--bg2); border:1px solid var(--edge);
    border-radius:6px; box-shadow:0 3px 0 0 rgba(0,0,0,.65); padding:28px 26px 24px; }
  .caixa h2 { font-size:26px; font-weight:600; margin-bottom:6px; }
  .caixa p.d { color:var(--text2); font-size:15px; margin-bottom:18px; }
  label.l { display:block; font-size:13px; font-weight:500; color:var(--text2); margin:14px 0 6px; }
  input.t { width:100%; padding:12px 13px; font:inherit; font-size:16px; color:var(--text); background:var(--bg);
    border:1px solid var(--edge); border-radius:6px; }
  input.t:focus { outline:2px solid var(--cream); outline-offset:2px; }
  .avs { display:grid; grid-template-columns:repeat(6,1fr); gap:8px; }
  .avs button { padding:0; border:2px solid transparent; border-radius:6px; background:none; cursor:pointer; overflow:hidden; aspect-ratio:1; }
  .avs button img { width:100%; height:100%; display:block; }
  .avs button[aria-pressed="true"] { border-color:var(--cream); }
  .opt { display:flex; align-items:flex-start; gap:12px; margin-top:16px; cursor:pointer; }
  .opt input { margin-top:5px; width:18px; height:18px; accent-color:var(--cor); flex:none; }
  .opt b { display:block; font-weight:600; font-size:16px; }
  .opt span { color:var(--text2); font-size:14px; }
  .pin { display:flex; gap:10px; justify-content:center; margin:8px 0 4px; }
  .pin input { width:54px; height:64px; text-align:center; font:inherit; font-size:30px; font-weight:600; color:var(--text);
    background:var(--bg); border:1px solid var(--edge); border-radius:6px; }
  .pin input:focus { outline:2px solid var(--cream); outline-offset:2px; }
  .linha { display:flex; gap:10px; margin-top:22px; justify-content:flex-end; flex-wrap:wrap; }
  .linha .esq { margin-right:auto; }
  .msg { min-height:20px; margin-top:12px; font-size:14px; color:#ff8a78; }
  .pinbox { margin-top:10px; padding:14px; background:var(--bg); border:1px solid var(--edge); border-radius:6px; }
  .pinbox .estado { font-size:15px; color:var(--text2); margin-bottom:8px; }
  @media (max-width:560px) { .perfil, .perfil .av { width:104px; } .perfil .av { height:104px; } .grid { gap:20px 16px; }
    .avs { grid-template-columns:repeat(4,1fr); } }
  @media (prefers-reduced-motion: reduce) { * { transition:none !important; } }
"""

_PROFILES_JS = """
(function () {
  var $ = function (s) { return document.querySelector(s); };
  var estado = { perfis: [], me: null, podeGerenciar: false, max: 6, avatares: [], editando: false, edit: null };
  var ICONE_LAPIS = '<svg viewBox="0 0 24 24" stroke-linecap="round" stroke-linejoin="round"><path d="M12 20h9"/><path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4z"/></svg>';
  var ICONE_CADEADO = '<svg viewBox="0 0 24 24" stroke-linecap="round" stroke-linejoin="round"><rect x="5" y="11" width="14" height="10" rx="2"/><path d="M8 11V8a4 4 0 0 1 8 0v3"/></svg>';

  function api(url, corpo) {
    return fetch(url, { method: corpo === undefined ? 'GET' : 'POST',
        headers: { 'Content-Type': 'application/json' }, body: corpo === undefined ? undefined : JSON.stringify(corpo) })
      .then(function (r) { return r.json().catch(function () { return {}; }).then(function (d) { d._http = r.status; return d; }); });
  }
  function el(tag, cls, texto) { var e = document.createElement(tag); if (cls) e.className = cls; if (texto != null) e.textContent = texto; return e; }
  function avatarUrl(id) { return '/static/avatars/' + id + '.svg'; }
  function entrar() { window.location.replace('/'); }

  function aplicar(d) {
    estado.perfis = d.profiles || []; estado.me = d.me; estado.podeGerenciar = !!d.canManage;
    estado.max = d.max || 6; estado.avatares = d.avatars || [];
    desenhar();
  }

  function desenhar() {
    var grade = $('#grade'); grade.innerHTML = '';
    document.body.classList.toggle('editando', estado.editando);
    $('#titulo').textContent = estado.editando ? 'Gerenciar perfis' : 'Quem está assistindo?';
    $('#subtitulo').textContent = estado.editando ? 'Escolha um perfil para editar, ou crie um novo.' : '';
    estado.perfis.forEach(function (p) {
      var b = el('button', 'perfil'); b.type = 'button';
      var av = el('div', 'av'); var img = el('img'); img.src = avatarUrl(p.avatar); img.alt = ''; av.appendChild(img);
      if (p.hasPin && !estado.editando) { var c = el('div', 'lock'); c.innerHTML = ICONE_CADEADO; av.appendChild(c); }
      var l = el('div', 'lapis'); l.innerHTML = ICONE_LAPIS; av.appendChild(l);
      b.appendChild(av); b.appendChild(el('div', 'nome', p.name));
      var tags = []; if (p.infantil) tags.push('Infantil'); else if (p.role === 'admin') tags.push('Admin');
      if (p.hasPin && estado.editando) tags.push('PIN');
      b.appendChild(el('div', 'tags', tags.join(' · ')));
      b.addEventListener('click', function () { estado.editando ? abrirEdicao(p) : escolher(p); });
      grade.appendChild(b);
    });
    if (estado.editando && estado.perfis.length < estado.max) {
      var n = el('button', 'perfil novo'); n.type = 'button';
      var av2 = el('div', 'av'); av2.appendChild(el('span', null, '+')); n.appendChild(av2);
      n.appendChild(el('div', 'nome', 'Novo perfil')); n.appendChild(el('div', 'tags', ''));
      n.addEventListener('click', function () { abrirEdicao(null); });
      grade.appendChild(n);
    }
    var ger = $('#btnGerenciar');
    ger.textContent = estado.editando ? 'Concluído' : 'Gerenciar perfis';
    ger.className = estado.editando ? 'btn primario' : 'btn';
  }

  /* ----- escolher perfil (com PIN) ----- */
  var pinAlvo = null;
  function escolher(p) {
    if (!p.hasPin) { selecionar(p.id, ''); return; }
    pinAlvo = p; $('#pinNome').textContent = p.name; limparPin('#pinEntrada'); $('#pinMsg').textContent = '';
    abrir('#modalPin'); setTimeout(function () { $('#pinEntrada input').focus(); }, 50);
  }
  function selecionar(id, pin) {
    return api('/api/profiles/select', { id: id, pin: pin }).then(function (d) {
      if (d.status === 'ok') { entrar(); return; }
      $('#pinMsg').textContent = d.error || 'Não foi possível entrar.'; limparPin('#pinEntrada');
      var i = $('#pinEntrada input'); if (i) i.focus();
    });
  }
  function lerPin(sel) { return Array.prototype.map.call(document.querySelectorAll(sel + ' input'), function (i) { return i.value; }).join(''); }
  function limparPin(sel) { Array.prototype.forEach.call(document.querySelectorAll(sel + ' input'), function (i) { i.value = ''; }); }
  function montarPin(sel, aoCompletar) {
    var cx = $(sel); cx.innerHTML = '';
    for (var k = 0; k < 4; k++) {
      var i = el('input'); i.type = 'password'; i.inputMode = 'numeric'; i.maxLength = 1; i.autocomplete = 'off';
      i.setAttribute('aria-label', 'Dígito ' + (k + 1));
      i.addEventListener('input', function (ev) {
        var t = ev.target; t.value = t.value.replace(/[^0-9]/g, '').slice(0, 1);
        if (t.value && t.nextElementSibling) t.nextElementSibling.focus();
        if (aoCompletar && lerPin(sel).length === 4) aoCompletar(lerPin(sel));
      });
      i.addEventListener('keydown', function (ev) {
        if (ev.key === 'Backspace' && !ev.target.value && ev.target.previousElementSibling) ev.target.previousElementSibling.focus();
      });
      cx.appendChild(i);
    }
    cx.addEventListener('paste', function (ev) {
      var txt = (ev.clipboardData.getData('text') || '').replace(/[^0-9]/g, '').slice(0, 4); if (!txt) return;
      ev.preventDefault(); var ins = cx.querySelectorAll('input');
      for (var k = 0; k < 4; k++) ins[k].value = txt[k] || '';
      if (aoCompletar && txt.length === 4) aoCompletar(txt);
    });
  }

  /* ----- modais ----- */
  function abrir(id) { $(id).classList.add('on'); }
  function fechar(id) { $(id).classList.remove('on'); }

  /* ----- gerenciar ----- */
  function alternarGerenciar() {
    if (estado.editando) { estado.editando = false; desenhar(); return; }
    if (estado.podeGerenciar) { estado.editando = true; desenhar(); return; }
    $('#senhaConta').value = ''; $('#senhaMsg').textContent = ''; abrir('#modalSenha');
    setTimeout(function () { $('#senhaConta').focus(); }, 50);
  }
  function confirmarSenha() {
    api('/api/profiles/unlock', { password: $('#senhaConta').value }).then(function (d) {
      if (d.status !== 'ok') { $('#senhaMsg').textContent = d.error || 'Senha incorreta'; return; }
      fechar('#modalSenha'); return api('/api/profiles').then(function (dd) { estado.editando = true; aplicar(dd); });
    });
  }

  function abrirEdicao(p) {
    var ed = estado.edit = { id: p ? p.id : null, avatar: p ? p.avatar : estado.avatares[estado.perfis.length % estado.avatares.length],
      hasPin: p ? p.hasPin : false, pinNovo: null, removerPin: false };
    $('#edTitulo').textContent = p ? 'Editar perfil' : 'Novo perfil';
    $('#edNome').value = p ? p.name : '';
    $('#edInfantil').checked = p ? p.infantil : false;
    $('#edAdmin').checked = p ? p.role === 'admin' : false;
    $('#edAdminLinha').style.display = $('#edInfantil').checked ? 'none' : '';
    var grade = $('#edAvatares'); grade.innerHTML = '';
    estado.avatares.forEach(function (a) {
      var b = el('button'); b.type = 'button'; b.setAttribute('aria-label', 'Avatar ' + a);
      b.setAttribute('aria-pressed', a === ed.avatar ? 'true' : 'false');
      var im = el('img'); im.src = avatarUrl(a); im.alt = ''; b.appendChild(im);
      b.addEventListener('click', function () { ed.avatar = a;
        Array.prototype.forEach.call(grade.children, function (c) { c.setAttribute('aria-pressed', 'false'); }); b.setAttribute('aria-pressed', 'true'); });
      grade.appendChild(b);
    });
    desenharPinEdicao(); $('#edMsg').textContent = '';
    $('#edExcluir').style.display = p && estado.perfis.length > 1 && p.id !== estado.me ? '' : 'none';
    abrir('#modalEdicao'); setTimeout(function () { $('#edNome').focus(); }, 50);
  }
  function desenharPinEdicao() {
    var ed = estado.edit; var caixa = $('#edPin'); caixa.innerHTML = '';
    var est = el('div', 'estado'); var acoes = el('div');
    if (ed.pinNovo) {
      est.textContent = 'PIN novo definido. Salve o perfil para aplicar.';
    } else if (ed.removerPin) {
      est.textContent = 'O PIN será removido ao salvar.';
    } else {
      est.textContent = ed.hasPin ? 'Este perfil tem PIN de 4 números.' : 'Sem PIN. Qualquer pessoa pode entrar neste perfil.';
    }
    caixa.appendChild(est);
    var entrada = el('div', 'pin'); entrada.id = 'edPinEntrada'; entrada.style.justifyContent = 'flex-start';
    var rotulo = el('label', 'l', ed.hasPin || ed.pinNovo ? 'Trocar o PIN' : 'Definir um PIN (opcional)'); rotulo.style.marginTop = '4px';
    caixa.appendChild(rotulo); caixa.appendChild(entrada); montarPin('#edPinEntrada', function (v) { ed.pinNovo = v; ed.removerPin = false; desenharPinEdicao(); });
    if (ed.hasPin && !ed.removerPin) {
      var rm = el('button', 'link', 'Remover o PIN'); rm.type = 'button';
      rm.addEventListener('click', function () { ed.removerPin = true; ed.pinNovo = null; desenharPinEdicao(); });
      acoes.appendChild(rm);
    }
    caixa.appendChild(acoes);
  }
  function salvarEdicao() {
    var ed = estado.edit; var msg = $('#edMsg'); msg.textContent = '';
    var corpo = { id: ed.id || '', name: $('#edNome').value.trim(), avatar: ed.avatar,
      infantil: $('#edInfantil').checked, role: ($('#edAdmin').checked && !$('#edInfantil').checked) ? 'admin' : 'user' };
    $('#edSalvar').disabled = true;
    api('/api/profiles/save', corpo).then(function (d) {
      if (d.status !== 'ok') { msg.textContent = d.error || 'Não foi possível salvar.'; throw 0; }
      var id = ed.id || d.created; var ultimo = d;
      if (ed.pinNovo || ed.removerPin) {
        return api('/api/profiles/pin', { id: id, pin: ed.pinNovo || null }).then(function (r) {
          if (r.status !== 'ok') { msg.textContent = r.error || 'Não foi possível salvar o PIN.'; throw 0; } return r; });
      }
      return ultimo;
    }).then(function (d) { fechar('#modalEdicao'); aplicar(d); })
      .catch(function () {}).then(function () { $('#edSalvar').disabled = false; });
  }
  function excluirPerfil() {
    var ed = estado.edit; if (!ed.id) return;
    if (!window.confirm('Remover este perfil? O histórico de exibição dele será apagado.')) return;
    api('/api/profiles/delete', { id: ed.id }).then(function (d) {
      if (d.status !== 'ok') { $('#edMsg').textContent = d.error || 'Não foi possível remover.'; return; }
      fechar('#modalEdicao'); aplicar(d);
    });
  }

  function sairDaConta() {
    api('/api/auth/logout', {}).then(function () { window.location.replace('/'); });
  }

  document.addEventListener('DOMContentLoaded', function () {
    montarPin('#pinEntrada', function (v) { if (pinAlvo) selecionar(pinAlvo.id, v); });
    $('#btnGerenciar').addEventListener('click', alternarGerenciar);
    $('#btnSair').addEventListener('click', sairDaConta);
    $('#pinCancelar').addEventListener('click', function () { fechar('#modalPin'); });
    $('#senhaCancelar').addEventListener('click', function () { fechar('#modalSenha'); });
    $('#senhaOk').addEventListener('click', confirmarSenha);
    $('#senhaConta').addEventListener('keydown', function (e) { if (e.key === 'Enter') confirmarSenha(); });
    $('#edCancelar').addEventListener('click', function () { fechar('#modalEdicao'); });
    $('#edSalvar').addEventListener('click', salvarEdicao);
    $('#edExcluir').addEventListener('click', excluirPerfil);
    $('#edInfantil').addEventListener('change', function () { $('#edAdminLinha').style.display = this.checked ? 'none' : ''; });
    $('#edNome').addEventListener('keydown', function (e) { if (e.key === 'Enter') salvarEdicao(); });
    document.addEventListener('keydown', function (e) { if (e.key === 'Escape') ['#modalPin', '#modalSenha', '#modalEdicao'].forEach(fechar); });
    api('/api/profiles').then(function (d) {
      if (d.status !== 'ok') { window.location.replace('/'); return; }
      estado.editando = false; aplicar(d);
      if (new URLSearchParams(location.search).get('gerenciar') === '1' && estado.podeGerenciar) { estado.editando = true; desenhar(); }
      if (estado.me) { $('#btnVoltar').style.display = ''; }
    });
    $('#btnVoltar').addEventListener('click', entrar);
  });
})();
"""


def _profiles_page():
    """Seletor "Quem esta assistindo?": escolher perfil (com PIN, se tiver) e,
    para quem pode, criar/editar perfis com avatar, perfil infantil e PIN."""
    marca = _branding.get()
    cor = marca["cor"]
    css = _PROFILES_CSS.replace("__COR__", cor).replace("__COR_HOVER__", _branding._clarear(cor))
    wordmark = _WORDMARK.replace("__MARCA__", marca["nome"])
    return """<!DOCTYPE html>
<html lang="pt-BR"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex">
<title>Quem esta assistindo? · __NOME__</title>
<link rel="icon" href="/favicon.svg">
<style>__FONTE____CSS__</style>
</head><body>
<header>
  __WORDMARK__
  <div>
    <button class="link" id="btnVoltar" type="button" style="display:none">Voltar ao app</button>
    <button class="link" id="btnSair" type="button">Sair da conta</button>
  </div>
</header>
<main>
  <h1 id="titulo">Quem está assistindo?</h1>
  <p class="sub" id="subtitulo"></p>
  <div class="grid" id="grade"></div>
  <div class="acoes"><button class="btn" id="btnGerenciar" type="button">Gerenciar perfis</button></div>
</main>

<div class="modal" id="modalPin" role="dialog" aria-modal="true" aria-labelledby="pinTitulo">
  <div class="caixa">
    <h2 id="pinTitulo">Perfil protegido</h2>
    <p class="d">Digite o PIN de 4 números de <strong id="pinNome"></strong>.</p>
    <div class="pin" id="pinEntrada"></div>
    <div class="msg" id="pinMsg" role="alert"></div>
    <div class="linha"><button class="btn" id="pinCancelar" type="button">Cancelar</button></div>
  </div>
</div>

<div class="modal" id="modalSenha" role="dialog" aria-modal="true" aria-labelledby="senhaTitulo">
  <div class="caixa">
    <h2 id="senhaTitulo">Confirme a senha da conta</h2>
    <p class="d">Para gerenciar perfis, digite a senha do login da casa.</p>
    <input class="t" id="senhaConta" type="password" autocomplete="current-password" aria-label="Senha da conta">
    <div class="msg" id="senhaMsg" role="alert"></div>
    <div class="linha"><button class="btn" id="senhaCancelar" type="button">Cancelar</button>
      <button class="btn primario" id="senhaOk" type="button">Continuar</button></div>
  </div>
</div>

<div class="modal" id="modalEdicao" role="dialog" aria-modal="true" aria-labelledby="edTitulo">
  <div class="caixa">
    <h2 id="edTitulo">Editar perfil</h2>
    <label class="l" for="edNome">Nome</label>
    <input class="t" id="edNome" type="text" maxlength="20" autocomplete="off">
    <label class="l">Avatar</label>
    <div class="avs" id="edAvatares"></div>
    <label class="opt"><input type="checkbox" id="edInfantil"><div><b>Perfil infantil</b>
      <span>Só mostra os filmes que você liberou, sem exceção.</span></div></label>
    <label class="opt" id="edAdminLinha"><input type="checkbox" id="edAdmin"><div><b>Administrador</b>
      <span>Pode gerenciar perfis, fontes, nuvem e backup.</span></div></label>
    <div class="pinbox" id="edPin"></div>
    <div class="msg" id="edMsg" role="alert"></div>
    <div class="linha">
      <button class="btn perigo esq" id="edExcluir" type="button">Remover perfil</button>
      <button class="btn" id="edCancelar" type="button">Cancelar</button>
      <button class="btn primario" id="edSalvar" type="button">Salvar</button>
    </div>
  </div>
</div>
<script>__JS__</script>
</body></html>""".replace("__FONTE__", _FONT_FACE).replace("__CSS__", css).replace("__JS__", _PROFILES_JS) \
        .replace("__WORDMARK__", wordmark).replace("__NOME__", marca["nome"])
