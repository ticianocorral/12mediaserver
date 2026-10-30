/* Modo TV — navegacao pelo controle remoto.
 *
 * Carregado apenas quando a URL tem ?tv=1, entao nada aqui roda para quem usa
 * o 12:00 Media Server no computador ou no celular.
 *
 * O trabalho pesado (escolher o vizinho na direcao da seta) fica com o polyfill
 * de spatial navigation do W3C. Este arquivo cuida do que e especifico daqui:
 * tornar focavel o que so tem onclick, ativar com Enter, e sair da frente
 * enquanto o player esta aberto.
 */
(function () {
  'use strict';

  // ── Layout previsivel ────────────────────────────────────────
  // O viewport e "width=device-width", e a largura em CSS px de uma TV varia
  // com a densidade — perto demais do corte de 768px do layout de celular.
  // Fixar 1536 garante o layout de desktop em qualquer aparelho, e de quebra
  // amplia tudo: numa tela de 1920 a WebView escala 1536 para 1920 (1,25x).
  var vp = document.querySelector('meta[name="viewport"]');
  if (vp) vp.setAttribute('content', 'width=1536, initial-scale=1.0');
  document.documentElement.classList.add('modo-tv');

  // ── O que vira focavel ───────────────────────────────────────
  // Regra por comportamento, nao por lista de classes: tudo que tem onclick e
  // nao e focavel por natureza. Assim telas novas (series, colecoes) entram
  // sozinhas, sem ninguem lembrar de atualizar este arquivo.
  // Ligado enquanto o player esta aberto: as setas passam a ser dele.
  var playerAberto = null;

  var CLICAVEL = '[onclick]:not(button):not(a):not(input):not(select):not(textarea)';
  // Panos de fundo existem para fechar no clique: focar neles nao leva a lugar
  // nenhum e ainda engole uma parada da navegacao.
  var IGNORAR = '.sidebar-backdrop, .modal-overlay, .player-overlay';

  function marcarFocaveis() {
    var nodes = document.querySelectorAll(CLICAVEL);
    for (var i = 0; i < nodes.length; i++) {
      var el = nodes[i];
      if (el.hasAttribute('tabindex')) continue;
      if (el.matches(IGNORAR)) continue;
      el.setAttribute('tabindex', '0');
      el.classList.add('tv-focavel');
    }
  }

  // ── Enter ativa ──────────────────────────────────────────────
  // O navegador so dispara click no Enter para <button> e <a>. Os cartoes sao
  // <div onclick>, entao o Enter deles e por nossa conta. Restrito a
  // .tv-focavel de proposito: campo de busca continua recebendo Enter normal.
  document.addEventListener('keydown', function (e) {
    if (e.key !== 'Enter') return;
    var el = document.activeElement;
    if (!el || !el.classList.contains('tv-focavel')) return;
    e.preventDefault();
    el.click();
  });

  // ── Setas sem keyCode ────────────────────────────────────────
  // O polyfill decide a direcao lendo so e.keyCode, que e propriedade obsoleta.
  // Navegador de verdade sempre preenche, mas basta um ambiente que mande
  // apenas e.key para a navegacao morrer calada — e numa TV isso seria o
  // controle inteiro sem funcionar. O guarda !e.keyCode faz esta ponte nunca
  // disparar junto com o polyfill; ela so cobre o buraco.
  var SETAS = {
    ArrowLeft: 'left', ArrowUp: 'up', ArrowRight: 'right', ArrowDown: 'down',
  };
  document.addEventListener('keydown', function (e) {
    if (e.keyCode) return;
    var dir = SETAS[e.key];
    if (!dir || typeof window.navigate !== 'function') return;
    if (playerAberto) return;
    var alvo = document.activeElement;
    // Dentro de um campo de texto a seta anda com o cursor, nao com o foco.
    if (alvo && (alvo.nodeName === 'INPUT' || alvo.nodeName === 'TEXTAREA')) return;
    e.preventDefault();
    window.navigate(dir);
  });

  // ── Rolar quando nao ha candidato visivel ────────────────────
  // O polyfill so considera candidatos dentro da area visivel, e nao rola este
  // documento sozinho. Numa grade mais alta que a tela isso trava o foco na
  // ultima linha visivel: as setas param de responder e a pagina nem
  // acompanha — na TV parece que o controle quebrou.
  //
  // O listener e no document, que borbulha antes do window onde o polyfill
  // escuta; o setTimeout garante que so agimos depois que ele teve sua chance.
  function direcaoVertical(e) {
    if (e.keyCode === 38 || e.key === 'ArrowUp') return 'up';
    if (e.keyCode === 40 || e.key === 'ArrowDown') return 'down';
    return null;
  }

  document.addEventListener('keydown', function (e) {
    var dir = direcaoVertical(e);
    if (!dir || playerAberto) return;
    var antes = document.activeElement;
    if (antes && (antes.nodeName === 'INPUT' || antes.nodeName === 'TEXTAREA')) return;
    setTimeout(function () {
      if (document.activeElement !== antes) return;   // o polyfill deu conta
      var antesY = window.scrollY;
      var passo = Math.round(window.innerHeight * 0.55) * (dir === 'down' ? 1 : -1);
      // 'instant' e nao 'auto': 'auto' quer dizer "siga o CSS", e o CSS daqui
      // pede rolagem suave — a proxima linha so entraria na tela depois da
      // animacao, tarde demais para contar como candidata logo abaixo.
      window.scrollTo({ top: antesY + passo, behavior: 'instant' });
      if (window.scrollY === antesY) return;          // acabou a pagina
      if (typeof window.navigate === 'function') window.navigate(dir);
    }, 0);
  });

  // ── Rolagem ao focar ─────────────────────────────────────────
  // Sem isto o foco anda para um cartao fora da tela e o usuario ve uma pagina
  // parada. 'nearest' rola o minimo necessario; a suavidade vem do CSS.
  document.addEventListener('focusin', function (e) {
    var el = e.target;
    if (el && el.scrollIntoView) {
      el.scrollIntoView({ block: 'nearest', inline: 'nearest' });
    }
  });

  // ── Player: as setas sao dele ────────────────────────────────
  // Dentro do player as setas ja avancam o filme e mudam o volume
  // (app.js). Deixar a navegacao espacial ligada faria as duas coisas ao mesmo
  // tempo, entao ela desliga enquanto o overlay esta ativo.
  function sincronizarPlayer() {
    var aberto = !!document.querySelector('#playerOverlay.active');
    if (aberto === playerAberto) return;
    playerAberto = aberto;
    if (window.__spatialNavigation__) {
      window.__spatialNavigation__.keyMode = aberto ? 'NONE' : 'ARROW';
    }
  }

  // ── O foco nunca pode ficar em lugar nenhum ──────────────────
  // Sem foco as setas nao tem de onde sair e o controle parece morto. Isto nao
  // pode ser disparo unico: o app troca #content inteiro por innerHTML, entao o
  // elemento focado e destruido a cada navegacao e o foco volta para o body.
  // Rodando a cada rajada de mudanca, o foco se recupera sozinho e ainda cai
  // no primeiro cartao da tela nova, que e o que se espera numa TV.
  function garantirFoco() {
    var atual = document.activeElement;
    if (atual && atual !== document.body && atual !== document.documentElement) return;
    var alvo = document.querySelector(
      '#content .tv-focavel, #content button, .sidebar-item');
    if (alvo) alvo.focus();
  }

  // ── Uma varredura por rajada ─────────────────────────────────
  // O app redesenha containers inteiros por innerHTML, entao o observador
  // dispara dezenas de vezes seguidas. Agrupar troca isso por uma varredura.
  //
  // setTimeout e nao requestAnimationFrame de proposito: rAF nao roda com a
  // janela em segundo plano, e bastaria uma mutacao nesse intervalo para o
  // 'pendente' ficar preso em true e a marcacao nunca mais voltar. Numa TV
  // isso seria o controle morrer depois de trocar de app e voltar.
  var pendente = false;
  function agendar() {
    if (pendente) return;
    pendente = true;
    setTimeout(function () {
      pendente = false;
      marcarFocaveis();
      sincronizarPlayer();
      garantirFoco();
    }, 0);
  }

  function iniciar() {
    marcarFocaveis();
    sincronizarPlayer();
    garantirFoco();
    // attributeFilter class: e assim que o player abre e fecha (.active), e
    // sem isso a navegacao espacial ficaria ligada por cima dele.
    new MutationObserver(agendar).observe(document.body, {
      childList: true, subtree: true,
      attributes: true, attributeFilter: ['class', 'style'],
    });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', iniciar);
  } else {
    iniciar();
  }
})();
