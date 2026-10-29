// Sessao expirada: qualquer chamada que volte 401 leva de volta ao login.
  (function () {
    var _fetch = window.fetch;
    window.fetch = function () {
      return _fetch.apply(this, arguments).then(function (res) {
        if (res.status === 401 && window.location.pathname !== '/login') {
          window.location.replace('/login');
        }
        return res;
      });
    };
  })();

  // ==================== STATE ====================
  let currentPath = "";

  // History navigation support
  window.addEventListener('popstate', function(e) {
    const path = (e.state && e.state.path) || '';
    // Close movie info overlay if open
    const overlay = document.getElementById('movieInfoOverlay');
    if (overlay && overlay.classList.contains('active')) {
      closeMovieInfo();
    }
    // Always load, even if same path (handles initial pop)
    loadPathInternal(path);
  });

  // ==================== API ====================
  async function apiFetch(endpoint) {
    try {
      const res = await fetch(endpoint);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      return await res.json();
    } catch (e) {
      console.error("API error:", e);
      return null;
    }
  }

  function streamUrl(filePath) {
    return '/api/stream?path=' + encodeURIComponent(filePath);
  }

  function posterUrl(folderPath, imageName) {
    if (!imageName) return null;
    // Algumas APIs (séries, coleções) já entregam o caminho completo da
    // imagem; colar de novo virava ".../Série//Local/.../poster.jpg" (404).
    // Nome de arquivo nunca tem "/" — a barra é o sinal de caminho pronto.
    const fullPath = imageName.indexOf('/') === -1
      ? folderPath + '/' + imageName
      : imageName;
    return '/api/stream?path=' + encodeURIComponent(fullPath);
  }

  // ==================== FORMAT ====================
  function formatSize(bytes) {
    if (!bytes) return '';
    const units = ['B', 'KB', 'MB', 'GB', 'TB'];
    let i = 0;
    let size = bytes;
    while (size >= 1024 && i < units.length - 1) { size /= 1024; i++; }
    return size.toFixed(1) + ' ' + units[i];
  }

  function formatDate(t) {
    if (!t) return '';
    const d = new Date(t);
    return d.toLocaleDateString('pt-BR');
  }

  function fileIcon(name) {
    return '<svg class="icon-svg"><use href="#i-film"></use></svg>';
  }

  // ==================== SIMPLE FRONTEND CACHE ====================
  let _frontCache = {};
  const _CACHE_TTL = 120000; // 2 min
  const _CACHE_ERROR_TTL = 5000; // 5s for error responses

  function _invalidateCache(url) {
    delete _frontCache[url];
  }

  function cachedFetch(url) {
    const now = Date.now();
    const entry = _frontCache[url];
    if (entry && (now - entry.time) < _CACHE_TTL) {
      return Promise.resolve(entry.data);
    }
    return apiFetch(url).then(data => {
      // Don't cache null/error responses for the full TTL — use shorter error TTL
      if (data === null) {
        _frontCache[url] = { data, time: Date.now() - (_CACHE_TTL - _CACHE_ERROR_TTL) };
      } else {
        _frontCache[url] = { data, time: Date.now() };
      }
      return data;
    });
  }

  // Override apiFetch calls to use cache where possible
  // ==================== SEARCH ====================
  let _searchTimer = null;
  let _lastSearchQuery = null;

  function _updateSearchClear() {
    const clear = document.getElementById('searchClear');
    if (clear) clear.classList.toggle('show', document.getElementById('searchInput').value.length > 0);
  }

  // Busca ao vivo: debounce enquanto digita; Enter dispara na hora
  function onSearchInput() {
    clearTimeout(_searchTimer);
    _updateSearchClear();
    const q = document.getElementById('searchInput').value.trim();
    if (!q) { loadPath(''); return; }
    _searchTimer = setTimeout(search, 250);
  }

  function clearSearch() {
    clearTimeout(_searchTimer);
    const input = document.getElementById('searchInput');
    input.value = '';
    _updateSearchClear();
    _lastSearchQuery = null;
    loadPath('');
    input.focus();
  }

  function search() {
    const q = document.getElementById('searchInput').value.trim();
    if (!q) { loadPath(''); return; }
    _updateSearchClear();
    // Só mostra o loading quando o termo mudou (evita flicker ao refinar a busca)
    if (_lastSearchQuery !== q) {
      _lastSearchQuery = q;
      document.getElementById('content').innerHTML = '<div class="loading"><div class="spinner"></div><span>Pesquisando...</span></div>';
    }

    cachedFetch('/api/search?q=' + encodeURIComponent(q)).then(data => {
      if (!data || !data.results) {
        document.getElementById('content').innerHTML = '<div class="empty-state"><div class="empty-icon"><svg class="icon-svg"><use href="#i-frown"></use></svg></div><h3>Erro na pesquisa</h3></div>';
        return;
      }
      renderResults(data.results, q);
    });
  }

  function renderResults(results, query) {
    const container = document.getElementById('content');
    if (results.length === 0) {
      container.innerHTML = `
        <div class="empty-state">
          <div class="empty-icon"><svg class="icon-svg"><use href="#i-search"></use></svg></div>
          <h3>Nenhum resultado encontrado</h3>
          <p>Tente outro termo de busca.</p>
        </div>
        <div class="genre-section">
          <div class="genre-header" onclick="loadPath('')">
            <div class="genre-title"><span class="arrow"><svg class="icon-svg"><use href="#i-arrow-left"></use></svg></span> Voltar ao início</div>
          </div>
        </div>`;
      return;
    }

    let html = `<div class="genre-section">
      <div class="genre-header" style="cursor:default;border:none">
        <div class="genre-title"><svg class="icon-svg"><use href="#i-search"></use></svg> Resultados para "${escHtml(query)}" <span class="genre-count">(${results.length})</span></div>
      </div>
      <div class="movie-grid">`;

    results.forEach(item => {
      const name = item.Name || '';
      const filePath = item.Path ? '/' + item.Path : '';
      const posterSrc = item.poster ? posterUrl(filePath.replace(/\/[^/]*$/, ''), item.poster) : null;
      html += renderMovieCardHtml(name, filePath, item.Size, posterSrc, item.watched);
    });

    html += `</div></div>
      <div class="genre-section">
        <div class="genre-header" onclick="loadPath('')">
          <div class="genre-title"><span class="arrow"><svg class="icon-svg"><use href="#i-arrow-left"></use></svg></span> Voltar ao início</div>
        </div>
      </div>`;

    container.innerHTML = html;
    document.getElementById('hero').style.display = 'none';
  }

  // ==================== GAVETA (celular) ====================
  // No celular a barra lateral sai do fluxo e vira gaveta; a barra superior
  // cuida do acesso. No desktop nada disso e usado — a barra fica fixa como
  // sempre esteve e estas funcoes nunca sao chamadas.
  function abrirGaveta(aberta) {
    const sb = document.getElementById('sidebar');
    const bd = document.getElementById('sidebarBackdrop');
    if (!sb) return;
    sb.classList.toggle('aberta', aberta);
    if (bd) bd.classList.toggle('ativo', aberta);
    // Trava a rolagem do fundo enquanto a gaveta cobre a tela.
    document.body.style.overflow = aberta ? 'hidden' : '';
  }

  function toggleSidebar() {
    const sb = document.getElementById('sidebar');
    abrirGaveta(!(sb && sb.classList.contains('aberta')));
  }

  function closeSidebar() { abrirGaveta(false); }

  function gavetaAberta() {
    const sb = document.getElementById('sidebar');
    return !!(sb && sb.classList.contains('aberta'));
  }

  // A lupa da barra superior: o campo de busca mora dentro da gaveta, entao
  // abrir uma coisa sem a outra deixaria o usuario sem caminho.
  function abrirBusca() {
    abrirGaveta(true);
    const campo = document.getElementById('searchInput');
    if (campo) setTimeout(function() { campo.focus(); }, 240);
  }

  // ==================== SIDEBAR ====================
  let _sidebarGenresLoaded = false;

  function sourceIcon(kind) {
    return kind === 'cloud'
      ? '<svg class="icon-svg"><use href="#i-cloud"></use></svg>'
      : '<svg class="icon-svg"><use href="#i-hard-drive"></use></svg>';
  }

  // Agrupa os generos pela fonte dona deles. O servidor manda o Path completo
  // de cada genero, entao nao ha prefixo remontado no cliente.
  // Marca no menu o item da tela atual. O HTML nasce com "Início" ativo, mas
  // quem manda é esta função: toda navegação passa por loadPathInternal ou
  // loadAZ, e eles redesenham a seleção — inclusive para tag, série e
  // coleção, que não são pastas.
  function _updateSidebarActive() {
    const atual = currentPath || '';
    document.querySelectorAll('#sidebarNav .sidebar-item[data-nav]').forEach(function (btn) {
      const alvo = btn.getAttribute('data-nav');
      let ativo = (alvo === atual);
      if (!ativo && alvo === 'home') ativo = isHomePage(atual);
      if (!ativo && alvo === 'series') ativo = atual.indexOf(SERIE_PREFIXO) === 0;
      if (!ativo && alvo === 'colecoes') ativo = atual.indexOf(COLECAO_PREFIXO) === 0;
      btn.classList.toggle('active', ativo);
    });
  }

  function loadSidebarGenres(force) {
    const container = document.getElementById('sidebarGenres');
    if (_sidebarGenresLoaded && !force) return;
    _sidebarGenresLoaded = true;
    // A barra lateral lista só as tags criadas na interface — gênero por
    // pasta deixou de existir. O "+" (admin) cria uma tag nova na hora.
    cachedFetch('/api/generos').then(generos => {
      const isAdmin = _me && _me.role === 'admin';
      let html = '<div class="sidebar-source-label"><svg class="icon-svg">'
        + '<use href="#i-layers"></use></svg> Tags'
        + (isAdmin
            ? ' <button class="sidebar-genre-add" onclick="openGeneroNovoModal()" title="Criar tag">+</button>'
            : '')
        + '</div>';
      (generos || []).forEach(g => {
        html += '<button class="sidebar-item" data-nav="' + GENERO_PREFIXO + g.id + '" onclick="loadPath(\'' + GENERO_PREFIXO + g.id + '\')">'
          + '<span class="icon"><svg class="icon-svg"><use href="#i-layers"></use></svg></span> '
          + escHtml(g.nome) + '</button>';
      });
      if (!generos || !generos.length) {
        html += '<div class="sidebar-sem-genero">Use o <b>+</b> para criar tags '
          + 'e reunir filmes nelas.</div>';
      }
      container.innerHTML = html;
      _updateSidebarActive();
    }).catch(() => {
      container.innerHTML = '';
    });
  }

  // ==================== HOME / GENRE LIST ====================
  function loadPath(path, replace) {
    const s = history.state;
    if (path !== (s && s.path)) {
      if (replace) {
        // Mantem a query na URL: e por ?tv=1 que o modo de controle remoto
        // sobrevive a um recarregamento dentro do app da TV.
        history.replaceState({ path: path }, '', window.location.pathname + window.location.search);
      } else {
        history.pushState({ path: path }, '', window.location.pathname + window.location.search);
      }
    }
    loadPathInternal(path);
  }

  function loadPathInternal(path) {
    closeSidebar();
    currentPath = path;
    _updateSidebarActive();
    document.getElementById('content').innerHTML = '<div class="loading"><div class="spinner"></div><span>Carregando...</span></div>';
    document.getElementById('searchInput').value = '';
    _updateSearchClear();

    // Close any open info overlay
    closeMovieInfo();

    // Coleção não é uma pasta, mas entra pelo mesmo caminho de navegação
    // (pushState/popstate) — assim o botão Voltar do navegador funciona nela
    // igual funciona numa tag, sem um segundo mecanismo de histórico.
    if (path && path.indexOf(COLECAO_PREFIXO) === 0) {
      renderCollectionView(path.slice(COLECAO_PREFIXO.length));
      return;
    }
    if (path && path.indexOf(SERIE_PREFIXO) === 0) {
      renderSerieView(decodeURIComponent(path.slice(SERIE_PREFIXO.length)));
      return;
    }
    if (path === LISTA_SERIES) {
      renderSeriesList();
      return;
    }
    // A página A-Z não é uma pasta: o clique em "Filmes", o refresh depois do
    // scan e uma volta no histórico caem todos aqui.
    if (path === LISTA_FILMES) {
      loadAZ();
      return;
    }
    if (path === LISTA_COLECOES) {
      renderCollectionsList();
      return;
    }
    if (path && path.indexOf(GENERO_PREFIXO) === 0) {
      renderGeneroView(path.slice(GENERO_PREFIXO.length));
      return;
    }

    const isHome = isHomePage(path);
    const url = isHome ? '/api/genres' : ('/api/list?path=' + encodeURIComponent(path));

    cachedFetch(url).then(data => {
      if (!data) {
        document.getElementById('content').innerHTML = '<div class="empty-state"><div class="empty-icon"><svg class="icon-svg"><use href="#i-error"></use></svg></div><h3>Erro ao carregar</h3><p>Não foi possível conectar ao servidor.</p></div>';
        return;
      }
      // Guarda a listagem: ao tocar um episódio desta pasta, a transmissão
      // monta a fila com os vizinhos (ver _playlistDaPastaAberta).
      _pastaAtual = { path: data.path || '', videos: data.videos || [] };
      renderDirectory(data);
    });
  }

  // ==================== A-Z VIEW ====================
  function loadAZ() {
    currentPath = LISTA_FILMES;
    closeSidebar();
    _updateSidebarActive();
    document.getElementById('searchInput').value = '';
    _updateSearchClear();
    closeMovieInfo();
    // Mesmo cabeçalho das outras páginas (Séries, Coleções): o hero com
    // título e contagem, em vez de um título solto dentro do conteúdo.
    const hero = document.getElementById('hero');
    hero.style.display = 'block';
    _heroCapa(null, null);
    document.getElementById('breadcrumb').innerHTML = '';
    document.getElementById('heroBg').style.backgroundImage = 'none';
    hero.style.background = 'linear-gradient(135deg, var(--bg2) 0%, var(--surface) 100%)';
    document.getElementById('heroTitle').innerHTML =
      '<svg class="icon-svg"><use href="#i-sort"></use></svg> Filmes';
    document.getElementById('heroDesc').textContent = '';
    const container = document.getElementById('content');
    container.innerHTML = '<div class="loading"><div class="spinner"></div><span>Carregando filmes...</span></div>';
    // Invalidate cache so we always get fresh data
    _invalidateCache('/api/all-movies');
    cachedFetch('/api/all-movies').then(movies => {
      if (!movies || movies.length === 0) {
        container.innerHTML = '<div class="empty-state"><div class="empty-icon"><svg class="icon-svg"><use href="#i-film"></use></svg></div><h3>Nenhum filme encontrado</h3></div>';
        return;
      }
      renderAZView(movies);
    });
  }

  function renderAZView(movies) {
    // Group by first letter
    const groups = {};
    movies.forEach(m => {
      const title = m.title || m.name || '';
      const letter = title.charAt(0).toUpperCase();
      if (!groups[letter]) groups[letter] = [];
      groups[letter].push(m);
    });

    const letters = Object.keys(groups).sort();

    document.getElementById('heroDesc').innerHTML =
      '<svg class="icon-svg"><use href="#i-sort"></use></svg> '
      + movies.length + (movies.length === 1 ? ' filme' : ' filmes');

    let html = '<div style="display:flex;flex-wrap:wrap;gap:4px;margin-bottom:24px;padding:0 4px" id="azJump">';
    letters.forEach(l => {
      html += '<a href="javascript:;" onclick="document.getElementById(\'az-' + l + '\').scrollIntoView({behavior:\'smooth\'});return false" style="display:inline-flex;align-items:center;justify-content:center;width:36px;height:36px;background:var(--surface);border-radius:6px;text-decoration:none;font-weight:700;font-size:15px;color:var(--accent);transition:background .2s">' + l + '</a>';
    });
    html += '</div>';

    letters.forEach(l => {
      const items = groups[l];
      html += '<div class="genre-section" id="az-' + l + '">';
      html += '<div class="genre-header" style="cursor:default;border:none;position:sticky;top:0;z-index:10;background:var(--bg)">';
      html += '<div class="genre-title">' + l + ' <span class="genre-count">(' + items.length + ')</span></div>';
      html += '</div><div class="movie-grid">';
      items.forEach(m => {
        const nameClean = (m.title || m.name || '').replace(/[._]/g, ' ').replace(/\.[^.]+$/, '');
        const safePath = enc(m.path);
        // Filme solto (arquivo avulso) não tem ficha: o clique toca direto.
        // Filme em pasta abre a ficha, como em todo o app.
        const clique = m.is_file
          ? 'playMovie(decodeURIComponent(\'' + safePath + '\'), decodeURIComponent(\'' + enc(nameClean) + '\'))'
          : 'showMovieInfo(decodeURIComponent(\'' + safePath + '\'), event)';
        const botaoGenero = (_me && _me.role === 'admin')
          ? '<button class="movie-card-genero" onclick="event.stopPropagation(); openGeneroFilmeModal(decodeURIComponent(\'' + safePath + '\'), decodeURIComponent(\'' + enc(nameClean) + '\'))" title="Tags do filme"><svg class="icon-svg"><use href="#i-layers"></use></svg></button>'
          : '';
        html += '<div class="movie-card" onclick="' + clique + '" title="' + escHtml(nameClean) + '">'
          + botaoGenero;
        if (m.poster) {
          html += '<img class="movie-card-poster" src="' + posterUrl(m.path, m.poster) + '" alt="' + escHtml(nameClean) + '" loading="lazy" onerror="this.style.display=\'none\';this.nextElementSibling.style.display=\'flex\'">';
          html += '<div class="movie-card-poster-placeholder" style="display:none"><svg class="icon-svg"><use href="#i-film"></use></svg></div>';
        } else {
          html += '<div class="movie-card-poster-placeholder" style="display:flex"><svg class="icon-svg"><use href="#i-film"></use></svg></div>';
        }
        html += _badgeAssistido(m);
        html += '<div class="movie-card-overlay"><div class="movie-card-title">' + escHtml(nameClean) + '</div>'
          + (m.is_file ? '<div class="movie-card-subtitle">arquivo solto</div>' : '')
          + '</div>';
        html += '</div>';
      });
      html += '</div></div>';
    });
    document.getElementById('content').innerHTML = html;
  }

  function isHomePage(path) {
    return path === '' || path === '/' || path === (window.__LOGICAL_ROOT__ || '/Media Server');
  }

  function renderDirectory(data) {
    const container = document.getElementById('content');
    const hero = document.getElementById('hero');
    hero.style.display = 'block';
    _heroCapa(null, null);

    const isHome = isHomePage(data.path);

    // Sem trilha do caminho de pastas: o acervo se navega por tags, series e
    // colecoes, nao pelo caminho do disco.
    document.getElementById('breadcrumb').innerHTML = '';
    const hasFolders = data.folders && data.folders.length > 0;
    const hasVideos = data.videos && data.videos.length > 0;
    const hasImages = data.images && data.images.length > 0;

    // If we're in a genre (1 level deep, has movie subfolders)
    if (!isHome && hasFolders && !hasVideos) {
      renderGenreView(container, data);
      return;
    }

    // If we're in a folder with videos directly
    if (!isHome && hasVideos) {
      renderVideoView(container, data);
      return;
    }

    // HOME PAGE: show all genres as sections
    if (isHome) {
      renderHomeView(container, data);
      return;
    }

    // Empty state
    if (!hasFolders && !hasVideos && !hasImages) {
      renderEmptyState(container, data.path);
      return;
    }

    // Fallback: show folders and videos
    renderGenericView(container, data);
  }

  // ===== HOME VIEW: summary + recent movies =====
  function renderHomeView(container, data) {
    const hero = document.getElementById('hero');
    hero.style.display = 'none';
    document.getElementById('heroTitle').textContent = '';
    document.getElementById('heroDesc').textContent = '';
    document.getElementById('heroBg').style.backgroundImage = 'none';

    // A home tem tres secoes de filme: novidades, o que ficou pela metade e o
    // que esta baixado. Navegar por fonte e por genero e papel da barra
    // lateral, que ja agrupa os generos pela fonte dona.
    container.innerHTML = `
      <div class="home-stats">
        <div class="home-stat" onclick="loadAZ()" title="Ver todos os filmes">
          <div class="home-stat-icon"><svg class="icon-svg"><use href="#i-film"></use></svg></div>
          <div class="home-stat-num" id="statMovies">—</div>
          <div class="home-stat-label">Filmes no acervo</div>
        </div>
        <div class="home-stat" onclick="loadSeries()" title="Ver todas as séries">
          <div class="home-stat-icon"><svg class="icon-svg"><use href="#i-tv"></use></svg></div>
          <div class="home-stat-num" id="statSeries">—</div>
          <div class="home-stat-label">Séries no acervo</div>
        </div>
        <div class="home-stat" onclick="openSourcesOrSettings()" title="Fontes do acervo">
          <div class="home-stat-icon"><svg class="icon-svg"><use href="#i-hard-drive"></use></svg></div>
          <div class="home-stat-num" id="statSources">—</div>
          <div class="home-stat-label" id="statSourcesLabel">Fontes conectadas</div>
        </div>
        <div class="home-stat" onclick="openCacheManager()" title="Gerenciar o cache offline">
          <div class="home-stat-icon"><svg class="icon-svg"><use href="#i-download"></use></svg></div>
          <div class="home-stat-num" id="statDownloaded">—</div>
          <div class="home-stat-label" id="statDownloadedLabel">Baixados da nuvem</div>
        </div>
      </div>
      <div class="genre-section">
        <div class="genre-header" style="cursor:default;border:none">
          <div class="genre-title"><svg class="icon-svg"><use href="#i-download"></use></svg> Últimos Adicionados</div>
        </div>
        <div class="movie-grid" id="recentGrid">
          <div class="loading"><div class="spinner"></div><span>Carregando...</span></div>
        </div>
      </div>
      <div class="genre-section" id="continueWatchingSection" style="display:none">
        <div class="genre-header" style="cursor:default;border:none">
          <div class="genre-title"><svg class="icon-svg"><use href="#i-play"></use></svg> Continuar Assistindo</div>
        </div>
        <div class="movie-grid" id="continueWatchingGrid"></div>
        <div class="episodio-lista" id="continueWatchingLista"></div>
      </div>
      <div class="genre-section" id="offlineSection" style="display:none">
        <div class="genre-header" style="cursor:default;border:none">
          <div class="genre-title"><svg class="icon-svg"><use href="#i-download"></use></svg> Baixados da nuvem</div>
        </div>
        <div class="movie-grid" id="offlineGrid"></div>
      </div>`;

    _loadHomeStats();

    // Fetch recent movies sorted by actual creation time (from server)
    cachedFetch('/api/recent-movies?limit=30').then(movies => {
      renderRecentMovies(movies || []);
    });

    function renderRecentMovies(movies) {
      const grid = document.getElementById('recentGrid');
      if (!grid) return;
      if (movies.length === 0) {
        grid.innerHTML = '<div class="empty-state"><div class="empty-icon"><svg class="icon-svg"><use href="#i-inbox"></use></svg></div><h3>Nenhum filme ainda</h3></div>';
        return;
      }
      // Show up to 7 newest
      const recent = movies.slice(0, 7);

      let html = '';
      recent.forEach((m, idx) => {
        const nameClean = (m.title || m.name || '').replace(/[._]/g, ' ').replace(/\.[^.]+$/, '');
        const safePath = enc(m.path);
        const cliqueRecente = m.is_serie
          ? 'loadPath(\'' + SERIE_PREFIXO + safePath + '\')'
          : 'showMovieInfo(decodeURIComponent(\'' + safePath + '\'), event)';
        html += '<div class="movie-card" onclick="' + cliqueRecente + '" title="' + escHtml(m.name) + '">'
          + '<div class="movie-card-poster-placeholder" style="display:flex"><svg class="icon-svg"><use href="#i-film"></use></svg></div>'
          + _badgeAssistido(m)
          + '<div class="movie-card-overlay">'
          + '<div class="movie-card-title">' + escHtml(nameClean) + '</div>'
          + '</div></div>';
        // Load poster using the poster name from the server response
        if (m.poster) {
          const img = document.createElement('img');
          img.className = 'movie-card-poster';
          img.src = posterUrl(m.path, m.poster);
          img.alt = escHtml(m.name);
          img.style.cssText = 'width:100%;height:100%;object-fit:cover;position:absolute;inset:0';
          img.onerror = () => img.remove();
          // Attach after card is in DOM
          setTimeout(() => {
            const cards = grid.querySelectorAll('.movie-card');
            if (cards[idx]) cards[idx].appendChild(img);
          }, 0);
        }
      });
      grid.innerHTML = html;
    }

    // Carrega "Continuar Assistindo"
    cachedFetch('/api/continue-watching').then(items => {
      const section = document.getElementById('continueWatchingSection');
      const grid = document.getElementById('continueWatchingGrid');
      if (!section || !grid) return;
      if (!items || items.length === 0) {
        section.style.display = 'none';
        return;
      }
      section.style.display = '';
      let html2 = '';
      let linhas = '';
      items.forEach((m, idx) => {
        const pct = (m.duration > 0) ? Math.round((m.position / m.duration) * 100) : 0;
        const posStr = Math.floor(m.position / 60) + ':' + String(Math.floor(m.position % 60)).padStart(2, '0');
        const tipo = m.tipo || 'filme';

        // Episódio de série e filme solto: linha com retomada direta.
        if (tipo === 'episodio' || tipo === 'solto') {
          const rotulo = tipo === 'episodio'
            ? m.serie + ' · ' + m.temporada + ' · ' + m.episodio
            : m.name;
          linhas += '<button class="episodio-linha" onclick="playMovie(decodeURIComponent(\''
            + enc(m.path) + '\'), decodeURIComponent(\'' + enc(rotulo) + '\')'
            + (m.subtitle ? ', decodeURIComponent(\'' + enc(m.subtitle) + '\')' : ', null')
            + ', ' + Math.floor(m.position) + ')">'
            + '<span class="episodio-play"><svg class="icon-svg"><use href="#i-play"></use></svg></span>'
            + '<span class="episodio-titulo">' + escHtml(rotulo)
            + ' <span class="episodio-tamanho">' + posStr + ' assistido</span></span>'
            + '<span class="episodio-progresso"><span style="width:' + pct + '%"></span></span>'
            + '</button>';
          return;
        }

        // Filme em pasta: poster card com retomada pela ficha (como sempre).
        const nameClean = (m.title || m.name || '').replace(/[._]/g, ' ');
        const safePath = enc(m.path);
        html2 += '<div class="movie-card" onclick="showMovieInfo(decodeURIComponent(\'' + safePath + '\'), event)" title="' + escHtml(m.name) + '">'
          + '<div class="movie-card-poster-placeholder" style="display:flex"><svg class="icon-svg"><use href="#i-film"></use></svg></div>'
          + '<div class="movie-card-overlay">'
          + '<div class="movie-card-title">' + escHtml(nameClean) + '</div>'
          + '<div class="movie-card-subtitle">' + posStr + ' assistido</div>'
          + '</div>'
          + '<div class="progress-bar-wrap"><div class="progress-bar-fill" style="width:' + pct + '%"></div></div>'
          + '</div>';
        // Load poster
        if (m.poster) {
          const img = document.createElement('img');
          img.className = 'movie-card-poster';
          img.src = posterUrl(m.path, m.poster);
          img.alt = escHtml(m.name);
          img.style.cssText = 'width:100%;height:100%;object-fit:cover;position:absolute;inset:0';
          img.onerror = () => img.remove();
          setTimeout(() => {
            const cards = grid.querySelectorAll('.movie-card');
            if (cards[idx]) cards[idx].appendChild(img);
          }, 0);
        }
      });
      // Séries e soltos em progresso entram no MESMO campo, logo abaixo
      // dos cards de filme — um único "Continuar Assistindo".
      const listaEl = document.getElementById('continueWatchingLista');
      if (listaEl) listaEl.innerHTML = linhas;      grid.innerHTML = html2;
    });

    // Carrega filmes marcados como offline
    _renderOfflineGrid();
  }

  // Estatisticas da home. As duas fontes de dado ja existiam; o que muda e
  // mostrar o que importa num acervo com varias fontes, em vez de contar
  // generos. As contagens de filme e serie sao as mesmas das paginas A-Z e
  // Series (ver cached_movie_count/cached_series_count no servidor).
  function _loadHomeStats() {
    cachedFetch('/api/cache-status').then(st => {
      if (!st) return;
      const filmes = document.getElementById('statMovies');
      if (filmes) filmes.textContent = st.movies != null ? st.movies : '—';
      const series = document.getElementById('statSeries');
      if (series) series.textContent = st.series != null ? st.series : '—';
      const baixLabel = document.getElementById('statDownloadedLabel');
      const uso = st.usage && st.usage.details ? st.usage.details.vfs : 0;
      if (baixLabel && uso > 0) {
        baixLabel.textContent = 'Baixados · ' + formatSize(uso);
      }
    });

    const baix = document.getElementById('statDownloaded');
    if (baix) baix.textContent = _cachedSet.size;

    cachedFetch('/api/sources').then(d => {
      if (!d || !d.sources) return;
      const el = document.getElementById('statSources');
      const label = document.getElementById('statSourcesLabel');
      if (!el) return;
      const total = d.sources.length;
      const online = d.sources.filter(s => s.online).length;
      el.textContent = (online === total) ? String(total) : (online + '/' + total);
      if (label) {
        label.textContent = (online === total)
          ? (total === 1 ? 'Fonte conectada' : 'Fontes conectadas')
          : 'Fontes conectadas';
      }
    });
  }

  // O painel de fontes e de admin; quem nao e cai no hub de Ajustes.
  function openSourcesOrSettings() {
    if (_me && _me.role === 'admin') openSourcesModal();
    else openSettingsModal();
  }

  // ==================== COLEÇÕES ====================
  // Agrupamentos de filmes criados na própria interface (sagas, franquias).
  // O valor depois do prefixo é o id da coleção no banco.
  const COLECAO_PREFIXO = 'colecao:';
  const LISTA_COLECOES = 'colecoes';
  const GENERO_PREFIXO = 'genero:';
  const SERIE_PREFIXO = 'serie:';
  const LISTA_SERIES = 'series';
  const LISTA_FILMES = '__az__';

  // url() de CSS com aspas. Sem elas o parser rejeita a regra inteira quando o
  // caminho tem parenteses — e "Filme (1980)" e justamente a convencao de
  // nomes do acervo, entao o fundo simplesmente nao aparecia.
  function cssUrl(u) {
    return 'url("' + String(u).replace(/["\\\n]/g, function(c) {
      return '\\' + (c === '\n' ? 'A ' : c);
    }) + '")';
  }

  // Capa grande no cabecalho. Centralizado num helper porque o hero e
  // compartilhado por todas as telas: sem um ponto unico de limpeza, a capa
  // de uma colecao ficaria pendurada ao navegar pra um genero.
  function _heroCapa(poster, fanart) {
    const img = document.getElementById('heroCapa');
    const hero = document.getElementById('hero');
    const bg = document.getElementById('heroBg');
    if (!img || !hero) return;
    // As telas ligam hero.style.display='block' inline, e estilo inline ganha
    // da classe: por isso o display de linha tambem sai daqui, senao a capa
    // fica empilhada em cima do titulo em vez de ao lado.
    if (poster) {
      img.src = streamUrl(poster);
      img.style.display = '';
      img.onerror = function() {
        this.style.display = 'none';
        hero.classList.remove('com-capa');
        hero.style.display = 'block';
      };
      hero.classList.add('com-capa');
      hero.style.display = 'flex';
    } else {
      img.removeAttribute('src');
      img.style.display = 'none';
      hero.classList.remove('com-capa');
      hero.style.display = 'block';
    }
    if (bg) {
      if (fanart) {
        bg.style.backgroundImage = cssUrl(streamUrl(fanart));
        bg.classList.add('ativo');
      } else {
        bg.style.backgroundImage = 'none';
        bg.classList.remove('ativo');
      }
    }
  }

  function abrirColecao(nome) { loadPath(COLECAO_PREFIXO + nome); }
  function loadCollections() { loadPath(LISTA_COLECOES); }
  function loadSeries() { loadPath(LISTA_SERIES); }

  // ==================== LISTA DE SÉRIES ====================
  function renderSeriesList() {
    const container = document.getElementById('content');
    const hero = document.getElementById('hero');
    hero.style.display = 'block';
    _heroCapa(null, null);
    document.getElementById('breadcrumb').innerHTML = '';
    document.getElementById('heroBg').style.backgroundImage = 'none';
    hero.style.background = 'linear-gradient(135deg, var(--bg2) 0%, var(--surface) 100%)';
    document.getElementById('heroTitle').innerHTML =
      '<svg class="icon-svg"><use href="#i-tv"></use></svg> Séries';
    document.getElementById('heroDesc').textContent = '';

    cachedFetch('/api/series').then(series => {
      if (!series || series.length === 0) {
        container.innerHTML = '<div class="empty-state">'
          + '<div class="empty-icon"><svg class="icon-svg"><use href="#i-tv"></use></svg></div>'
          + '<h3>Nenhuma série no acervo</h3>'
          + '<p>Dentro da pasta <b>tv shows</b> do acervo, crie uma pasta por série '
          + 'e, dentro dela, as temporadas (S01, S02...) com os episódios.</p></div>';
        return;
      }
      document.getElementById('heroDesc').innerHTML =
        '<svg class="icon-svg"><use href="#i-tv"></use></svg> '
        + series.length + (series.length === 1 ? ' série' : ' séries');
      // A-Z igual ao menu de Filmes: navegação por letra + seções.
      const grupos = {};
      series.forEach(s => {
        const letra = (s.title || s.name || '').charAt(0).toUpperCase();
        (grupos[letra] = grupos[letra] || []).push(s);
      });
      const letras = Object.keys(grupos).sort();
      let html = '<div style="display:flex;flex-wrap:wrap;gap:4px;margin-bottom:24px;padding:0 4px">';
      letras.forEach(l => {
        html += '<a href="javascript:;" onclick="document.getElementById(\'azs-' + l + '\').scrollIntoView({behavior:\'smooth\'});return false" '
          + 'style="display:inline-flex;align-items:center;justify-content:center;width:36px;height:36px;background:var(--surface);border-radius:6px;text-decoration:none;font-weight:700;font-size:15px;color:var(--accent)">' + l + '</a>';
      });
      html += '</div>';
      letras.forEach(l => {
        html += '<div class="genre-section" id="azs-' + l + '">'
          + '<div class="genre-header" style="cursor:default;border:none;position:sticky;top:0;z-index:10;background:var(--bg)">'
          + '<div class="genre-title">' + l
          + ' <span class="genre-count">(' + grupos[l].length + ')</span></div></div>'
          + '<div class="movie-grid">';
        grupos[l].forEach(s => {
          const titulo = escHtml(s.title);
          const poster = s.poster ? streamUrl(s.poster) : null;
          const meta = s.temporadas
            + (s.temporadas === 1 ? ' temporada · ' : ' temporadas · ')
            + s.episodios + (s.episodios === 1 ? ' episódio' : ' episódios');
          html += '<div class="movie-card" onclick="loadPath(\'' + SERIE_PREFIXO + enc(s.path) + '\')" title="' + titulo + '">'
            + (poster
                ? '<img class="movie-card-poster" src="' + poster + '" alt="' + titulo
                  + '" loading="lazy" onerror="this.style.display=\'none\';'
                  + 'this.nextElementSibling.style.display=\'flex\'">'
                  + '<div class="movie-card-poster-placeholder" style="display:none">'
                  + '<svg class="icon-svg"><use href="#i-tv"></use></svg></div>'
                : '<div class="movie-card-poster-placeholder" style="display:flex">'
                  + '<svg class="icon-svg"><use href="#i-tv"></use></svg></div>')
            + '<div class="movie-card-overlay"><div class="movie-card-title">' + titulo + '</div>'
            + '<div class="movie-card-subtitle">' + meta + '</div>'
            + '</div></div>';
        });
        html += '</div></div>';
      });
      container.innerHTML = html;
    });
  }

  function renderCollectionsList() {
    const container = document.getElementById('content');
    const hero = document.getElementById('hero');
    hero.style.display = 'block';
    _heroCapa(null, null);
    document.getElementById('breadcrumb').innerHTML = '';
    document.getElementById('heroTitle').innerHTML =
      '<svg class="icon-svg"><use href="#i-layers"></use></svg> Coleções';
    document.getElementById('heroBg').style.backgroundImage = 'none';
    hero.style.background = 'linear-gradient(135deg, var(--bg2) 0%, var(--surface) 100%)';

    const botaoNova = (_me && _me.role === 'admin')
      ? '<button class="btn btn-primary colecao-nova-btn" onclick="openColecaoModal()">'
        + '<svg class="icon-svg"><use href="#i-plus"></use></svg> Nova coleção</button>'
      : '';
    cachedFetch('/api/collections').then(cols => {
      document.getElementById('heroDesc').innerHTML =
        '<svg class="icon-svg"><use href="#i-layers"></use></svg> '
        + (cols && cols.length ? cols.length + (cols.length === 1 ? ' coleção' : ' coleções') : '');
      if (!cols || cols.length === 0) {
        container.innerHTML = botaoNova + '<div class="empty-state">'
          + '<div class="empty-icon"><svg class="icon-svg"><use href="#i-layers"></use></svg></div>'
          + '<h3>Nenhuma coleção ainda</h3>'
          + '<p>Agrupe filmes num só lugar: uma saga, uma franquia, o que você quiser. '
          + 'Crie a coleção, escolha os filmes e a capa — tudo por aqui.</p></div>';
        return;
      }
      let html = '<div class="genre-section">' + botaoNova + '<div class="colecao-lista">';
      cols.forEach(c => {
        html += '<button class="colecao-item" onclick="abrirColecao(' + c.id + ')">'
          + (c.poster
              ? '<img class="colecao-capa" src="' + streamUrl(c.poster) + '" alt="" '
                + 'loading="lazy" onerror="this.remove()">'
              : '<span class="colecao-icone"><svg class="icon-svg"><use href="#i-layers"></use></svg></span>')
          + '<span class="colecao-nome">' + escHtml(c.name) + '</span>'
          + '<span class="colecao-conta">' + c.total
          + (c.total === 1 ? ' filme' : ' filmes') + '</span></button>';
      });
      container.innerHTML = html + '</div></div>';
    });
  }

  function renderCollectionView(nome) {
    const container = document.getElementById('content');
    const hero = document.getElementById('hero');
    hero.style.display = 'block';
    document.getElementById('heroBg').style.backgroundImage = 'none';
    hero.style.background = 'linear-gradient(135deg, var(--bg2) 0%, var(--surface) 100%)';

    document.getElementById('breadcrumb').innerHTML =
      '<a onclick="loadPath(\'\')"><svg class="icon-svg"><use href="#i-home"></use></svg> Início</a>'
      + ' <span class="sep">›</span> <a onclick="loadCollections()">Coleções</a>'
      + ' <span class="sep">›</span> <span>' + escHtml(nome) + '</span>';

    cachedFetch('/api/collection?key=' + encodeURIComponent(nome)).then(col => {
      if (!col || !col.movies) {
        container.innerHTML = '<div class="empty-state"><div class="empty-icon">'
          + '<svg class="icon-svg"><use href="#i-error"></use></svg></div>'
          + '<h3>Coleção não encontrada</h3></div>';
        return;
      }
      // O endereço guarda o id; o nome de verdade chega na resposta.
      const ultimoBc = document.querySelector('#breadcrumb span:last-child');
      if (ultimoBc) ultimoBc.textContent = col.name;
      _heroCapa(col.poster, col.fanart);
      document.getElementById('heroTitle').innerHTML =
        (col.poster ? '' : '<svg class="icon-svg"><use href="#i-layers"></use></svg> ')
        + escHtml(col.name);
      const acoesAdmin = (_me && _me.role === 'admin')
        ? '<button class="colecao-acao-btn" onclick="openColecaoModal(' + col.id + ')">'
          + '<svg class="icon-svg"><use href="#i-gear"></use></svg> Editar</button>'
          + '<button class="colecao-acao-btn perigo" onclick="excluirColecao(' + col.id
          + ', decodeURIComponent(\'' + enc(col.name) + '\'))">'
          + '<svg class="icon-svg"><use href="#i-trash"></use></svg> Excluir</button>'
        : '';
      document.getElementById('heroDesc').innerHTML =
        '<span class="colecao-acoes">' + acoesAdmin + '</span>'
        + '<svg class="icon-svg"><use href="#i-film"></use></svg> ' + col.movies.length
        + (col.movies.length === 1 ? ' filme' : ' filmes')
        + (col.overview ? '<div class="colecao-sinopse">' + escHtml(col.overview) + '</div>' : '');

      // Ordenados por ano no servidor — é o que põe a saga na ordem certa.
      let html = '<div class="genre-section"><div class="movie-grid">';
      col.movies.forEach(m => {
        // Cartão próprio em vez de renderMovieCardHtml: filme abre a ficha,
        // série abre a página dela (com as temporadas). Pôster e ano vêm
        // prontos da API, sem regex no nome da pasta.
        const titulo = escHtml((m.title || m.name).replace(/[._]/g, ' '));
        const poster = m.poster ? posterUrl(m.path, m.poster) : null;
        const clique = m.is_serie
          ? 'loadPath(\'' + SERIE_PREFIXO + enc(m.path) + '\')'
          : 'showMovieInfo(decodeURIComponent(\'' + enc(m.path) + '\'), event)';
        html += '<div class="movie-card" onclick="' + clique + '" title="' + titulo + '">'
          + (poster
              ? '<img class="movie-card-poster" src="' + poster + '" alt="' + titulo
                + '" loading="lazy" onerror="this.style.display=\'none\';'
                + 'this.nextElementSibling.style.display=\'flex\'">'
                + '<div class="movie-card-poster-placeholder" style="display:none">'
                + '<svg class="icon-svg"><use href="#i-film"></use></svg></div>'
              : '<div class="movie-card-poster-placeholder">'
                + '<svg class="icon-svg"><use href="#i-film"></use></svg></div>')
          + _badgeAssistido(m)
          + '<div class="movie-card-overlay"><div class="movie-card-title">' + titulo + '</div>'
          + '<div class="movie-card-subtitle">' + (m.year ? escHtml(m.year) : 'Filme') + '</div>'
          + '</div></div>';
      });
      container.innerHTML = html + '</div></div>';
    });
  }

  // ==================== COLEÇÕES: CRIAR / EDITAR ====================
  // Estado do modal. filmes é um Set de folder_path; a ordem de escolha é a
  // que a capa picker apresenta. capa é o folder_path do filme escolhido.
  let _colecao = null;
  let _colecaoTodos = null;   // cache de /api/all-movies pro seletor
  let _colecaoBusca = '';

  function _colecaoAbrirEstado(id) {
    document.getElementById('colecaoModalTitulo').innerHTML =
      '<svg class="icon-svg"><use href="#i-layers"></use></svg> '
      + (id ? 'Editar coleção' : 'Nova coleção');
    if (id) {
      return cachedFetch('/api/collection?key=' + id).then(col => {
        if (!col) return null;
        return {
          id: col.id, nome: col.name, descricao: col.overview || '',
          filmes: col.movies.map(m => ({ path: m.path, title: m.title, poster: m.poster })),
          capa: col.capa_path || (col.movies.length === 1 ? col.movies[0].path : ''),
        };
      });
    }
    return Promise.resolve({ id: null, nome: '', descricao: '', filmes: [], capa: '' });
  }

  function openColecaoModal(id) {
    const conteudo = document.getElementById('colecaoModalConteudo');
    conteudo.innerHTML = '<div class="loading" style="min-height:140px">'
      + '<div class="spinner"></div><span>Carregando filmes...</span></div>';
    document.getElementById('colecaoModal').classList.add('active');
    document.body.style.overflow = 'hidden';
    Promise.all([
      _colecaoAbrirEstado(id || null),
      cachedFetch('/api/all-movies'),
      cachedFetch('/api/series'),
    ]).then(([estado, filmes, series]) => {
      if (!estado) {
        conteudo.innerHTML = '<div class="empty-state"><div class="empty-icon">'
          + '<svg class="icon-svg"><use href="#i-error"></use></svg></div>'
          + '<h3>Coleção não encontrada</h3></div>';
        return;
      }
      // Filmes e séries lado a lado no seletor: uma coleção pode misturar.
      const seriesFormatadas = (series || []).map(s => ({
        path: s.path, name: s.name, title: s.title, is_serie: true,
        poster: s.poster, _capaPronta: s.poster ? streamUrl(s.poster) : null,
      }));
      _colecaoTodos = (filmes || []).concat(seriesFormatadas);
      _colecao = {
        id: estado.id, nome: estado.nome, descricao: estado.descricao,
        capa: estado.capa,
        filmes: new Map(estado.filmes.map(f => [f.path, {
          path: f.path, title: f.title, poster: f.poster,
          is_serie: f.is_serie,
          _capaPronta: f.is_serie && f.poster ? streamUrl(f.poster) : null,
        }])),
      };
      _colecaoBusca = '';
      _colecaoRenderPasso1();
    }).catch(() => {
      conteudo.innerHTML = '<div class="user-msg err">Falha ao carregar.</div>';
    });
  }

  function closeColecaoModal() {
    document.getElementById('colecaoModal').classList.remove('active');
    document.body.style.overflow = '';
    _colecao = null;
    _colecaoBusca = '';
  }
  document.getElementById('colecaoModal').addEventListener('click', function(e) {
    if (e.target === this) closeColecaoModal();
  });

  function _colecaoRenderPasso1() {
    const conteudo = document.getElementById('colecaoModalConteudo');
    let html = '<label class="colecao-campo"><span>Nome da coleção</span>'
      + '<input id="colecaoNome" type="text" maxlength="80" placeholder="Ex.: Star Wars — a saga completa" '
      + 'value="' + escHtml(_colecao.nome) + '"></label>'
      + '<label class="colecao-campo"><span>Descrição <em>(opcional)</em></span>'
      + '<textarea id="colecaoDescricao" rows="2" maxlength="300" '
      + 'placeholder="Uma linha sobre o conjunto...">' + escHtml(_colecao.descricao) + '</textarea></label>'
      + '<div class="colecao-secao-titulo">Filmes da coleção '
      + '<span class="colecao-contador" id="colecaoContador"></span></div>'
      + '<input id="colecaoBusca" class="colecao-busca" type="text" '
      + 'placeholder="Filtrar por título..." value="' + escHtml(_colecaoBusca) + '" '
      + 'oninput="_colecaoFiltrar(this.value)">'
      + '<div class="colecao-picker" id="colecaoPicker"></div>'
      + '<div class="colecao-passos">'
      + '<span></span>'
      + '<button class="rclone-action-btn primary" onclick="_colecaoIrParaCapa()">Continuar →</button>'
      + '</div>'
      + '<div id="colecaoMsg"></div>';
    conteudo.innerHTML = html;
    document.getElementById('colecaoBusca').addEventListener('keydown', function(e) {
      if (e.key === 'Enter') e.preventDefault();
    });
    _colecaoRenderPicker();
  }

  function _colecaoFiltrar(valor) {
    _colecaoBusca = valor;
    _colecaoRenderPicker();
  }

  function _colecaoRenderPicker() {
    const picker = document.getElementById('colecaoPicker');
    if (!picker) return;
    const busca = _colecaoBusca.trim().toLowerCase();
    // Selecionados primeiro (na ordem em que entraram), depois o resto — assim
    // a seleção não some ao filtrar. Sem busca, mostra só os escolhidos + aviso.
    const escolhidos = [..._colecao.filmes.keys()];
    const ordem = escolhidos.concat(
      _colecaoTodos.filter(m => !escolhidos.includes(m.path))
        .map(m => m.path));
    const termos = ordem.filter(path => {
      if (busca) {
        const m = _colecaoTodos.find(x => x.path === path)
          || _colecao.filmes.get(path);
        const titulo = ((m && (m.title || m.name)) || '').toLowerCase();
        if (!titulo.includes(busca)) return false;
      }
      return true;
    });
    if (!termos.length) {
      picker.innerHTML = '<div class="colecao-picker-vazio">Nenhum filme encontrado'
        + (busca ? ' para "' + escHtml(_colecaoBusca) + '".' : '.') + '</div>';
      _colecaoAtualizarContador();
      return;
    }
    let html = '';
    termos.forEach(path => {
      const m = _colecaoTodos.find(x => x.path === path) || _colecao.filmes.get(path);
      const escolhido = _colecao.filmes.has(path);
      const titulo = escHtml((m.title || m.name || '').replace(/[._]/g, ' '));
      const poster = m.poster ? posterUrl(m.path, m.poster) : null;
      html += '<button class="colecao-filme' + (escolhido ? ' escolhido' : '') + '" '
        + 'onclick="_colecaoToggle(\'' + enc(path) + '\')" title="' + titulo + '">'
        + (poster
            ? '<img src="' + poster + '" alt="" loading="lazy" onerror="this.remove()">'
            : '<span class="colecao-filme-sem"><svg class="icon-svg"><use href="#i-film"></use></svg></span>')
        + '<span class="colecao-filme-check"><svg class="icon-svg"><use href="#i-check"></use></svg></span>'
        + '<span class="colecao-filme-titulo">' + titulo + '</span>'
        + '</button>';
    });
    picker.innerHTML = html;
    _colecaoAtualizarContador();
  }

  function _colecaoToggle(pathEnc) {
    const path = decodeURIComponent(pathEnc);
    if (_colecao.filmes.has(path)) {
      _colecao.filmes.delete(path);
      if (_colecao.capa === path) _colecao.capa = '';
    } else {
      const m = _colecaoTodos.find(x => x.path === path);
      _colecao.filmes.set(path, { path: path, title: (m && m.title) || path,
        poster: (m && m.poster) || null, _capaPronta: m && m._capaPronta });
    }
    _colecaoRenderPicker();
  }

  function _colecaoAtualizarContador() {
    const el = document.getElementById('colecaoContador');
    if (el) el.textContent = _colecao.filmes.size
      + (_colecao.filmes.size === 1 ? ' filme escolhido' : ' filmes escolhidos');
  }

  // ── Passo 2: capa ──
  function _colecaoIrParaCapa() {
    _colecao.nome = (document.getElementById('colecaoNome').value || '').trim();
    _colecao.descricao = (document.getElementById('colecaoDescricao').value || '').trim();
    if (!_colecao.nome) {
      _colecaoMostrarErro('Dê um nome à coleção.');
      return;
    }
    if (_colecao.filmes.size === 0) {
      _colecaoMostrarErro('Escolha pelo menos um filme.');
      return;
    }
    if (!_colecao.capa) {
      _colecao.capa = _colecao.filmes.keys().next().value;
    }
    _colecaoRenderPasso2();
  }

  function _colecaoRenderPasso2() {
    const conteudo = document.getElementById('colecaoModalConteudo');
    let grade = '';
    for (const [path, f] of _colecao.filmes) {
      const poster = f.poster ? posterUrl(f.path, f.poster) : null;
      grade += '<button class="colecao-capa-opcao' + (_colecao.capa === path ? ' escolhida' : '') + '" '
        + 'onclick="_colecaoEscolherCapa(\'' + enc(path) + '\')">'
        + (poster
            ? '<img src="' + poster + '" alt="" onerror="this.parentElement.classList.add(\'sem-poster\'); this.remove()">'
            : '')
        + '<span class="colecao-capa-titulo">' + escHtml((f.title || '').replace(/[._]/g, ' ')) + '</span>'
        + '<span class="colecao-capa-check"><svg class="icon-svg"><use href="#i-check"></use></svg></span>'
        + '</button>';
    }
    conteudo.innerHTML = '<div class="colecao-secao-titulo">Qual capa usar?</div>'
      + '<p class="colecao-dica">O pôster do filme escolhido representa a coleção — '
      + 'você pode trocar depois em Editar.</p>'
      + '<div class="colecao-capa-grade">' + grade + '</div>'
      + '<div class="colecao-passos">'
      + '<button class="rclone-action-btn" onclick="_colecaoRenderPasso1()">← Voltar</button>'
      + '<button class="rclone-action-btn primary" id="colecaoSalvarBtn" onclick="_colecaoSalvar()">'
      + (_colecao.id ? 'Salvar alterações' : 'Criar coleção') + '</button>'
      + '</div>'
      + '<div id="colecaoMsg"></div>';
  }

  function _colecaoEscolherCapa(pathEnc) {
    _colecao.capa = decodeURIComponent(pathEnc);
    _colecaoRenderPasso2();
  }

  function _colecaoMostrarErro(texto) {
    const msg = document.getElementById('colecaoMsg');
    if (msg) msg.innerHTML = '<div class="user-msg err">' + escHtml(texto) + '</div>';
  }

  function _colecaoSalvar() {
    const btn = document.getElementById('colecaoSalvarBtn');
    if (btn) { btn.disabled = true; btn.textContent = 'Salvando...'; }
    fetch(_colecao.id ? '/api/colecoes/update' : '/api/colecoes/create', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        id: _colecao.id,
        nome: _colecao.nome,
        descricao: _colecao.descricao,
        capa: _colecao.capa,
        filmes: [..._colecao.filmes.keys()],
      }),
    }).then(res => res.json()).then(data => {
      if (data.status === 'ok') {
        closeColecaoModal();
        showToast('✅ ' + (data.message || 'Coleção salva.'), 'success');
        _invalidateCache('/api/collections');
        loadCollections();
      } else {
        _colecaoMostrarErro(data.error || 'Não foi possível salvar.');
        if (btn) { btn.disabled = false; btn.textContent = _colecao.id ? 'Salvar alterações' : 'Criar coleção'; }
      }
    }).catch(() => {
      _colecaoMostrarErro('Falha de conexão com o servidor.');
      if (btn) { btn.disabled = false; btn.textContent = _colecao.id ? 'Salvar alterações' : 'Criar coleção'; }
    });
  }

  function excluirColecao(id, nome) {
    _confirmarGenerico(
      'Excluir coleção?',
      'A coleção "' + nome + '" vai embora. Os filmes não são tocados — continuam no acervo, nas suas tags.',
      function() {
        fetch('/api/colecoes/delete', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ id: id }),
        }).then(res => res.json()).then(data => {
          if (data.status === 'ok') {
            showToast('Coleção excluída', 'success');
            _invalidateCache('/api/collections');
            loadCollections();
          } else {
            showToast('Erro: ' + (data.error || 'falha ao excluir'), 'error');
          }
        }).catch(() => showToast('Erro ao excluir coleção', 'error'));
      });
  }

  // Reaproveita o modal de confirmação do player para qualquer decisão:
  // troca os textos, encaminha o OK e devolve os textos originais ao fechar.
  function _confirmarGenerico(titulo, descricao, aoConfirmar) {
    const modal = document.getElementById('confirmModal');
    const tit = modal.querySelector('.confirm-title');
    const desc = modal.querySelector('.confirm-desc');
    const icon = modal.querySelector('.confirm-icon');
    const cancel = modal.querySelector('.confirm-btn.cancel');
    const sim = document.getElementById('confirmYesBtn');
    const originais = { tit: tit.textContent, desc: desc.textContent,
                        icon: icon.textContent, cancel: cancel.textContent,
                        sim: sim.textContent };
    tit.textContent = titulo;
    desc.textContent = descricao;
    icon.textContent = '🗑️';
    cancel.textContent = 'Manter';
    sim.textContent = 'Excluir';
    modal.classList.add('active');
    document.body.style.overflow = 'hidden';
    sim.onclick = function() {
      modal.classList.remove('active');
      _confirmarRestaurar(originais);
      document.body.style.overflow = '';
      aoConfirmar();
    };
    cancel.onclick = function() {
      modal.classList.remove('active');
      _confirmarRestaurar(originais);
      document.body.style.overflow = '';
    };
  }
  // Igual ao _confirmarGenerico, mas com um campo de texto — usado para
  // renomear. O OK entrega o valor digitado (vazio = cancelado).
  function _confirmarGenericoComInput(titulo, valorInicial, aoConfirmar) {
    const modal = document.getElementById('confirmModal');
    const body = modal.querySelector('.confirm-body');
    let input = document.getElementById('confirmInputDinamico');
    if (!input) {
      input = document.createElement('input');
      input.id = 'confirmInputDinamico';
      input.className = 'confirm-input';
      body.insertBefore(input, body.querySelector('.confirm-actions'));
    }
    input.style.display = '';
    input.value = valorInicial || '';
    _confirmarGenerico(titulo, '', function() {
      const v = input.value.trim();
      input.style.display = 'none';
      aoConfirmar(v);
    });
    const cancel = modal.querySelector('.confirm-btn.cancel');
    const cancelOriginal = cancel.onclick;
    cancel.onclick = function() {
      input.style.display = 'none';
      if (cancelOriginal) cancelOriginal();
    };
    setTimeout(() => input.focus(), 80);
  }

  function _confirmarRestaurar(originais) {
    const modal = document.getElementById('confirmModal');
    modal.querySelector('.confirm-title').textContent = originais.tit;
    modal.querySelector('.confirm-desc').textContent = originais.desc;
    modal.querySelector('.confirm-icon').textContent = originais.icon;
    modal.querySelector('.confirm-btn.cancel').textContent = originais.cancel;
    document.getElementById('confirmYesBtn').textContent = originais.sim;
    // O onclick do "Sair" é reatribuído pelo próprio fluxo de saída do player.
  }

  // ==================== SÉRIES ====================
  function renderSerieView(seriePath) {
    const container = document.getElementById('content');
    const hero = document.getElementById('hero');
    hero.style.display = 'block';
    document.getElementById('breadcrumb').innerHTML =
      '<a onclick="loadPath(\'\')"><svg class="icon-svg"><use href="#i-home"></use></svg> Início</a>'
      + ' <span class="sep">›</span> <span id="serieBcNome">...</span>';

    cachedFetch('/api/serie?path=' + encodeURIComponent(seriePath)).then(serie => {
      if (!serie) {
        container.innerHTML = '<div class="empty-state"><div class="empty-icon">'
          + '<svg class="icon-svg"><use href="#i-error"></use></svg></div>'
          + '<h3>Série não encontrada</h3></div>';
        return;
      }
      _heroCapa(serie.poster, serie.fanart);
      // Guarda a ficha da série: capa, sinopse e episódios em ordem. A
      // transmissão usa isso para mostrar a capa da série (o episódio não
      // tem pôster próprio) e para emendar o próximo episódio no fim.
      (function() {
        var epsSerie = [];
        serie.temporadas.forEach(function(t) {
          (t.episodios || []).forEach(function(e) { epsSerie.push(e); });
        });
        _serieAtual = {
          path: seriePath,
          poster: serie.poster || null,
          fanart: serie.fanart || null,
          overview: serie.overview || null,
          year: serie.year || null,
          episodios: epsSerie,
        };
      })();
      document.getElementById('serieBcNome').textContent = serie.name;
      document.getElementById('heroTitle').textContent = serie.name;
      const isAdmin = _me && _me.role === 'admin';
      const totalEps = serie.temporadas.reduce((n, t) => n + t.episodios.length, 0);
      document.getElementById('heroDesc').innerHTML =
        (isAdmin ? '<span class="colecao-acoes">'
          + switchInfantilHtml(seriePath, serie.infantil, 'Perfil infantil',
                               'vale para a série inteira: todas as temporadas e episódios')
          + '</span>' : '')
        + '<svg class="icon-svg"><use href="#i-tv"></use></svg> '
        + serie.temporadas.length + (serie.temporadas.length === 1 ? ' temporada · ' : ' temporadas · ')
        + totalEps + (totalEps === 1 ? ' episódio' : ' episódios')
        + (serie.overview ? '<div class="colecao-sinopse">' + escHtml(serie.overview) + '</div>' : '');

      if (!serie.temporadas.length) {
        container.innerHTML = '<div class="empty-state"><div class="empty-icon">'
          + '<svg class="icon-svg"><use href="#i-tv"></use></svg></div>'
          + '<h3>Nenhum episódio ainda</h3>'
          + '<p>Dentro da pasta da série, crie as pastas das temporadas '
          + '(S01, S02...) e ponha os episódios dentro delas.</p></div>';
        return;
      }
      let html = '';
      serie.temporadas.forEach(temp => {
        html += '<div class="genre-section">'
          + '<div class="genre-header" style="cursor:default;border:none">'
          + '<div class="genre-title">' + escHtml(temp.nome)
          + ' <span class="genre-count">(' + temp.episodios.length + ')</span></div></div>'
          + '<div class="episodio-lista">';
        temp.episodios.forEach(ep => {
          // Episódio pela metade: retoma de onde parou e oferece "Já assisti".
          const temProgresso = (ep.position || 0) > 5 &&
            (!ep.duration || (ep.position / ep.duration) <= 0.95);
          const posStr = Math.floor((ep.position || 0) / 60) + ':' +
            String(Math.floor((ep.position || 0) % 60)).padStart(2, '0');
          const pct = (ep.duration > 0) ? Math.round((ep.position / ep.duration) * 100) : 0;
          html += '<button class="episodio-linha' + (temProgresso ? ' em-progresso' : '') + '" '
            + 'onclick="playMovie(decodeURIComponent(\'' + enc(ep.path) + '\'), '
            + 'decodeURIComponent(\'' + enc(ep.title) + '\')'
            + (ep.subtitle ? ', decodeURIComponent(\'' + enc(ep.subtitle) + '\')' : ', null')
            + (temProgresso ? ', ' + Math.floor(ep.position) : ', null')
            + ', decodeURIComponent(\'' + enc(ep.path) + '\')'
            + ')" title="' + escHtml(ep.title) + '">'
            + '<span class="episodio-play"><svg class="icon-svg"><use href="#i-'
            + (temProgresso ? 'pause' : 'play') + '"></use></svg></span>'
            + '<span class="episodio-titulo">' + escHtml(ep.title)
            + (temProgresso ? ' <span class="episodio-pos">' + posStr + '</span>' : '')
            + '</span>'
            + '<span class="episodio-tamanho">' + formatSize(ep.size) + '</span>'
            + (ep.subtitle ? '<span class="episodio-cc" title="Com legenda">CC</span>' : '')
            + (temProgresso
                ? '<span class="episodio-progresso" title="' + pct + '% assistido">'
                  + '<span style="width:' + pct + '%"></span></span>'
                : '')
            + (temProgresso
                ? '<span class="episodio-assistido" onclick="event.stopPropagation();'
                  + 'limparProgressoEpisodio(decodeURIComponent(\'' + enc(ep.path) + '\'), this)" '
                  + 'title="Remove o progresso deste episódio">Já assisti</span>'
                : (ep.watched
                    // Selo do assistido: clicável para RETIRAR a marcação.
                    ? '<span class="episodio-assistido episodio-visto" '
                      + 'onclick="event.stopPropagation();'
                      + '_desmarcarEpisodio(decodeURIComponent(\'' + enc(ep.path) + '\'), this)" '
                      + 'title="Assistido — clique para retirar a marcação">✓ Assistido</span>'
                    : ''))
            + '</button>';
        });
        html += '</div></div>';
      });
      container.innerHTML = html;
    });
  }

  // Retira a marcação "assistido" do episódio: apaga a linha de progresso
  // (o /api/watched com on:false — a mesma tecla que o switch da ficha).
  function _desmarcarEpisodio(epPath, el) {
    fetch('/api/watched', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ path: epPath, on: false }),
    }).then(r => r.json()).then(data => {
      if (data && data.status === 'error') throw new Error(data.error || 'erro');
      if (el) el.remove();
      if (_serieAtual && _serieAtual.path) {
        _invalidateCache('/api/serie?path=' + encodeURIComponent(_serieAtual.path));
      }
      showToast('✖ Fora de assistidos', 'success');
    }).catch(() => showToast('Erro ao retirar a marcação', 'error'));
  }

  function limparProgressoEpisodio(epPath, el) {
    fetch('/api/progress', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ path: epPath, position: 0, duration: 0 }),
      keepalive: true,
    }).then(() => {
      const linha = el.closest('.episodio-linha');
      if (!linha) return;
      linha.classList.remove('em-progresso');
      linha.querySelectorAll('.episodio-progresso, .episodio-assistido, .episodio-pos')
        .forEach(x => x.remove());
      const play = linha.querySelector('.episodio-play use');
      if (play) play.setAttribute('href', '#i-play');
      // Vira o selo "✓ Assistido" (com a mesma saída de marcação).
      linha.insertAdjacentHTML('beforeend',
        '<span class="episodio-assistido episodio-visto" '
        + 'onclick="event.stopPropagation();'
        + '_desmarcarEpisodio(decodeURIComponent(\'' + enc(epPath) + '\'), this)" '
        + 'title="Assistido — clique para retirar a marcação">✓ Assistido</span>');
      if (_serieAtual && _serieAtual.path) {
        _invalidateCache('/api/serie?path=' + encodeURIComponent(_serieAtual.path));
      }
      showToast('✔ Episódio marcado como assistido', 'success');
    }).catch(() => showToast('Erro ao limpar progresso', 'error'));
  }

  // ==================== TAGS DO APP ====================
  // Criadas na interface, independentes de pastas. Uma tag reúne filmes de
  // qualquer fonte; filmes soltos entram pelo path do próprio arquivo.

  function renderGeneroView(generoId) {
    const container = document.getElementById('content');
    const hero = document.getElementById('hero');
    hero.style.display = 'block';
    _heroCapa(null, null);
    document.getElementById('heroBg').style.backgroundImage = 'none';
    hero.style.background = 'linear-gradient(135deg, var(--bg2) 0%, var(--surface) 100%)';
    document.getElementById('breadcrumb').innerHTML =
      '<a onclick="loadPath(\'\')"><svg class="icon-svg"><use href="#i-home"></use></svg> Início</a>'
      + ' <span class="sep">›</span> <span id="generoBcNome">...</span>';

    cachedFetch('/api/genero?id=' + generoId).then(gen => {
      if (!gen) {
        container.innerHTML = '<div class="empty-state"><div class="empty-icon">'
          + '<svg class="icon-svg"><use href="#i-error"></use></svg></div>'
          + '<h3>Tag não encontrada</h3></div>';
        return;
      }
      document.getElementById('generoBcNome').textContent = gen.name;
      document.getElementById('heroTitle').innerHTML =
        '<svg class="icon-svg"><use href="#i-layers"></use></svg> ' + escHtml(gen.name);
      const isAdmin = _me && _me.role === 'admin';
      document.getElementById('heroDesc').innerHTML =
        (isAdmin ? '<span class="colecao-acoes">'
          + '<button class="colecao-acao-btn" onclick="openGeneroRenomear(' + gen.id
          + ', decodeURIComponent(\'' + enc(gen.name) + '\'))">'
          + '<svg class="icon-svg"><use href="#i-gear"></use></svg> Renomear</button>'
          + '<button class="colecao-acao-btn perigo" onclick="excluirGenero(' + gen.id
          + ', decodeURIComponent(\'' + enc(gen.name) + '\'))">'
          + '<svg class="icon-svg"><use href="#i-trash"></use></svg> Excluir</button>'
          + '</span>' : '')
        + '<svg class="icon-svg"><use href="#i-film"></use></svg> ' + gen.movies.length
        + (gen.movies.length === 1 ? ' filme' : ' filmes');

      if (!gen.movies.length) {
        container.innerHTML = '<div class="empty-state"><div class="empty-icon">'
          + '<svg class="icon-svg"><use href="#i-film"></use></svg></div>'
          + '<h3>Nenhum filme nesta tag</h3>'
          + '<p>Abra a ficha de um filme (ou um card no A-Z) e toque em '
          + '<b>Tags</b> para colocá-lo aqui.</p></div>';
        return;
      }
      let html = '<div class="genre-section"><div class="movie-grid">';
      gen.movies.forEach(m => {
        const titulo = escHtml((m.title || m.name).replace(/[._]/g, ' '));
        const poster = m.poster ? posterUrl(m.path, m.poster) : null;
        const clique = m.is_file
          ? 'playMovie(decodeURIComponent(\'' + enc(m.path) + '\'), decodeURIComponent(\'' + enc(m.title || m.name) + '\'))'
          : 'showMovieInfo(decodeURIComponent(\'' + enc(m.path) + '\'), event)';
        html += '<div class="movie-card" onclick="' + clique + '" title="' + titulo + '">'
          + (poster
              ? '<img class="movie-card-poster" src="' + poster + '" alt="' + titulo
                + '" loading="lazy" onerror="this.style.display=\'none\';'
                + 'this.nextElementSibling.style.display=\'flex\'">'
                + '<div class="movie-card-poster-placeholder" style="display:none">'
                + '<svg class="icon-svg"><use href="#i-film"></use></svg></div>'
              : '<div class="movie-card-poster-placeholder" style="display:flex">'
                + '<svg class="icon-svg"><use href="#i-film"></use></svg></div>')
          + _badgeAssistido(m)
          + '<div class="movie-card-overlay"><div class="movie-card-title">' + titulo + '</div>'
          + '<div class="movie-card-subtitle">'
          + (m.is_file ? 'arquivo solto' : (m.year ? escHtml(m.year) : 'Filme'))
          + '</div></div></div>';
      });
      container.innerHTML = html + '</div></div>';
    });
  }

  // ── Modal: atribuir tags a um filme ──
  let _generoAlvo = null;

  function openGeneroFilmeModal(alvo, titulo) {
    _generoAlvo = { alvo: alvo, titulo: titulo };
    document.getElementById('generoFilmeTitulo').textContent = titulo;
    const corpo = document.getElementById('generoFilmeCorpo');
    corpo.innerHTML = '<div class="loading" style="min-height:90px"><div class="spinner"></div><span>Carregando...</span></div>';
    document.getElementById('generoFilmeMsg').innerHTML = '';
    document.getElementById('generoFilmeModal').classList.add('active');
    document.body.style.overflow = 'hidden';
    _invalidateCache('/api/generos');
    _invalidateCache('/api/generos/de?alvo=' + encodeURIComponent(alvo));
    Promise.all([
      cachedFetch('/api/generos'),
      cachedFetch('/api/generos/de?alvo=' + encodeURIComponent(alvo)),
    ]).then(([todos, meus]) => {
      _generoRenderChips(todos, (meus && meus.ids) || []);
    }).catch(() => {
      corpo.innerHTML = '<div class="user-msg err">Falha ao carregar tags.</div>';
    });
  }

  function _generoRenderChips(todos, meusIds) {
    const corpo = document.getElementById('generoFilmeCorpo');
    let chips = '';
    todos.forEach(g => {
      const on = meusIds.includes(g.id);
      chips += '<button class="genero-chip' + (on ? ' on' : '') + '" '
        + 'onclick="_generoToggleChip(this, ' + g.id + ')">' + escHtml(g.nome) + '</button>';
    });
    corpo.innerHTML = (todos.length
        ? '<div class="genero-chips">' + chips + '</div>'
        : '<p class="colecao-dica">Nenhuma tag criada ainda — crie a primeira abaixo.</p>')
      + '<div class="genero-nova-linha">'
      + '<input id="generoNovoNome" type="text" maxlength="40" placeholder="Nova tag...">'
      + '<button class="rclone-action-btn" onclick="_generoCriarEDar()">Criar</button>'
      + '</div>'
      + '<div class="colecao-passos"><span></span>'
      + '<button class="rclone-action-btn primary" onclick="closeGeneroFilmeModal()">Pronto</button>'
      + '</div>';
    corpo.dataset.meus = JSON.stringify(meusIds);
  }

  function _generoToggleChip(chip, id) {
    const corpo = document.getElementById('generoFilmeCorpo');
    const meus = JSON.parse(corpo.dataset.meus || '[]');
    const i = meus.indexOf(id);
    if (i >= 0) { meus.splice(i, 1); chip.classList.remove('on'); }
    else { meus.push(id); chip.classList.add('on'); }
    corpo.dataset.meus = JSON.stringify(meus);
  }

  function _generoCriarEDar() {
    const input = document.getElementById('generoNovoNome');
    const nome = (input.value || '').trim();
    if (!nome) return;
    fetch('/api/generos/create', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ nome: nome }),
    }).then(r => r.json()).then(data => {
      if (data.status !== 'ok') {
        document.getElementById('generoFilmeMsg').innerHTML =
          '<div class="user-msg err">' + escHtml(data.error || 'Erro.') + '</div>';
        return;
      }
      const corpo = document.getElementById('generoFilmeCorpo');
      const meus = JSON.parse(corpo.dataset.meus || '[]');
      if (!meus.includes(data.id)) meus.push(data.id);
      input.value = '';
      // Recarrega a lista para incluir a tag nova já marcada.
      _invalidateCache('/api/generos');
      cachedFetch('/api/generos').then(todos => _generoRenderChips(todos, meus));
      _sidebarGenerosRefresh();
    }).catch(() => {
      document.getElementById('generoFilmeMsg').innerHTML =
        '<div class="user-msg err">Falha de conexão.</div>';
    });
  }

  function closeGeneroFilmeModal() {
    const corpo = document.getElementById('generoFilmeCorpo');
    const meus = JSON.parse(corpo.dataset.meus || '[]');
    if (_generoAlvo) {
      fetch('/api/generos/atribuir', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ alvo: _generoAlvo.alvo, generos: meus }),
      }).then(r => r.json()).then(data => {
        if (data.status === 'ok') {
          showToast('✅ ' + data.message, 'success');
          (JSON.parse(document.getElementById('generoFilmeCorpo').dataset.meus || '[]'))
            .forEach(gid => _invalidateCache('/api/genero?id=' + gid));
          _invalidateCache('/api/genres');
          _invalidateCache('/api/all-movies');
        } else showToast('Erro: ' + (data.error || 'falha'), 'error');
      }).catch(() => showToast('Erro ao salvar tags', 'error'));
    }
    document.getElementById('generoFilmeModal').classList.remove('active');
    document.body.style.overflow = '';
    _generoAlvo = null;
    loadSidebarGenres(true);
    // Se estamos numa tag ou no A-Z, recarrega para refletir mudanças.
    if (currentPath && currentPath.indexOf(GENERO_PREFIXO) === 0) loadPath(currentPath, true);
  }
  document.getElementById('generoFilmeModal').addEventListener('click', function(e) {
    if (e.target === this) closeGeneroFilmeModal();
  });

  // ── Modal: criar tag (barra lateral) ──
  function openGeneroNovoModal() {
    document.getElementById('generoNovoInput').value = '';
    document.getElementById('generoNovoMsg').innerHTML = '';
    document.getElementById('generoNovoModal').classList.add('active');
    document.body.style.overflow = 'hidden';
    setTimeout(() => document.getElementById('generoNovoInput').focus(), 80);
  }
  function closeGeneroNovoModal() {
    document.getElementById('generoNovoModal').classList.remove('active');
    document.body.style.overflow = '';
  }
  document.getElementById('generoNovoModal').addEventListener('click', function(e) {
    if (e.target === this) closeGeneroNovoModal();
  });
  function criarGeneroDoModal() {
    const input = document.getElementById('generoNovoInput');
    const nome = (input.value || '').trim();
    if (!nome) return;
    fetch('/api/generos/create', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ nome: nome }),
    }).then(r => r.json()).then(data => {
      if (data.status !== 'ok') {
        document.getElementById('generoNovoMsg').innerHTML =
          '<div class="user-msg err">' + escHtml(data.error || 'Erro.') + '</div>';
        return;
      }
      closeGeneroNovoModal();
      showToast('✅ ' + data.message, 'success');
      _invalidateCache('/api/generos');
      loadSidebarGenres(true);
    }).catch(() => {
      document.getElementById('generoNovoMsg').innerHTML =
        '<div class="user-msg err">Falha de conexão.</div>';
    });
  }

  function _sidebarGenerosRefresh() { loadSidebarGenres(true); }

  function openGeneroRenomear(id, nomeAtual) {
    _confirmarGenericoComInput('Renomear tag', nomeAtual, function(novoNome) {
      if (!novoNome || novoNome === nomeAtual) return;
      fetch('/api/generos/renomear', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ id: id, nome: novoNome }),
      }).then(r => r.json()).then(data => {
        if (data.status === 'ok') {
          showToast('✅ ' + data.message, 'success');
          _invalidateCache('/api/genero?id=' + id);
          _invalidateCache('/api/generos');
          _invalidateCache('/api/genres');
          loadPath(GENERO_PREFIXO + id, true); loadSidebarGenres(true);
        }
        else showToast('Erro: ' + (data.error || 'falha'), 'error');
      }).catch(() => showToast('Erro ao renomear', 'error'));
    });
  }

  function excluirGenero(id, nome) {
    _confirmarGenerico('Excluir tag?',
      'A tag "' + nome + '" vai embora. Os filmes não são tocados.',
      function() {
        fetch('/api/generos/delete', {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ id: id }),
        }).then(r => r.json()).then(data => {
          if (data.status === 'ok') {
          showToast('✅ ' + data.message, 'success');
          _invalidateCache('/api/genero?id=' + id);
          _invalidateCache('/api/generos');
          _invalidateCache('/api/genres');
          loadPath(''); loadSidebarGenres(true);
        }
          else showToast('Erro: ' + (data.error || 'falha'), 'error');
        }).catch(() => showToast('Erro ao excluir tag', 'error'));
      });
  }

  // ==================== PERFIL INFANTIL ====================
  // Interruptor com rótulo claro: "Perfil infantil" + ON/OFF. O mesmo
  // componente serve para a ficha do filme e para a página da série
  // (na série, marcar vale para a série inteira — todas as temporadas).
  function switchInfantilHtml(alvo, ativo, rotulo, nota) {
    return '<span class="switch-infantil" onclick="toggleInfantil(this)">'
      + '<span class="switch-texto">'
      + '<span class="switch-rotulo">' + escHtml(rotulo || 'Perfil infantil') + '</span>'
      + (nota ? '<span class="switch-nota">' + escHtml(nota) + '</span>' : '')
      + '</span>'
      + '<span class="switch-track' + (ativo ? ' on' : '') + '" data-alvo="' + escHtml(alvo) + '" '
      + 'role="switch" aria-checked="' + (ativo ? 'true' : 'false') + '">'
      + '<span class="switch-knob"></span></span>'
      + '<span class="switch-estado">' + (ativo ? 'Sim' : 'Não') + '</span>'
      + '</span>';
  }

  function toggleInfantil(switchEl) {
    const raiz = switchEl.closest('.switch-infantil') || switchEl;
    const track = raiz.querySelector('.switch-track');
    const alvo = track.dataset.alvo;
    if (!alvo) return;
    const on = !track.classList.contains('on');
    raiz.style.pointerEvents = 'none';
    fetch('/api/infantil/marcar', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ alvo: alvo, on: on }),
    }).then(r => r.json()).then(data => {
      if (data.status === 'ok') {
        track.classList.toggle('on', data.on);
        track.setAttribute('aria-checked', data.on ? 'true' : 'false');
        const estado = raiz.querySelector('.switch-estado');
        if (estado) estado.textContent = data.on ? 'Sim' : 'Não';
        showToast((data.on ? '👶 No perfil infantil' : 'Fora do perfil infantil'), 'success');
        _invalidateCache('/api/all-movies');
        _invalidateCache('/api/recent-movies');
        _invalidateCache('/api/genres');
        _invalidateCache('/api/series');
      } else {
        showToast('Erro: ' + (data.error || 'falha'), 'error');
      }
    }).catch(() => showToast('Erro ao marcar', 'error'))
      .finally(() => { raiz.style.pointerEvents = ''; });
  }

  // ── Controles em pílula da ficha do filme ──────────────────
  // Mesma casca do interruptor do perfil infantil. "Já assisti" é interruptor
  // de verdade (marca/desmarca); "Tags" é um botão com a contagem que abre o
  // modal. Assim os dois deixam de parecer botõezinhos soltos na linha.

  function switchAssistidoHtml(folderPath, assistido) {
    return '<span class="pill-acao" onclick="toggleAssistido(this)">'
      + '<span class="switch-texto">'
      + '<span class="switch-rotulo">Já assisti</span>'
      + '<span class="switch-nota">' + (assistido ? 'Fora do continuar' : 'Marcar como visto') + '</span>'
      + '</span>'
      + '<span class="switch-track' + (assistido ? ' on' : '') + '" data-alvo="' + escHtml(folderPath) + '" '
      + 'role="switch" aria-checked="' + (assistido ? 'true' : 'false') + '">'
      + '<span class="switch-knob"></span></span>'
      + '<span class="switch-estado">' + (assistido ? 'Sim' : 'Não') + '</span>'
      + '</span>';
  }

  // Repinta o interruptor a partir de um estado conhecido — o /api/progress
  // que a ficha já buscava corrige um cache velho do movie-detail.
  function _pintarAssistido(raiz, on) {
    if (!raiz) return;
    const track = raiz.querySelector('.switch-track');
    if (track) {
      track.classList.toggle('on', on);
      track.setAttribute('aria-checked', on ? 'true' : 'false');
    }
    const estado = raiz.querySelector('.switch-estado');
    if (estado) estado.textContent = on ? 'Sim' : 'Não';
    const nota = raiz.querySelector('.switch-nota');
    if (nota) nota.textContent = on ? 'Fora do continuar' : 'Marcar como visto';
  }

  // Selo "assistido" dos cards: verde no canto do poster. O estado vem do
  // servidor (watch_progress encerrado) em todas as listagens — A-Z, home,
  // coleções, TAGs e arquivos da ficha.
  function _badgeAssistido(m) {
    return (m && m.watched)
      ? '<div class="movie-card-assistido" title="Já assistido">'
        + '<svg class="icon-svg"><use href="#i-check"></use></svg></div>'
      : '';
  }

  // Tira o filme da fileira "Continuar Assistindo" sem esperar a home recarregar.
  function _removerDoContinueAssistindo(folderPath) {
    const cwSection = document.getElementById('continueWatchingSection');
    if (!cwSection || cwSection.style.display === 'none') return;
    const cards = cwSection.querySelectorAll('.movie-card');
    for (let i = 0; i < cards.length; i++) {
      const onclick = cards[i].getAttribute('onclick') || '';
      if (onclick.indexOf(folderPath) !== -1
          || onclick.indexOf(encodeURIComponent(folderPath)) !== -1) {
        cards[i].remove();
        break;
      }
    }
    if (cwSection.querySelectorAll('.movie-card').length === 0) {
      cwSection.style.display = 'none';
    }
  }

  function toggleAssistido(pillEl) {
    const raiz = pillEl.closest('.pill-acao') || pillEl;
    const track = raiz.querySelector('.switch-track');
    const alvo = track && track.dataset.alvo;
    if (!alvo) return;
    const on = !track.classList.contains('on');
    raiz.style.pointerEvents = 'none';
    fetch('/api/watched', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ path: alvo, on: on }),
    }).then(r => r.json()).then(data => {
      if (data.status === 'ok') {
        _pintarAssistido(raiz, data.watched);
        if (data.watched) {
          const actionsEl = document.querySelector('.movie-info-actions');
          const resumeBtn = actionsEl && actionsEl.querySelector('.btn-resume');
          if (resumeBtn) resumeBtn.remove();
        }
        showToast(data.watched ? '✔ Marcado como assistido' : 'Fora de assistidos', 'success');
        // O selo de assistido aparece em TODAS as listagens (A-Z, home,
        // coleções, TAGs, series) — invalida o cache inteiro na vez seguinte.
        try {
          for (var k in _frontCache) { delete _frontCache[k]; }
        } catch (e) { /* _frontCache indisponivel */ }
        if (data.watched) _removerDoContinueAssistindo(alvo);
      } else {
        showToast('Erro: ' + (data.error || 'falha'), 'error');
      }
    }).catch(() => showToast('Erro ao marcar', 'error'))
      .finally(() => { raiz.style.pointerEvents = ''; });
  }

  function pillTagsHtml(alvo, titulo, tags) {
    const n = (tags || []).length;
    const nota = n === 0 ? 'Sem tags' : (n + (n === 1 ? ' tag' : ' tags'));
    return '<button class="pill-acao pill-acao-btn" '
      + 'onclick="openGeneroFilmeModal(decodeURIComponent(\'' + enc(alvo) + '\'), '
      + 'decodeURIComponent(\'' + enc(titulo) + '\'))" title="Tags do filme">'
      + '<span class="pill-acao-icone"><svg class="icon-svg"><use href="#i-layers"></use></svg></span>'
      + '<span class="switch-texto"><span class="switch-rotulo">Tags</span>'
      + '<span class="switch-nota">' + escHtml(nota) + '</span></span>'
      + '</button>';
  }

  function genreIcon(name) {
    const icons = {
      'terror': '<svg class="icon-svg"><use href="#i-ghost"></use></svg>', 'horror': '<svg class="icon-svg"><use href="#i-ghost"></use></svg>',
      'comedia': '<svg class="icon-svg"><use href="#i-smile"></use></svg>', 'comédia': '<svg class="icon-svg"><use href="#i-smile"></use></svg>',
      'acao': '<svg class="icon-svg"><use href="#i-zap"></use></svg>', 'acção': '<svg class="icon-svg"><use href="#i-zap"></use></svg>', 'ação': '<svg class="icon-svg"><use href="#i-zap"></use></svg>',
      'drama': '<svg class="icon-svg"><use href="#i-frown"></use></svg>',
      'ficcao': '<svg class="icon-svg"><use href="#i-rocket"></use></svg>', 'ficção': '<svg class="icon-svg"><use href="#i-rocket"></use></svg>', 'sci-fi': '<svg class="icon-svg"><use href="#i-rocket"></use></svg>',
      'shows': '<svg class="icon-svg"><use href="#i-music"></use></svg>', 'series': '<svg class="icon-svg"><use href="#i-music"></use></svg>', 'séries': '<svg class="icon-svg"><use href="#i-music"></use></svg>',
      'documentario': '<svg class="icon-svg"><use href="#i-video"></use></svg>', 'documentário': '<svg class="icon-svg"><use href="#i-video"></use></svg>',
      'romance': '<svg class="icon-svg"><use href="#i-heart"></use></svg>',
      'aventura': '<svg class="icon-svg"><use href="#i-map"></use></svg>',
      'animacao': '<svg class="icon-svg"><use href="#i-palette"></use></svg>', 'animação': '<svg class="icon-svg"><use href="#i-palette"></use></svg>',
      'suspense': '<svg class="icon-svg"><use href="#i-eye"></use></svg>',
      'trash': '<svg class="icon-svg"><use href="#i-skull"></use></svg>',
      'acervo': '<svg class="icon-svg"><use href="#i-book"></use></svg>',
    };
    const key = name.toLowerCase().normalize('NFD').replace(/[\u0300-\u036f]/g, '');
    return icons[key] || '<svg class="icon-svg"><use href="#i-film"></use></svg>';
  }

  // ===== GENRE VIEW: show movie folders as cards =====
  function renderGenreView(container, data) {
    const hero = document.getElementById('hero');
    hero.style.display = 'block';

    const parts = data.path.split('/').filter(Boolean);
    const genreName = parts.length > 0 ? parts[parts.length - 1] : 'Género';
    // Pasta de filme e vídeo solto na pasta da tag viram o mesmo cartão na
    // tela, então contam junto: separar os dois era uma distinção interna que
    // não dizia nada a quem lê.
    const total = data.folders.length + (data.videos ? data.videos.length : 0);
    const icon = genreIcon(genreName);
    document.getElementById('heroTitle').innerHTML = icon + ' ' + escHtml(genreName);
    document.getElementById('heroDesc').innerHTML =
      '<svg class="icon-svg"><use href="#i-film"></use></svg> ' + total
      + (total === 1 ? ' filme' : ' filmes');
    hero.style.background = 'linear-gradient(135deg, var(--bg2) 0%, var(--surface) 100%)';
    document.getElementById('heroBg').style.backgroundImage = 'none';

    const movieFolders = data.folders || [];
    const directVideos = data.videos || [];

    if (movieFolders.length === 0 && directVideos.length === 0) {
      container.innerHTML = `
        <div class="empty-state">
          <div class="empty-icon"><svg class="icon-svg"><use href="#i-inbox"></use></svg></div>
          <h3>Nenhum filme em "${escHtml(genreName)}"</h3>
          <p>${isLocalPath(data.path)
              ? 'Adicione pastas de filme nesta pasta do disco e clique em Atualizar.'
              : 'Adicione filmes nesta pasta da nuvem para vê-los aqui.'}</p>
        </div>`;
      return;
    }

    let html = `<div class="genre-section">
      <div class="genre-header" style="cursor:default;border:none;padding-bottom:4px">
        <div class="genre-title"><svg class="icon-svg"><use href="#i-film"></use></svg> Filmes <span class="genre-count">(${movieFolders.length})</span></div>
      </div>
      <div class="movie-grid">`;

    // Show movie folders as cards
    movieFolders.forEach(folder => {
      const name = folder.Name || '';
      const folderPath = (data.path ? data.path + '/' : '') + name;
      html += renderMovieFolderCard(name, folderPath);
    });

    // Also show any direct videos
    directVideos.forEach(video => {
      const name = video.Name || '';
      const filePath = (data.path ? data.path + '/' : '') + name;
      html += renderMovieCardHtml(name, filePath, video.Size, video.poster ? posterUrl(data.path, video.poster) : null, video.watched);
    });

    html += `</div></div>`;
    container.innerHTML = html;

    // Load posters for movie folders
    movieFolders.forEach(folder => {
      const name = folder.Name || '';
      const folderPath = (data.path ? data.path + '/' : '') + name;
      const imgId = 'poster-' + encodeURIComponent(folderPath).replace(/%/g, '_');
      cachedFetch('/api/movie-detail?path=' + encodeURIComponent(folderPath)).then(detail => {
        const imgEl = document.getElementById(imgId);
        if (!imgEl) return;
        if (detail && detail.poster) {
          imgEl.src = posterUrl(folderPath, detail.poster.Name);
          imgEl.style.display = 'block';
          const ph = document.getElementById('ph-' + encodeURIComponent(folderPath).replace(/%/g, '_'));
          if (ph) ph.style.display = 'none';
          imgEl.onerror = () => { imgEl.style.display = 'none'; if (ph) ph.style.display = 'flex'; };
        } else {
          imgEl.style.display = 'none';
          if (imgEl.nextElementSibling) imgEl.nextElementSibling.style.display = 'flex';
        }
      });
    });

    // Load hero background from first movie's fanart or poster - REMOVED, simple header only
  }

  function renderMovieFolderCard(name, folderPath) {
    const encodedPath = encodeURIComponent(folderPath).replace(/%/g, '_');
    const nameClean = name.replace(/[._]/g, ' ');
    const yearMatch = name.match(/(\d{4})/);
    const year = yearMatch ? yearMatch[1] : '';
    const safePath = enc(folderPath);

    return `
      <div class="movie-card" onclick="showMovieInfo(decodeURIComponent('${safePath}'), event)" title="${escHtml(name)}">
        <img class="movie-card-poster" id="poster-${encodedPath}" src="" alt="${escHtml(name)}" style="display:none">
        <div class="movie-card-poster-placeholder" id="ph-${encodedPath}"><svg class="icon-svg"><use href="#i-film"></use></svg></div>
        <div class="movie-card-overlay">
          <div class="movie-card-title">${escHtml(nameClean)}</div>
          <div class="movie-card-subtitle">${year ? year : 'Filme'}</div>
        </div>
      </div>`;
  }

  // ===== VIDEO VIEW: direct video files =====
  function renderVideoView(container, data) {
    let html = `<div class="movie-grid">`;
    (data.videos || []).forEach(video => {
      const name = video.Name || '';
      const filePath = (data.path ? data.path + '/' : '') + name;
      const posterSrc = video.poster ? posterUrl(data.path, video.poster) : null;
      html += renderMovieCardHtml(name, filePath, video.Size, posterSrc, video.watched);
    });
    html += `</div>`;
    container.innerHTML = html;
  }

  // ===== GENERIC / FALLBACK =====
  function renderGenericView(container, data) {
    let html = '';

    if (data.folders && data.folders.length > 0) {
      html += `<div class="genre-section">
        <div class="genre-header" style="cursor:default;border:none">
          <div class="genre-title"><svg class="icon-svg"><use href="#i-folder"></use></svg> Pastas <span class="genre-count">(${data.folders.length})</span></div>
        </div>
        <div class="movie-grid">`;
      data.folders.forEach(folder => {
        const name = folder.Name || '';
        const folderPath = (data.path ? data.path + '/' : '') + name;
        const safePath = enc(folderPath);
    html += `
          <div class="movie-card" onclick="loadPath(decodeURIComponent('${safePath}'))" title="${escHtml(name)}">
            <div class="movie-card-poster-placeholder"><svg class="icon-svg"><use href="#i-folder"></use></svg></div>
            <div class="movie-card-overlay">
              <div class="movie-card-title">${escHtml(name)}</div>
            </div>
          </div>`;
      });
      html += `</div></div>`;
    }

    if (data.videos && data.videos.length > 0) {
      html += `<div class="genre-section">
        <div class="genre-header" style="cursor:default;border:none">
          <div class="genre-title"><svg class="icon-svg"><use href="#i-film"></use></svg> Vídeos <span class="genre-count">(${data.videos.length})</span></div>
        </div>
        <div class="movie-grid">`;
      data.videos.forEach(video => {
        const name = video.Name || '';
        const filePath = (data.path ? data.path + '/' : '') + name;
        const posterSrc = video.poster ? posterUrl(data.path, video.poster) : null;
        html += renderMovieCardHtml(name, filePath, video.Size, posterSrc, video.watched);
      });
      html += `</div></div>`;
    }

    container.innerHTML = html || `<div class="empty-state"><div class="empty-icon"><svg class="icon-svg"><use href="#i-folder"></use></svg></div><h3>Pasta vazia</h3></div>`;
  }

  // ===== EMPTY STATE =====
  function renderEmptyState(container, path) {
    container.innerHTML = `
      <div class="empty-state">
        <div class="empty-icon"><svg class="icon-svg"><use href="#i-folder"></use></svg></div>
        <h3>Pasta vazia</h3>
        <p>Nenhum conteúdo encontrado aqui.</p>
      </div>`;
  }

  // ===== MOVIE CARD HTML =====
  function renderMovieCardHtml(name, filePath, size, posterSrc, watched) {
    const nameClean = name.replace(/\.[^.]+$/, '').replace(/[._]/g, ' ');
    // Use encodeURIComponent for safe embedding in onclick attributes
    // DecodeURIComponent in the handler reverses this safely
    const safePath = enc(filePath);
    const safeName = enc(name);
    const yearMatch = name.match(/(\d{4})/);
    const year = yearMatch ? yearMatch[1] : '';

    let html = `
      <div class="movie-card" onclick="playMovie(decodeURIComponent('${safePath}'), decodeURIComponent('${safeName}'))" title="${escHtml(name)}">`;

    if (posterSrc) {
      html += `<img class="movie-card-poster" src="${posterSrc}" alt="${escHtml(name)}" loading="lazy" onerror="this.style.display='none';this.nextElementSibling.style.display='flex'">`;
      html += `<div class="movie-card-poster-placeholder" style="display:none">${fileIcon(name)}</div>`;
    } else {
      html += `<div class="movie-card-poster-placeholder">${fileIcon(name)}</div>`;
    }
    html += _badgeAssistido({ watched: watched });

    html += `
        <div class="movie-card-overlay">
          <div class="movie-card-title">${escHtml(nameClean)}</div>
          <div class="movie-card-subtitle">${formatSize(size)}${year ? ' • ' + year : ''}</div>
        </div>
      </div>`;
    return html;
  }

  // ===== MOVIE INFO =====
  let currentMovieFolder = null;
  // Arte e ficha do filme aberto, para a TV mostrar algo alem do titulo pelado.
  let _castArt = { folder: null, poster: null, fanart: null, year: null, studio: null, plot: null };
  // Ficha da última série aberta (capa, sinopse e episódios em ordem) e da
  // última listagem de pasta: é daqui que saem a capa e a fila ao transmitir
  // um episódio (ver _arteEPlaylistDoEpisodio).
  let _serieAtual = null;
  let _pastaAtual = null;

  function showMovieInfo(folderPath, event) {
    if (event) event.stopPropagation();
    currentMovieFolder = folderPath;

    // Push history state for movie detail
    if (folderPath !== (history.state && history.state.path)) {
      history.pushState({ path: folderPath }, '', window.location.pathname + window.location.search);
    }

    const overlay = document.getElementById('movieInfoOverlay');
    const content = document.getElementById('movieInfoContent');
    const bg = document.getElementById('movieInfoBg');

    overlay.classList.add('active');
    document.body.style.overflow = 'hidden';
    content.innerHTML = '<div class="loading" style="min-height:400px"><div class="spinner"></div><span>Carregando informações...</span></div>';
    bg.style.backgroundImage = 'none';

    cachedFetch('/api/movie-detail?path=' + encodeURIComponent(folderPath)).then(detail => {
      if (!detail) {
        content.innerHTML = '<div class="empty-state"><div class="empty-icon"><svg class="icon-svg"><use href="#i-error"></use></svg></div><h3>Erro ao carregar</h3></div>';
        return;
      }

      // Cache VFS só existe pra nuvem: em fonte local a pergunta não se aplica
      // e a requisição seria desperdício.
      if (!isLocalPath(folderPath) && !_cachedSet.has(folderPath)
          && detail.video && detail.video.Name) {
        const filePath = folderPath + '/' + detail.video.Name;
        fetch('/api/check-cached?path=' + encodeURIComponent(filePath)).then(r => r.json()).then(d => {
          if (d.cached) _markCached(folderPath);
        }).catch(() => {});
      }

      const title = detail.title || 'Filme';
      const titleClean = title.replace(/[._]/g, ' ');
      const year = detail.year || '';
      const video = detail.video;
      const poster = detail.poster;
      const fanart = detail.fanart;
      const subtitle = detail.subtitle;
      const nfo = detail.nfo;

      // Guarda o que a TV vai mostrar. E aqui que poster, fanart e a ficha
      // existem — no player so ha o caminho do arquivo de video.
      _castArt = {
        folder: folderPath,
        poster: poster ? folderPath + '/' + poster.Name : null,
        fanart: fanart ? folderPath + '/' + fanart.Name : null,
        year: year || null,
        studio: (nfo && nfo.studios && nfo.studios[0]) || null,
        plot: (nfo && (nfo.tagline || nfo.plot)) || null
      };

      // Background fanart
      if (fanart) {
        bg.style.backgroundImage = cssUrl(posterUrl(folderPath, fanart.Name));
      } else if (poster) {
        bg.style.backgroundImage = cssUrl(posterUrl(folderPath, poster.Name));
      }

      // Poster image
      // Havia placeholder para "sem cartaz", mas nao para "cartaz que falhou
      // ao carregar" — nesse caso sobrava o glifo de imagem quebrada, bem
      // visivel no celular, onde o cartaz fica acima do titulo.
      const semCartaz = '<div class=\'placeholder\'><svg class=\'icon-svg\'><use href=\'#i-film\'></use></svg></div>';
      const posterImg = poster
        ? '<img src="' + posterUrl(folderPath, poster.Name) + '" alt="' + escHtml(titleClean)
          + '" onerror="this.outerHTML=' + JSON.stringify(semCartaz).replace(/"/g, '&quot;') + '">'
        : semCartaz.replace(/'/g, '"');

      const videoPath = video ? (folderPath + '/' + video.Name) : null;

      // ---- NFO RICH CONTENT ----
      let nfoHtml = '';

      // Rating stars
      if (nfo && nfo.rating) {
        const r = parseFloat(nfo.rating);
        const full = Math.floor(r / 2);
        const half = r % 2 >= 1 ? 1 : 0;
        const starFull = '<svg class="icon-svg"><use href="#i-star-filled"></use></svg>';
        const starEmpty = '<svg class="icon-svg"><use href="#i-star-empty"></use></svg>';
        const stars = starFull.repeat(full) + (half ? starFull : '') + starEmpty.repeat(Math.max(0, 5 - full - half));
        nfoHtml += `<div class="movie-rating">
          <span class="stars">${stars}</span>
          <span class="num">${nfo.rating}</span>
          ${nfo.votes ? '<span class="votes">(' + nfo.votes + ' votos)</span>' : ''}
        </div>`;
      }

      // Genres do metadado (drama, ação...): chip com o ícone da categoria.
      if (nfo && nfo.genres && nfo.genres.length > 0) {
        nfoHtml += '<div class="movie-genres">';
        nfo.genres.forEach(g => {
          nfoHtml += '<span class="movie-genre-tag">' + genreIcon(g) + escHtml(g) + '</span>';
        });
        nfoHtml += '</div>';
      }

      // Tagline
      if (nfo && nfo.tagline) {
        nfoHtml += '<div class="movie-tagline">"' + escHtml(nfo.tagline) + '"</div>';
      }

      // Plot
      if (nfo && nfo.plot) {
        nfoHtml += '<div class="movie-plot">' + escHtml(nfo.plot) + '</div>';
      }

      // Metadata row: runtime, mpaa, country, year, premiered
      let metaParts = [];
      if (nfo && nfo.runtime) metaParts.push('<span><span class="label">Duração</span> ' + escHtml(nfo.runtime) + ' min</span>');
      if (nfo && nfo.mpaa) metaParts.push('<span><span class="label">Classificação</span> ' + escHtml(nfo.mpaa) + '</span>');
      if (year) metaParts.push('<span><span class="label">Ano</span> ' + year + '</span>');
      if (nfo && nfo.premiered) metaParts.push('<span><span class="label">Estreia</span> ' + escHtml(nfo.premiered) + '</span>');
      if (nfo && nfo.country && nfo.country.length > 0) metaParts.push('<span><span class="label">País</span> ' + escHtml(nfo.country.join(', ')) + '</span>');
      if (nfo && nfo.source) metaParts.push('<span><span class="label">Fonte</span> ' + escHtml(nfo.source) + '</span>');
      if (metaParts.length > 0) {
        nfoHtml += '<div class="movie-meta-row">' + metaParts.join('') + '</div>';
      }

      // Directors / Writers
      let creditsHtml = '';
      if (nfo && nfo.directors && nfo.directors.length > 0) {
        creditsHtml += '<span><span class="label">Diretor</span> ' + escHtml(nfo.directors.join(', ')) + '</span>';
      }
      if (nfo && nfo.writers && nfo.writers.length > 0) {
        creditsHtml += '<span><span class="label">Roteiro</span> ' + escHtml(nfo.writers.join(', ')) + '</span>';
      }
      if (nfo && nfo.studios && nfo.studios.length > 0) {
        creditsHtml += '<span><span class="label">Estúdio</span> ' + escHtml(nfo.studios.join(', ')) + '</span>';
      }
      if (creditsHtml) {
        nfoHtml += '<div class="movie-meta-row">' + creditsHtml + '</div>';
      }

      // Cast
      if (nfo && nfo.actors && nfo.actors.length > 0) {
        nfoHtml += '<div class="movie-cast"><h4>Elenco</h4><div class="movie-cast-grid">';
        // Show top 12 actors
        nfo.actors.slice(0, 12).forEach(a => {
          nfoHtml += '<div class="cast-item"><span class="name">' + escHtml(a.name) + '</span> <span class="role">' + escHtml(a.role || '') + '</span></div>';
        });
        nfoHtml += '</div></div>';
      }

      // Tags do metadado (NFO) = palavras-chave. Rótulo explícito para não
      // confundir com as Tags do app, que o usuário cria na mão.
      if (nfo && nfo.tags && nfo.tags.length > 0) {
        nfoHtml += '<div class="movie-tags"><span class="movie-tags-rotulo">Palavras-chave</span>';
        nfo.tags.forEach(t => { nfoHtml += '<span class="movie-tag">#' + escHtml(t.replace(/[^a-z0-9]/gi, '')) + '</span>'; });
        nfoHtml += '</div>';
      }

      // ---- BUILD FINAL HTML ----
      let html = `
        <div class="movie-info-poster">
          ${posterImg}
        </div>
        <div class="movie-info-details">
          ${year ? '<div class="badge">' + year + '</div>' : ''}
          <h1>${escHtml(titleClean)}</h1>
          ${nfoHtml}

          <div class="movie-info-meta">
            ${video ? '<div class="meta-item"><svg class="icon-svg"><use href="#i-box"></use></svg> <span class="label">Tamanho</span> ' + formatSize(video.Size) + '</div>' : ''}
            ${video ? '<div class="meta-item"><svg class="icon-svg"><use href="#i-film"></use></svg> <span class="label">Formato</span> ' + (video.Name ? video.Name.split('.').pop().toUpperCase() : '') + '</div>' : ''}
            ${subtitle ? '<div class="meta-item"><svg class="icon-svg"><use href="#i-message"></use></svg> <span class="label">Legenda</span> ' + formatSize(subtitle.Size) + '</div>' : '<div class="meta-item"><svg class="icon-svg"><use href="#i-message"></use></svg> <span class="label">Legenda</span> Não</div>'}
          </div>

          <div class="movie-info-actions">
            ${videoPath ? '<button class="btn-play" onclick="playFromInfo(decodeURIComponent(\'' + enc(videoPath) + '\'), decodeURIComponent(\'' + enc(escHtml(titleClean)) + '\') ' + (subtitle ? ', decodeURIComponent(\'' + enc(folderPath + '/' + subtitle.Name) + '\')' : '') + ')"><svg class="icon-svg"><use href="#i-play"></use></svg> Assistir</button>' : '<button class="btn-play" disabled style="opacity:0.4"><svg class="icon-svg"><use href="#i-play"></use></svg> Indisponível</button>'}
            ${isLocalPath(folderPath)
                ? '<span class="offline-badge"><svg class="icon-svg"><use href="#i-hard-drive"></use></svg> Local</span>'
                : (_isCached(folderPath) ? '<span class="offline-badge"><svg class="icon-svg"><use href="#i-download"></use></svg> Baixado</span>' : '')}
            ${switchAssistidoHtml(folderPath, !!detail.watched)}
            ${(_me && _me.role === 'admin')
                ? pillTagsHtml(folderPath, titleClean, detail.tags)
                : ''}
            ${(_me && _me.role === 'admin')
                ? switchInfantilHtml(folderPath, detail.infantil, 'Perfil infantil')
                : ''}
            ${detail.collection
                ? '<button class="btn-colecao" onclick="closeMovieInfo(); abrirColecao('
                  + detail.collection.id + ')" title="Ver a coleção inteira">'
                  + '<svg class="icon-svg"><use href="#i-layers"></use></svg> '
                  + escHtml(detail.collection.name)
                  + ' <span class="btn-colecao-conta">' + detail.collection.total + '</span></button>'
                : ''}
          </div>
          </div>
        </div>`;

      content.innerHTML = html;

      // Check progress and show resume button
      fetch('/api/progress?path=' + encodeURIComponent(folderPath)).then(r => r.json()).then(prog => {
        // O /api/progress é a fonte da verdade do "assistido": corrige o
        // interruptor caso o movie-detail tenha vindo do cache.
        if (prog && typeof prog.watched === 'boolean') {
          _pintarAssistido(content.querySelector('.movie-info-actions .pill-acao'), prog.watched);
        }
        if (!prog || !prog.position || prog.position <= 0) return;
        const actionsEl = content.querySelector('.movie-info-actions');
        if (!actionsEl) return;
        const pct = (prog.duration > 0) ? Math.round((prog.position / prog.duration) * 100) : 0;
        // Don't show resume if >95% done
        if (pct > 95) return;
        const posStr = formatTime(prog.position, false);
        const resumeBtn = document.createElement('button');
        resumeBtn.className = 'btn-play btn-resume';
        resumeBtn.setAttribute('data-path', videoPath || '');
        resumeBtn.innerHTML = '⏯ Continuar de ' + posStr + ' <span class="resume-pct">(' + pct + '%)</span>';
        resumeBtn.onclick = function() {
          const vPath = this.getAttribute('data-path');
          if (vPath) playFromInfo(vPath, titleClean, subtitle ? (folderPath + '/' + subtitle.Name) : null, prog.position);
        };
        // Insert before the first button
        actionsEl.insertBefore(resumeBtn, actionsEl.firstChild);
      }).catch(function() {});
    });
  }

  function closeMovieInfo() {
    const overlay = document.getElementById('movieInfoOverlay');
    overlay.classList.remove('active');
    document.body.style.overflow = '';
    currentMovieFolder = null;
  }

  // Botão de voltar da ficha do filme: sem ele, no PWA instalado (tela cheia,
  // sem barra do navegador) não havia nenhum jeito visível de sair — só quem
  // sabia do gesto de arrastar da borda ou do Escape (desktop) conseguia.
  // Usa o histórico (showMovieInfo empilha um estado ao abrir) pra voltar pra
  // pasta de onde veio, não só fechar; se não houver histórico pra voltar
  // (ex.: chegou aqui direto por um link), cai pra closeMovieInfo() puro.
  function voltarDoFilme() {
    const overlay = document.getElementById('movieInfoOverlay');
    history.back();
    setTimeout(() => {
      if (overlay.classList.contains('active')) closeMovieInfo();
    }, 300);
  }

  function playFromInfo(videoPath, movieName, subtitlePath, resumePosition) {
    closeMovieInfo();
    playMovie(videoPath, movieName, subtitlePath, resumePosition);
  }

  // Close movie info on Escape
  // Modais do sistema em ordem de precedência pro Escape: o primeiro aberto
  // fecha e nada mais acontece — apertar Escape num modal nunca podia derrubar
  // o player que ficou tocando por trás.
  const _MODAIS_ESCAPE = [
    ['confirmModal', 'closeConfirmModal'],
    ['nuvemWizardModal', 'closeNuvemWizard'],
    ['generoFilmeModal', 'closeGeneroFilmeModal'],
    ['generoNovoModal', 'closeGeneroNovoModal'],
    ['colecaoModal', 'closeColecaoModal'],
    ['backupModal', 'closeBackupModal'],
    ['cacheManagerModal', 'closeCacheManager'],
    ['settingsModal', 'closeSettingsModal'],
    ['sourcesModal', 'closeSourcesModal'],
    ['brandingModal', 'closeBrandingModal'],
    ['rcloneModal', 'closeRcloneModal'],
    ['changelogModal', 'closeChangelogModal'],
  ];

  document.addEventListener('keydown', function(e) {
    if (e.key === 'Escape') {
      if (gavetaAberta()) { closeSidebar(); return; }
      for (const [id, fechar] of _MODAIS_ESCAPE) {
        if (document.getElementById(id).classList.contains('active')) {
          window[fechar]();
          return;
        }
      }
      const infoOverlay = document.getElementById('movieInfoOverlay');
      if (infoOverlay.classList.contains('active')) {
        closeMovieInfo();
      } else {
        closePlayer();
      }
    }
  });

  // Close on backdrop click
  document.getElementById('movieInfoOverlay').addEventListener('click', function(e) {
    if (e.target === this) closeMovieInfo();
  });

  // Close confirm modal on backdrop click
  document.getElementById('confirmModal').addEventListener('click', function(e) {
    if (e.target === this) closeConfirmModal();
  });

  // Save progress on page unload (close tab, navigate away)
  window.addEventListener('beforeunload', function() {
    if (_currentPlayFolder) {
      _saveProgress();
    }
  });

  // ==================== PLAYER ====================
  let currentVideoPath = null;
  let currentSubtitlePath = null;
  let _currentPlayFolder = null;  // folder path for progress tracking
  let _progressSaveTimer = null;

  // Save watch progress to server
  // posExt/durExt vem da TV quando esta transmitindo — o <video> local esta
  // pausado la atras e gravaria a posicao errada em "continuar assistindo".
  function _saveProgress(posExt, durExt) {
    const video = document.getElementById('videoPlayer');
    const temExt = (typeof posExt === 'number' && typeof durExt === 'number' && durExt > 0);
    if (!_currentPlayFolder) return;
    if (!temExt && (!video || !video.duration || video.duration === 0)) return;
    const pos = temExt ? posExt : (video.currentTime || 0);
    if (pos < 5) return;
    const dur = temExt ? durExt : video.duration;
    const pct = (pos / dur) * 100;
    if (pct > 95) {
      _clearProgress(_currentPlayFolder);
      return;
    }
    fetch('/api/progress', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({path: _currentPlayFolder, position: pos, duration: dur}),
      keepalive: true
    }).catch(() => {});
  }

  function _clearProgress(folderPath) {
    fetch('/api/progress', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({path: folderPath, position: 0, duration: 0}),
      keepalive: true
    }).catch(() => {});
  }

  // ═══════════════════════════════════════════════
  //  Google Cast (Chromecast)
  // ═══════════════════════════════════════════════
  let _castSession = null;
  let _castContext = null;
  /** true once the Cast SDK script has been injected into the page */
  let _castSdkInjected = false;
  /** true once __onGCastApiAvailable(true) has fired */
  let _castReady = false;

  /** Detect if we're inside VS Code / Electron shell (no native Cast support) */
  function _isVSCodeWebview() {
    return navigator.userAgent.indexOf('Electron') >= 0
      || navigator.userAgent.indexOf('VS Code') >= 0
      || navigator.userAgent.indexOf('Code/') >= 0;
  }

  function _getBaseUrl() {
    return window.location.origin;
  }

  // Base para a midia que a PROPRIA PAGINA toca — hoje, o AirPlay, que troca o
  // src do <video> daqui.
  //
  // O __HTTP_BASE__ e sempre http de proposito: o Chromecast busca a midia
  // sozinho e nao aceita certificado auto-assinado. Mas numa pagina https um
  // src http e conteudo misto, e o navegador bloqueia — o AirPlay morreria
  // calado. Ali a unica saida e a propria origem. Servindo em http, que e o
  // caso normal na rede de casa, nada muda.
  function _baseMidiaDaPagina() {
    if (window.location.protocol === 'https:') return _getBaseUrl();
    return window.__HTTP_BASE__ || _getBaseUrl();
  }

  function _loadCastSdk() {
    if (_castSdkInjected) return;
    _castSdkInjected = true;
    if (document.getElementById('castSdkScript')) return;
    var script = document.createElement('script');
    script.id = 'castSdkScript';
    script.src = 'https://www.gstatic.com/cv/js/sender/v1/cast_sender.js?loadCastFramework=1';
    script.async = true;
    script.onerror = function() {
      console.warn('[Cast] Failed to load Cast SDK');
      _castReady = false;
      var btn = document.getElementById('castBtn');
      if (btn) btn.style.display = 'none';
    };
    document.head.appendChild(script);
  }

  // Called by Cast SDK when API is ready
  window.__onGCastApiAvailable = function(isAvailable) {
    var btn = document.getElementById('castBtn');
    if (!isAvailable) {
      console.log('[Cast] SDK not available on this browser');
      _castReady = false;
      if (btn) btn.style.display = 'none';
      return;
    }
    console.log('[Cast] SDK available');
    _castReady = true;
    try {
      _castContext = cast.framework.CastContext.getInstance();
      _castContext.setOptions({
        receiverApplicationId: chrome.cast.media.DEFAULT_MEDIA_RECEIVER_APP_ID,
        autoJoinPolicy: chrome.cast.AutoJoinPolicy.ORIGIN_SCOPED
      });

      // Listen for session changes
      _castContext.addEventListener(
        cast.framework.CastContextEventType.SESSION_STATE_CHANGED,
        function(event) {
          _onCastSessionStateChanged(event);
        }
      );

      // Initial session check (user might already be casting from another tab)
      var session = _castContext.getCurrentSession();
      if (session) {
        _castSession = session;
        if (btn) { btn.style.display = ''; btn.innerHTML = '<svg class="icon-svg"><use href="#i-cast"></use></svg>'; btn.classList.add('active'); }
      } else {
        if (btn) btn.style.display = '';
      }
    } catch (e) {
      console.warn('[Cast] Init error:', e);
      _castReady = false;
      if (btn) btn.style.display = 'none';
    }
  };

  function _onCastSessionStateChanged(event) {
    var btn = document.getElementById('castBtn');
    switch (event.sessionState) {
      case cast.framework.SessionState.SESSION_STARTED:
      case cast.framework.SessionState.SESSION_RESUMED:
        _castSession = _castContext.getCurrentSession();
        if (btn) { btn.innerHTML = '<svg class="icon-svg"><use href="#i-cast"></use></svg>'; btn.classList.add('active'); }
        console.log('[Cast] Session started');
        break;
      case cast.framework.SessionState.SESSION_ENDED:
        _castSession = null;
        if (btn) { btn.innerHTML = '<svg class="icon-svg"><use href="#i-tv"></use></svg>'; btn.classList.remove('active'); }
        _showCastingPanel(false);
        console.log('[Cast] Session ended');
        break;
      case cast.framework.SessionState.SESSION_START_FAILED:
        console.warn('[Cast] Session start failed');
        break;
      default:
        console.log('[Cast] Session state:', event.sessionState);
    }
  }

  function _isCasting() {
    return _castSession !== null;
  }

  // ===== CONTROLE REMOTO =====
  // Enquanto transmite, o <video> local fica pausado: os controles precisam
  // falar com a sessao do Chromecast, senao mexem num player que ninguem ve.
  function _castMedia() {
    if (!_isCasting()) return null;
    try {
      var s = cast.framework.CastContext.getInstance().getCurrentSession();
      var m = s ? s.getMediaSession() : null;
      // Sem midia carregada ainda (ou ja terminou) nao ha o que comandar.
      return (m && m.playerState !== chrome.cast.media.PlayerState.IDLE) ? m : null;
    } catch (e) {
      return null;
    }
  }

  function _castDuration() {
    var m = _castMedia();
    return (m && m.media && m.media.duration) ? m.media.duration : 0;
  }

  function _castSeekTo(segundos) {
    var m = _castMedia();
    if (!m) return false;
    var dur = _castDuration();
    var req = new chrome.cast.media.SeekRequest();
    req.currentTime = Math.max(0, dur ? Math.min(dur, segundos) : segundos);
    m.seek(req, function() {}, function(e) { console.warn('[Cast] seek falhou:', e); });
    return true;
  }

  // Enquanto transmite, o tempo vem do receiver — o <video> local esta parado.
  let _castTicker = null;
  let _castUltimoSave = 0;
  // Fila de episódios da transmissão: montada no playMovie (página da série
  // ou da temporada) e consumida quando a TV avisa que o episódio terminou.
  let _castPlaylist = null;          // { itens: [{path,title,sub,arte}], idx }
  let _castProximoArmado = false;    // vira "armado" quando algo esta tocando
  let _castUltimoIdle = null;        // mediaSessionId do ultimo IDLE/finished —
                                     // o ticker reavisa o estado a cada 1s e
                                     // sem isso re-marcava "assistido" em laço.
  let _castAvancando = false;        // trava do carregamento do proximo

  function _startCastTicker() {
    if (_castTicker) clearInterval(_castTicker);
    _castTicker = setInterval(function() {
      var m = _castMedia();
      if (!m) return;
      var pos = m.getEstimatedTime();
      var dur = _castDuration();
      var seek = document.getElementById('seekBar');
      var time = document.getElementById('timeDisplay');
      if (seek && dur) seek.value = (pos / dur) * 100;
      if (time) time.textContent = formatTime(pos) + ' / ' + formatTime(dur);
      var btn = document.getElementById('playBtn');
      var tocando = (m.playerState === chrome.cast.media.PlayerState.PLAYING
                     || m.playerState === chrome.cast.media.PlayerState.BUFFERING);
      var icone = tocando
        ? '<svg class="icon-svg"><use href="#i-pause"></use></svg>'
        : '<svg class="icon-svg"><use href="#i-play"></use></svg>';
      if (btn) btn.innerHTML = icone;
      // O botão do painel de transmissão espelha o mesmo estado.
      var cbtn = document.getElementById('castingPlayBtn');
      if (cbtn) cbtn.innerHTML = icone;
      // Fim do episódio: o receiver avisa IDLE/"finished" — com a fila
      // montada, o próximo entra sozinho (sem isso a TV ficava parada).
      // Marca o fim de propósito: a última passada de 30s acima podia ter
      // ficado em 9x% e o episódio/filme ia embora sem virar "assistido".
      if (tocando) {
        _castProximoArmado = true;
      } else if (m.playerState === chrome.cast.media.PlayerState.IDLE
                 && String(m.idleReason || '').toLowerCase() === 'finished'
                 && _castUltimoIdle !== m.mediaSessionId) {
        _castUltimoIdle = m.mediaSessionId;
        _saveProgress(100, 100);
        if (_castProximoArmado) {
          _castProximoArmado = false;
          _castAvancarFila();
        }
      }
      // "Continuar assistindo" precisa do tempo da TV, nao do player parado.
      if (tocando && dur && (Date.now() - _castUltimoSave) > 30000) {
        _castUltimoSave = Date.now();
        _saveProgress(pos, dur);
      }
    }, 1000);
  }

  function _stopCastTicker() {
    if (_castTicker) { clearInterval(_castTicker); _castTicker = null; }
  }

  // Nome do aparelho para o painel. No Android o SDK às vezes devolve o nome
  // do RECEBEDOR ("media receiver") no lugar do Chromecast — melhor ficar
  // sem nome do que mostrar um aparelho que não existe. Tenta a sessão
  // legada antes de desistir.
  function _nomeDaTV() {
    var generico = /media\s*receiver|cast media player/i;
    var nome = '';
    try { nome = _castSession.getCastDevice().friendlyName || ''; } catch (e) {}
    if (nome && !generico.test(nome)) return nome;
    try {
      var legado = _castSession.getSessionObj ? _castSession.getSessionObj() : null;
      var rec = legado && legado.receiver;
      var alternativo = (rec && (rec.friendlyName || rec.displayName)) || '';
      if (alternativo && !generico.test(alternativo)) return alternativo;
    } catch (e) {}
    return '';
  }

  function _showCastingPanel(mostrar) {
    var painel = document.getElementById('castingPanel');
    if (!painel) return;
    painel.classList.toggle('active', !!mostrar);
    if (!mostrar) { _stopCastTicker(); return; }
    var nome = _nomeDaTV();
    var dev = document.getElementById('castingDevice');
    if (dev) dev.textContent = nome ? ('para ' + nome) : '';
    var tit = document.getElementById('castingTitle');
    var nomeFilme = document.getElementById('playerMovieName');
    if (tit) tit.textContent = nomeFilme ? nomeFilme.textContent : 'Transmitindo';
    var img = document.getElementById('castingPoster');
    if (img) {
      // Poster quebrado deixaria um buraco com o icone de imagem falha.
      img.onerror = function() { this.style.display = 'none'; };
      if (_castArt.poster) {
        img.style.display = '';
        img.src = streamUrl(_castArt.poster);
      } else {
        img.removeAttribute('src');
        img.style.display = 'none';
      }
    }
    // Controle remoto da tela: botões de legenda só aparecem quando o filme
    // tem faixa, e o estado (tamanho e CC) nasce igual ao da barra.
    var temLegenda = !!currentSubtitlePath;
    ['castingSubSep', 'castingSizeBtn', 'castingCcBtn'].forEach(function(id) {
      var el = document.getElementById(id);
      if (el) el.style.display = temLegenda ? '' : 'none';
    });
    var ccBtn = document.getElementById('castingCcBtn');
    if (ccBtn) {
      var midia = _castMedia();
      var ligada = midia ? (midia.activeTrackIds || []).indexOf(1) !== -1
                         : (temLegenda && subtitlesEnabled);
      ccBtn.classList.toggle('active', ligada);
    }
    _syncSubtitleControls();
    _startCastTicker();
  }

  function toggleCast() {
    var btn = document.getElementById('castBtn');

    // VS Code / Electron webview doesn't support Chrome Cast SDK
    if (_isVSCodeWebview()) {
      showToast('⚠️ Chromecast não funciona no VS Code. Abra no Chrome/Edge.', 'error');
      return;
    }

    // First click: inject the Cast SDK script
    if (!_castSdkInjected) {
      _loadCastSdk();
      if (btn) btn.innerHTML = '<svg class="icon-svg"><use href="#i-clock"></use></svg>';
      console.log('[Cast] SDK loading, waiting...');
      // Wait up to 8s for the SDK to become ready
      var waited = 0;
      var MAX_WAIT = 40; // 40 * 200ms = 8s
      var interval = setInterval(function() {
        waited++;
        if (_castReady) {
          clearInterval(interval);
          console.log('[Cast] SDK ready after ~' + (waited * 200) + 'ms');
          _doToggleCast();
        } else if (waited >= MAX_WAIT) {
          clearInterval(interval);
          if (btn) btn.innerHTML = '<svg class="icon-svg"><use href="#i-tv"></use></svg>';
          // Check if the script tag actually exists but callback never fired
          var scriptTag = document.getElementById('castSdkScript');
          var hint = scriptTag ? 'SDK loaded but not available' : 'SDK failed to load';
          console.warn('[Cast] Timeout: ' + hint);
          showToast('❌ Chromecast não disponível neste navegador (' + hint + ')', 'error');
        }
      }, 200);
      return;
    }

    // SDK was already injected — if ready, toggle; else show error
    if (!_castReady) {
      console.warn('[Cast] SDK was loaded but never became ready');
      showToast('❌ Chromecast não suportado neste navegador', 'error');
      return;
    }
    _doToggleCast();
  }

  function _doToggleCast() {
    if (_isCasting()) {
      // Stop casting
      _castSession.endSession(true);
      return;
    }
    // Start casting - Cast SDK shows the device picker
    if (typeof cast === 'undefined' || !cast.framework) {
      console.warn('[Cast] Cast SDK not loaded');
      showToast('❌ SDK do Chromecast não carregado', 'error');
      return;
    }
    console.log('[Cast] requestSession()... contextReady=' + !!_castContext + ' ready=' + _castReady + ' casting=' + _isCasting());
    cast.framework.CastContext.getInstance().requestSession()
      .then(function() {
        // Session started - now load media
        _castSession = cast.framework.CastContext.getInstance().getCurrentSession();
        _sendMediaToCast();
      })
      .catch(function(err) {
        if (err.code === 'cancel' || err.code === chrome.cast.ErrorCode.CANCEL) {
          // User cancelled - do nothing
          return;
        }
        console.warn('[Cast] Session request error:', err);
        var errMsg = err.code || err.message || String(err);
        var hint = '';
        if (errMsg === 'session_error') {
          hint = ' — verifique se o Chromecast está na mesma rede Wi-Fi, se o servidor está em HTTPS (localhost:8443) ou HTTP (localhost:8080), e tente abrir chrome://cast no Chrome para testar a conectividade.';
        } else if (errMsg === 'timeout') {
          hint = ' — Chromecast não respondeu a tempo';
        }
        showToast('❌ ' + errMsg + hint, 'error');
      });
  }

  // Chromecast e AirPlay compartilham o mesmo problema: o aparelho que vai
  // tocar o filme busca a midia sozinho, direto do servidor, sem o cookie de
  // sessao do navegador. As duas rotas pedem aqui uma URL assinada, valida so
  // para o arquivo em questao (e a legenda/imagens, se informadas).
  // Assina uma mídia sem depender do <video> local: o próximo episódio da
  // fila chega aqui só com o caminho na mão.
  async function _fetchMediaTokenDe(mediaPath, subPath, extraImages) {
    if (!mediaPath) return null;
    var baseUrl = window.__HTTP_BASE__ || _getBaseUrl();
    var body = { path: mediaPath, subtitle: subPath || '' };
    if (extraImages && extraImages.length) body.images = extraImages;
    var tokens = null;
    try {
      var res = await fetch('/api/cast-token', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body)
      });
      if (res.ok) tokens = await res.json();
    } catch (e) { console.warn('[Cast] falha ao assinar a URL:', e); }
    if (!tokens || !tokens.t) return null;
    return {
      baseUrl: baseUrl,                    // Chromecast: sempre http
      midiaBase: _baseMidiaDaPagina(),     // AirPlay: acompanha a pagina
      // Reconstruído do zero: o src do <video> pode carregar um token velho
      // de uma tentativa anterior, e "...&t=antigo&t=novo" confundia o
      // servidor (403 na TV, tela presa no carregando).
      streamPath: '/api/stream?path=' + encodeURIComponent(mediaPath),
      tokens: tokens,
    };
  }

  // Assina a mídia que está no <video> (envio manual e AirPlay).
  async function _fetchMediaToken(video, extraImages) {
    if (!video || !video.src) return null;
    var urlObj = new URL(video.src, _getBaseUrl());
    var mediaPath = urlObj.searchParams.get('path') || '';
    return _fetchMediaTokenDe(mediaPath, currentSubtitlePath, extraImages);
  }

  // Poster/fanart que acompanham o pedido de token.
  function _castImagensDe(arte) {
    return [arte && arte.poster, arte && arte.fanart].filter(Boolean);
  }

  // ===== PREPARO PARA TV =====
  // O receptor do Chromecast e o AirPlay nao leem MKV — e o audio AC3/EAC3
  // fica mudo ate no Chrome do computador (sem decodificador Dolby). Em vez
  // de recusar o filme, o servidor gera um MP4 com o video copiado (sem
  // re-encodar) e faixa AAC, e guarda em cache: so a primeira transmissao
  // de cada arquivo espera. Ver mediaserver/prepare.py.
  var _prepareWatch = {};

  async function _postPrepare(mediaPath) {
    try {
      var res = await fetch('/api/prepare', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ path: mediaPath })
      });
      return res.ok ? await res.json() : null;
    } catch (e) {
      console.warn('[TV] falha ao pedir o preparo:', e);
      return null;
    }
  }

  async function _getPrepareStatus(mediaPath) {
    try {
      var res = await fetch('/api/prepare-status?path=' + encodeURIComponent(mediaPath));
      return res.ok ? await res.json() : null;
    } catch (e) {
      return null;
    }
  }

  // Avisa quando a conversao terminar, sem segurar o usuario: o AirPlay
  // exige o gesto do toque para abrir o seletor, e esperar minutos aqui o
  // invalidaria — melhor pedir um novo toque quando tudo estiver pronto.
  function _watchPrepare(mediaPath) {
    if (_prepareWatch[mediaPath]) return;
    _prepareWatch[mediaPath] = true;
    (async function() {
      for (var i = 0; i < 600; i++) {          // teto de ~20 min
        await new Promise(function(r) { setTimeout(r, 2000); });
        var s = await _getPrepareStatus(mediaPath);
        if (!s) continue;
        if (s.state === 'ready') {
          delete _prepareWatch[mediaPath];
          showToast('📺 Vídeo pronto — toque no AirPlay de novo', 'info');
          return;
        }
        if (s.state === 'error') {
          delete _prepareWatch[mediaPath];
          showToast('❌ Falha ao preparar o vídeo: ' + (s.error || 'erro'), 'error');
          return;
        }
      }
      delete _prepareWatch[mediaPath];
    })();
  }

  // Devolve a rota certa para o receptor: '/api/prepared' quando o servidor
  // converteu, '/api/stream' quando o original já toca, 'preparing' quando a
  // conversão ainda roda, ou null quando deu erro (já avisado ao usuário).
  // wait=false (AirPlay): não espera aqui — avisa depois, via _watchPrepare;
  // wait=true (Cast): acompanha com progresso até ficar pronto.
  async function _routeForCast(mediaPath, wait) {
    if (!mediaPath) return '/api/stream';
    var st = await _postPrepare(mediaPath);
    if (!st || !st.needed) return '/api/stream';
    if (st.state === 'ready') return '/api/prepared';
    if (st.state === 'error') {
      showToast('❌ Não foi possível preparar o vídeo: ' + (st.error || 'erro'), 'error');
      return null;
    }
    if (!wait) {
      _watchPrepare(mediaPath);
      return 'preparing';
    }
    for (var i = 0; i < 2400; i++) {           // re-encodes longos cabem aqui
      await new Promise(function(r) { setTimeout(r, 1500); });
      var s = await _getPrepareStatus(mediaPath);
      if (!s) continue;
      if (s.state === 'ready') {
        showToast('📺 Vídeo pronto — transmitindo…', 'info');
        return '/api/prepared';
      }
      if (s.state === 'error') {
        showToast('❌ Falha ao preparar o vídeo: ' + (s.error || 'erro'), 'error');
        return null;
      }
      if (s.state === 'idle') {                // servidor reiniciou no meio
        await _postPrepare(mediaPath);
        continue;
      }
      showToast('⏳ Preparando o vídeo para a TV…'
                + (s.percent > 0 ? ' ' + s.percent + '%' : ''), 'info');
    }
    showToast('❌ A preparação demorou demais', 'error');
    return null;
  }

  // ===== AIRPLAY (iOS/Safari) =====
  // O Chromecast nao tem como funcionar em navegador de iPhone: a Apple nao
  // expoe a API que o SDK do Google usa, nem no Safari nem no Chrome-iOS, que
  // roda sobre o mesmo motor da Apple. AirPlay e o caminho nativo da Apple —
  // so aparece quando ha um receptor real na rede (Apple TV, TV com AirPlay 2
  // embutido, ou um Roku, que suporta AirPlay 2 mesmo sem ser da Apple).
  function _airplaySupported(video) {
    return !!(video && typeof video.webkitShowPlaybackTargetPicker === 'function');
  }

  function _setupAirplay(video) {
    var btn = document.getElementById('airplayBtn');
    if (!btn) return;
    if (!_airplaySupported(video)) { btn.style.display = 'none'; return; }
    btn.style.display = '';

    // playMovie chama isto a cada filme; sem a trava os listeners iam
    // empilhando a cada reprodução (e o aviso de conexão repetia junto).
    if (video._msAirplaySetup) return;
    video._msAirplaySetup = true;

    // O evento existe pra afinar a visibilidade quando o Safari sabe que nao
    // ha receptor por perto — mas nem toda versao dispara ele de forma
    // confiavel, entao o botao comeca visivel (o pior caso e abrir o seletor
    // nativo vazio, que o proprio iOS ja trata) e so esconde se o evento
    // afirmar que nao ha nada.
    video.addEventListener('webkitplaybacktargetavailabilitychanged', function(e) {
      btn.style.display = (e.availability === 'not-available') ? 'none' : '';
    });

    // Enquanto transmite via AirPlay, o proprio <video> continua sendo o
    // controle — o WebKit repassa play/pause/seek pro receptor por baixo dos
    // panos, sem precisar de um ticker separado como o Cast usa. Aqui só
    // refletimos o estado no botão e confirmamos a conexão: o seletor nativo
    // fecha calado, e sem o aviso parecia que o toque não tinha feito nada.
    video.addEventListener('webkitcurrentplaybacktargetiswirelesschanged', function() {
      var wireless = video.webkitCurrentPlaybackTargetIsWireless;
      btn.classList.toggle('active', wireless);
      if (wireless) {
        showToast('📡 Transmitindo via AirPlay', 'info');
        _airplayRepararSePreciso(video);
      }
    });
  }

  // Monta a URL assinada que o receptor vai buscar, troca no <video> e
  // devolve a posicao/estado de reproducao quando o novo buffer carregar.
  // Trocar o src reinicia o buffer, entao guardamos e restauramos a posicao.
  function _airplayTrocarSrc(video, info, rota, mediaPath) {
    var pos = video.currentTime;
    var tocando = !video.paused;
    video.addEventListener('loadedmetadata', function retomar() {
      video.removeEventListener('loadedmetadata', retomar);
      video.currentTime = pos;
      if (tocando) video.play().catch(function() {});
    });
    video.src = info.midiaBase + (rota === '/api/prepared'
      ? '/api/prepared?path=' + encodeURIComponent(mediaPath)
      : info.streamPath) + '&t=' + encodeURIComponent(info.tokens.t);
    if (currentSubtitlePath && info.tokens.sub) {
      var track = document.getElementById('subtitleTrack');
      if (track) {
        track.src = info.midiaBase + '/api/subtitle?path=' + encodeURIComponent(currentSubtitlePath)
                  + '&t=' + encodeURIComponent(info.tokens.sub);
      }
    }
  }

  // Se a transmissao foi iniciada pelo seletor NATIVO do iOS (ícone do player
  // da Apple, fora do botão do app), o src ainda é a URL sem token: o receptor
  // busca ela sem o cookie da sessao, leva 401 e fica preso no "carregando"
  // pra sempre. Ao detectar a conexão wireless, reassina e troca o src sem
  // fechar a sessao — o Roku/Apple TV refaz a busca já autorizado.
  async function _airplayRepararSePreciso(video) {
    if (!video || !video.src) return;
    if (/[?&]t=/.test(video.src)) return;                  // nosso botão já assinou
    if (video.src.indexOf('/api/stream') < 0) return;      // só URL do próprio app
    if (video._msAirplayReparando) return;
    video._msAirplayReparando = true;
    try {
      var mediaPath = new URL(video.src, _getBaseUrl()).searchParams.get('path') || '';
      var info = await _fetchMediaToken(video, []);
      if (!info) { showToast('❌ Não foi possível autorizar o AirPlay', 'error'); return; }
      var rota = await _routeForCast(mediaPath, false);
      if (rota === null) return;
      if (rota === 'preparing') { _watchPrepare(mediaPath); return; }
      _airplayTrocarSrc(video, info, rota, mediaPath);
    } catch (e) {
      console.warn('[AirPlay] falha ao reassinar a URL:', e);
    } finally {
      video._msAirplayReparando = false;
    }
  }

  async function toggleAirplay() {
    var video = document.getElementById('videoPlayer');
    if (!_airplaySupported(video)) return;

    // Troca o src pra versao assinada antes de abrir o seletor: se o usuario
    // escolher o Roku, ele vai buscar essa URL sozinho, sem cookie. Trocar o
    // src reinicia o buffer, entao guardamos e restauramos a posicao.
    var info = await _fetchMediaToken(video, []);
    if (!info) {
      // Sem o token assinado o receptor nao consegue buscar a midia (ele nao
      // tem o cookie da sessao) e a TV fica presa no "conectando" pra sempre.
      // Melhor avisar aqui do que mandar o aparelho pra um beco sem saida.
      showToast('❌ Não foi possível autorizar o AirPlay', 'error');
      return;
    }
    // O seletor nativo precisa do gesto do toque ainda "quente": se o
    // arquivo precisa de conversao (MKV/E-AC3) e ela ainda não terminou,
    // não dá pra segurar o usuário aqui — avisa e pede um novo toque quando
    // ficar pronto (o _watchPrepare mostra o aviso).
    var mediaPath = new URL(video.src, _getBaseUrl()).searchParams.get('path') || '';
    var rota = await _routeForCast(mediaPath, false);
    if (rota === null) return;
    if (rota === 'preparing') {
      showToast('⏳ Preparando o vídeo para a TV… aviso quando ficar pronto', 'info');
      return;
    }
    _airplayTrocarSrc(video, info, rota, mediaPath);
    // O seletor nativo do iOS precisa ser chamado enquanto o toque do usuario
    // ainda "conta" como gesto ativo — por isso roda logo em seguida, sem mais
    // nenhuma espera depois do fetch acima.
    video.webkitShowPlaybackTargetPicker();
  }

  // O visual da legenda na TV sai da MESMA escolha da barra (tamanho e cor):
  // o receiver desenha do jeito que o TextTrackStyle pedir, então o usuário
  // regula uma vez no computador e vale também no sofá. Chamado no load da
  // mídia e de novo a cada troca de tamanho/cor com o filme já rolando.
  function _estiloLegendaCast() {
    var estilo = new chrome.cast.media.TextTrackStyle();
    estilo.foregroundColor = subtitleColors[subtitleColorIndex].castColor;
    estilo.fontGenericFamily = chrome.cast.media.TextTrackFontGenericFamily.SANS_SERIF;
    estilo.fontStyle = chrome.cast.media.TextTrackFontStyle.NORMAL;
    estilo.fontScale = subtitleSizes[subtitleSizeIndex].castScale;
    // A caixa vem do backgroundColor, nao da "window": o receiver padrao do
    // Google ignora windowType/windowColor, e apostar neles deixava a legenda
    // sem fundo nenhum na TV — branco puro, ilegivel em cena clara.
    // O preco e perder o canto arredondado: o backgroundColor pinta um
    // retangulo colado no texto. Fundo visivel vale mais que canto bonito.
    estilo.backgroundColor = '#000000D9';   // preto a ~85%
    estilo.windowType = chrome.cast.media.TextTrackWindowType.NONE;
    // Sombra como seguro: se ate o backgroundColor for ignorado, o texto
    // ainda se separa do fundo. Onde a caixa aparece, ela some contra o preto.
    estilo.edgeType = chrome.cast.media.TextTrackEdgeType.DROP_SHADOW;
    estilo.edgeColor = '#000000FF';
    return estilo;
  }

  // Reaplica o estilo na sessão em andamento, sem mexer nas faixas ativas.
  // "Não mexer" é OMITIR o activeTrackIds (a API rejeita null; não fornecido =
  // tracks como estão). O receiver aceita trocar o estilo a qualquer momento —
  // a legenda na TV muda sem recarregar o vídeo.
  function _aplicarEstiloLegendaCast() {
    var m = _castMedia();
    if (!m) return;
    try {
      var faixas = (m.activeTrackIds && m.activeTrackIds.length)
        ? m.activeTrackIds : undefined;
      m.editTracksInfo(
        new chrome.cast.media.EditTracksInfoRequest(faixas, _estiloLegendaCast()),
        function() { console.log('[Cast] estilo da legenda atualizado'); },
        function(e) { console.warn('[Cast] estilo da legenda falhou:', e); });
    } catch (e) {
      console.warn('[Cast] estilo da legenda indisponível:', e);
    }
  }

  async function _sendMediaToCast() {
    if (!_castSession) return;
    var video = document.getElementById('videoPlayer');
    if (!video || !video.src) return;

    var info = await _fetchMediaToken(video, _castImagensDe(_castArt));
    if (!info) {
      showToast('❌ Não foi possível autorizar o envio para a TV', 'error');
      return;
    }
    var mediaPath = new URL(video.src, _getBaseUrl()).searchParams.get('path') || '';
    var titleEl = document.getElementById('playerMovieName');
    var titulo = titleEl ? titleEl.textContent : '12:00 Media Server';
    try {
      var ok = await _castEnviarMidia(info, mediaPath, currentSubtitlePath,
                                      titulo, _castArt, video.currentTime);
      if (!ok) return;
    } catch (err) {
      console.warn('[Cast] Load media error:', err);
      showToast('❌ Erro ao transmitir', 'error');
      return;
    }
    console.log('[Cast] Media loaded on Chromecast');
    showToast('📡 Transmitindo para Chromecast', 'info');
    // Pause local video while casting
    video.pause();
    _showCastingPanel(true);
    _prepararProximoDaFila();
    // Force enable subtitle track after load (some receivers ignore activeTrackIds).
    // Retry a cada 2s até ~30s: o receiver só associa o track depois que o vídeo
    // carregou/bufferizou (stream via rclone→nuvem demora a começar).
    if (currentSubtitlePath) {
      _forceCastSubtitles(1, 0);
    }
  }

  // Envia uma mídia já assinada para a TV. Separado do _sendMediaToCast
  // porque o próximo episódio da fila não passa pelo <video> local: título,
  // arte, legenda e posição vêm do item da fila.
  // Devolve false quando a rota não ficou pronta (conversão falhou etc.).
  async function _castEnviarMidia(info, mediaPath, subPath, titulo, arte, tempo) {
    // MKV/E-AC3/HEVC não toca direto nos receptores: antes de a TV buscar
    // os bytes, o servidor gera o MP4 (H.264 + AAC) e a sessão espera.
    var rota = await _routeForCast(mediaPath, true);
    if (rota !== '/api/stream' && rota !== '/api/prepared') return false;
    var baseUrl = info.baseUrl, castTokens = info.tokens;

    // Construct absolute URL for Chromecast (over HTTP)
    var contentUrl = baseUrl + (rota === '/api/prepared'
      ? '/api/prepared?path=' + encodeURIComponent(mediaPath)
      : info.streamPath) + '&t=' + encodeURIComponent(castTokens.t);

    // Build media info
    var mediaInfo = new chrome.cast.media.MediaInfo(contentUrl, 'video/mp4');
    mediaInfo.streamType = chrome.cast.media.StreamType.BUFFERED;

    // MovieMediaMetadata no lugar do generico: e o que faz a TV desenhar a
    // ficha (arte, ano, estudio) em vez de uma tela vazia com o titulo.
    // Episódio entra com a ficha da série: o arquivo não tem pôster próprio.
    var meta = new chrome.cast.media.MovieMediaMetadata();
    meta.title = titulo || '12:00 Media Server';
    arte = arte || {};
    if (arte.year) meta.releaseDate = String(arte.year) + '-01-01';
    if (arte.studio) meta.studio = arte.studio;
    if (arte.plot) meta.subtitle = arte.plot;
    else if (arte.year) meta.subtitle = String(arte.year);

    // As imagens tambem saem por /api/stream: sem o token assinado a TV recebe
    // 401 e fica sem arte.
    var imgs = castTokens.imgs || {};
    var arteImgs = [];
    [arte.fanart, arte.poster].forEach(function(caminho) {
      if (!caminho || !imgs[caminho]) return;
      arteImgs.push(new chrome.cast.Image(
        baseUrl + '/api/stream?path=' + encodeURIComponent(caminho)
        + '&t=' + encodeURIComponent(imgs[caminho])));
    });
    if (arteImgs.length) meta.images = arteImgs;
    mediaInfo.metadata = meta;

    // A duração do <video> local só vale quando é o MESMO arquivo — no
    // episódio da fila o player de baixo ainda é o anterior.
    var video = document.getElementById('videoPlayer');
    var localPath = '';
    try {
      localPath = new URL(video.src, _getBaseUrl()).searchParams.get('path') || '';
    } catch (e) { /* sem src local, sem duração */ }
    if (video && video.duration && localPath === mediaPath) {
      mediaInfo.duration = video.duration;
    }

    // Add subtitle track if available
    if (subPath) {
      console.log('[Cast] Adding subtitle track:', subPath);
      var subUrl = baseUrl + '/api/subtitle?path=' + encodeURIComponent(subPath)
                 + '&t=' + encodeURIComponent(castTokens.sub || '');
      var track = new chrome.cast.media.Track(1, chrome.cast.media.TrackType.TEXT);
      track.trackContentId = subUrl;
      track.trackContentType = 'text/vtt';
      track.name = 'Português';
      track.language = 'pt';
      track.subtype = chrome.cast.media.TextTrackType.SUBTITLES;
      mediaInfo.tracks = [track];
      // Legenda no espirito da Apple TV: texto sobre caixa escura, sem
      // contorno nas letras (contorno e o visual "Classic"). Tamanho e cor
      // vêm da escolha do usuário na barra — ver _estiloLegendaCast.
      mediaInfo.textTrackStyle = _estiloLegendaCast();
      console.log('[Cast] Subtitle URL:', subUrl);
    }

    var request = new chrome.cast.media.LoadRequest(mediaInfo);
    // activeTrackIds vive no LoadRequest, nao no MediaInfo — estava no lugar
    // errado, e por isso a legenda dependia inteiramente do editTracksInfo
    // depois do load.
    if (subPath) {
      request.activeTrackIds = [1];
    }
    // Start from current position if the video has played
    if (tempo > 0) {
      request.currentTime = tempo;
    }

    await _castSession.loadMedia(request);
    // Arma o "próximo episódio": quando a TV avisar que acabou (IDLE/
    // finished), a fila decide se emenda o seguinte.
    _castProximoArmado = true;
    return true;
  }

  // Emenda o próximo episódio da fila quando o atual termina na TV. A fila
  // nasce do playMovie (página da série ou da temporada) — ver
  // _arteEPlaylistDoEpisodio.
  function _castAvancarFila() {
    if (!_castPlaylist || _castAvancando) return;
    var proximo = _castPlaylist.itens[_castPlaylist.idx + 1];
    if (!proximo) {
      showToast('🏁 Fim dos episódios — não há próximo', 'info');
      return;
    }
    _castAvancando = true;
    _castPlaylist.idx += 1;
    showToast('▶ Próximo episódio: ' + proximo.title, 'info');
    _castCarregarEpisodio(proximo).then(function(ok) {
      if (!ok) showToast('❌ Não foi possível tocar o próximo episódio', 'error');
    }).catch(function(e) {
      console.warn('[Cast] próximo episódio falhou:', e);
      showToast('❌ Não foi possível tocar o próximo episódio', 'error');
    }).then(function() {
      _castAvancando = false;
    });
  }

  // Emenda o próximo episódio quando quem terminou foi o player do aparelho
  // (assistindo no navegador ou pelo AirPlay). No Chromecast este caminho não
  // roda: lá o ticker vê IDLE/"finished" e chama _castAvancarFila.
  // playMovie remonta a ficha e a fila pelo novo arquivo, re-assina o token e
  // troca a chave de progresso para o episódio que começa.
  function _avancarFilaNoPlayer() {
    if (!_castPlaylist || _castAvancando) return;
    var proximo = _castPlaylist.itens[_castPlaylist.idx + 1];
    if (!proximo) return;
    _castAvancando = true;
    showToast('▶ Próximo episódio: ' + proximo.title, 'info');
    playMovie(proximo.path, proximo.title, proximo.sub || '', 0, proximo.path);
    // AirPlay: o src nasce sem token (o <video> local usa o cookie da sessão)
    // e o receptor busca a URL sozinho — sem assinar, ele leva 401 e fica
    // preso no "carregando". É o mesmo remédio do seletor nativo do iOS.
    var video = document.getElementById('videoPlayer');
    if (video && video.webkitCurrentPlaybackTargetIsWireless) {
      _airplayRepararSePreciso(video);
    }
    _castAvancando = false;
  }

  // Vai preparando o próximo episódio da fila em segundo plano: quando ele
  // entrar (fim do atual), a conversão já estará pronta (ou quase) e o
  // usuário não fica olhando a tela final esperando o preparo terminar.
  function _prepararProximoDaFila() {
    if (!_castPlaylist) return;
    var proximo = _castPlaylist.itens[_castPlaylist.idx + 1];
    if (!proximo) return;
    _postPrepare(proximo.path);
  }

  async function _castCarregarEpisodio(item) {
    if (!_castSession) return false;
    var info = await _fetchMediaTokenDe(item.path, item.sub || '', _castImagensDe(item.arte));
    if (!info) return false;
    var ok = await _castEnviarMidia(info, item.path, item.sub || '',
                                    item.title, item.arte, 0);
    if (!ok) return false;
    // O painel (título, capa, legenda) passa a valer para o episódio novo,
    // e o progresso salvo é o dele (chave por arquivo).
    currentVideoPath = item.path;
    currentSubtitlePath = item.sub || null;
    _currentPlayFolder = item.path;
    if (item.arte) _castArt = item.arte;
    var tit = document.getElementById('playerMovieName');
    if (tit) tit.textContent = item.title;
    _showCastingPanel(true);
    if (item.sub) _forceCastSubtitles(1, 0);
    _prepararProximoDaFila();
    return true;
  }

  // Arte da série + fila de episódios quando o vídeo é um episódio da série
  // aberta (o arquivo não tem pôster próprio — a capa é a da série). Sem
  // série reconhecida, tenta a listagem de pasta aberta por último.
  function _arteEPlaylistDoEpisodio(filePath) {
    _castPlaylist = null;
    var eps = _serieAtual && _serieAtual.episodios;
    if (eps && eps.length) {
      var idx = -1;
      for (var i = 0; i < eps.length; i++) {
        if (eps[i].path === filePath) { idx = i; break; }
      }
      if (idx >= 0) {
        var arte = {
          folder: filePath.substring(0, filePath.lastIndexOf('/')),
          poster: _serieAtual.poster,
          fanart: _serieAtual.fanart,
          year: _serieAtual.year,
          studio: null,
          plot: _serieAtual.overview,
        };
        if (!_castArt.poster && !_castArt.fanart) _castArt = arte;
        _castPlaylist = {
          itens: eps.map(function(e) {
            return { path: e.path, title: e.title, sub: e.subtitle || null, arte: arte };
          }),
          idx: idx,
        };
        return;
      }
    }
    _castPlaylist = _playlistDaPastaAberta(filePath);
  }

  // Fila a partir da listagem da pasta (temporada) aberta: ordem da pasta,
  // só quando o nome parece episódio (S01E02...) — filme solto não emenda.
  function _playlistDaPastaAberta(filePath) {
    var pasta = _pastaAtual && _pastaAtual.path;
    if (!pasta || filePath.indexOf(pasta + '/') !== 0) return null;
    var nome = filePath.slice(pasta.length + 1);
    if (nome.indexOf('/') !== -1 || !/S\d{1,2}E\d{1,2}/i.test(nome)) return null;
    var idx = -1;
    var itens = [];
    (_pastaAtual.videos || []).forEach(function(v) {
      var n = v.Name || v.name || '';
      if (!n || !/\.(mp4|mkv|avi|mov|m4v|webm)$/i.test(n)) return;
      if (n === nome) idx = itens.length;
      itens.push({
        path: pasta + '/' + n,
        title: n.replace(/\.[^.]+$/, '').replace(/[._]/g, ' '),
        sub: null,
        arte: _castArt,
      });
    });
    if (idx < 0 || itens.length < 2) return null;
    return { itens: itens, idx: idx };
  }

  function clearBufferTimer() {
    // No-op: _waitForBuffer was removed, but keep for cleanup compatibility
  }

  // Tenta habilitar a legenda no receiver até ~30s (a cada 2s).
  // O receiver do Chromecast só associa o track de texto depois que o vídeo
  // está carregado — com stream via rclone→nuvem isso pode levar vários segundos.
  function _forceCastSubtitles(trackId, attempt) {
    if (attempt > 15) {
      console.warn('[Cast] Subtitles: desistindo após ' + attempt + ' tentativas');
      return;
    }
    try {
      var s = cast.framework.CastContext.getInstance().getCurrentSession();
      if (!s) { console.warn('[Cast] Sem sessão (tentativa ' + attempt + '), tentando de novo...'); setTimeout(function() { _forceCastSubtitles(trackId, attempt + 1); }, 2000); return; }
      var m = s.getMediaSession();
      if (!m) { console.warn('[Cast] Sem media session (tentativa ' + attempt + '), tentando de novo...'); setTimeout(function() { _forceCastSubtitles(trackId, attempt + 1); }, 2000); return; }
      console.log('[Cast] Media session OK (tentativa ' + attempt + '), activeTrackIds:', m.activeTrackIds);
      var trackReq = new chrome.cast.media.EditTracksInfoRequest([trackId]);
      m.editTracksInfo(trackReq, function() {
        console.log('[Cast] Legendas habilitadas via editTracksInfo (tentativa ' + attempt + ')');
      }, function(err) {
        console.warn('[Cast] editTracksInfo falhou (tentativa ' + attempt + '):', err);
        setTimeout(function() { _forceCastSubtitles(trackId, attempt + 1); }, 2000);
      });
    } catch(e) {
      console.warn('[Cast] editTracksInfo erro (tentativa ' + attempt + '):', e);
      setTimeout(function() { _forceCastSubtitles(trackId, attempt + 1); }, 2000);
    }
  }

  // Aplica a legenda no <track> do player local (liga automático se houver)
  function _applySubtitleTrack(subtitlePath) {
    const track = document.getElementById('subtitleTrack');
    const parent = track.parentNode;
    const newTrack = document.createElement('track');
    newTrack.id = 'subtitleTrack';
    newTrack.kind = 'subtitles';
    newTrack.srclang = 'pt-BR';
    newTrack.label = 'Português';
    newTrack.default = true;
    if (subtitlePath) {
      newTrack.src = '/api/subtitle?path=' + encodeURIComponent(subtitlePath);
    }
    parent.replaceChild(newTrack, track);

    // Se houver legenda, já liga automático
    if (subtitlePath) {
      subtitlesEnabled = true;
      const t = document.getElementById('subtitleTrack');
      if (t) t.track.mode = 'showing';
      document.getElementById('subtitleToggleBtn').classList.add('active');
    } else {
      subtitlesEnabled = false;
      document.getElementById('subtitleToggleBtn').classList.remove('active');
    }
    updateSubtitleButton(subtitlePath);
  }

  // ── Ponte para o player nativo da TV ─────────────────────────
  // O app de Android TV injeta window.MediaServerTV. Quando ele existe, quem
  // toca o filme e o ExoPlayer nativo e nao o <video> desta pagina: a WebView
  // do Android nao e confiavel com MKV e faixas AC3/DTS, que e o grosso do
  // acervo, e o ExoPlayer decodifica por hardware.
  //
  // A URL vai assinada pelo mesmo /api/cast-token do Chromecast, entao o player
  // nativo busca os bytes sozinho, sem depender do cookie de sessao da pagina.
  function _tvNativoDisponivel() {
    return !!(window.MediaServerTV && typeof window.MediaServerTV.play === 'function');
  }

  async function _tvTocarNativo(filePath, movieName, subtitlePath, resumePosition) {
    let tokens = null;
    try {
      const res = await fetch('/api/cast-token', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ path: filePath, subtitle: subtitlePath || '' })
      });
      if (res.ok) tokens = await res.json();
    } catch (e) { /* tratado logo abaixo */ }
    if (!tokens || !tokens.t) {
      showToast('Nao foi possivel preparar o video para a TV', 'error');
      return;
    }
    const base = window.location.origin;
    const assinada = (rota, caminho, token) => base + rota
      + '?path=' + encodeURIComponent(caminho) + '&t=' + encodeURIComponent(token);
    window.MediaServerTV.play(JSON.stringify({
      url: assinada('/api/stream', filePath, tokens.t),
      legenda: (subtitlePath && tokens.sub)
        ? assinada('/api/subtitle', subtitlePath, tokens.sub) : '',
      titulo: (movieName || '').replace(/\.[^.]+$/, '').replace(/[._]/g, ' '),
      posicao: Math.round(resumePosition || 0)
    }));
  }

  // Chamado pelo app nativo ao sair do filme. Reusa o mesmo _saveProgress do
  // player da web, que ja sabe ignorar os primeiros segundos e limpar o
  // progresso quando o filme acabou.
  window.tvPlaybackEnded = function (posicao, duracao) {
    _saveProgress(Number(posicao) || 0, Number(duracao) || 0);
  };

  // O que o sistema mostra como "tocando agora" (AirPlay, tela de bloqueio,
  // central de mídia): o título da página é a fonte clássica no WebKit — era
  // ele que fazia a TV anunciar "12:00 Media Server" — e o title do <video> cobre o
  // widget do macOS. A Media Session, quando existe, fala a mesma língua.
  function _publicarNomeNaTela(nome) {
    const video = document.getElementById('videoPlayer');
    document.title = nome || '12:00 Media Server';
    if (video) video.title = nome || '';
    try {
      if (nome && window.MediaMetadata && 'mediaSession' in navigator) {
        navigator.mediaSession.metadata = new MediaMetadata({ title: nome });
      }
    } catch (e) { /* sem Media Session: o título da página já resolve */ }
  }

  function _limparNomeNaTela() {
    const video = document.getElementById('videoPlayer');
    document.title = '12:00 Media Server';
    if (video) video.title = '';
    try {
      if ('mediaSession' in navigator) navigator.mediaSession.metadata = null;
    } catch (e) {}
  }

  function playMovie(filePath, movieName, subtitlePath, resumePosition, progressKey) {
    const overlay = document.getElementById('playerOverlay');
    const video = document.getElementById('videoPlayer');
    const loading = document.getElementById('playerLoading');
    const movieTitle = document.getElementById('playerMovieName');

    currentVideoPath = filePath;
    currentSubtitlePath = subtitlePath || null;
    // Chave do progresso: por padrão a pasta do arquivo (filme em pasta, como
    // sempre). Episódios passam o path do próprio arquivo — cada episódio tem
    // seu progresso, em vez de todos dividirem a linha da temporada.
    _currentPlayFolder = progressKey || filePath.substring(0, filePath.lastIndexOf('/'));

    // Na TV quem toca e o player nativo. Fica depois de _currentPlayFolder de
    // proposito: e dele que _saveProgress depende quando o app devolve a
    // posicao no fim do filme.
    if (_tvNativoDisponivel()) {
      _tvTocarNativo(filePath, movieName, subtitlePath, resumePosition);
      return;
    }

    // Nome do vídeo na tela. No AirPlay quem anuncia é o sistema — pelo título
    // da PÁGINA (e pelo title do <video>) — e o título da página era
    // "12:00 Media Server": a TV mostrava o nome do app no lugar do filme.
    const nomeNaTela = movieName.replace(/\.[^.]+$/, '').replace(/[._]/g, ' ');
    movieTitle.textContent = nomeNaTela;
    _publicarNomeNaTela(nomeNaTela);
    document.getElementById('playerFileSize').textContent = '';

    // Proactively load Cast SDK (non-blocking)
    _loadCastSdk();
    // AirPlay nao precisa de SDK — e nativo do <video> em navegadores WebKit.
    _setupAirplay(video);

    // Limpa qualquer timer de buffer pendente
    clearBufferTimer();

    // Download de fundo só faz sentido pra nuvem: ele existe para forçar o
    // cache VFS do rclone. Num arquivo local isso leria o filme inteiro do
    // disco à toa, disputando com a própria reprodução.
    const _local = isLocalPath(filePath);
    if (!_local) _startBgDownload(filePath);

    // A arte guardada e da ficha aberta. Se o video vier de outro caminho
    // (lista de pasta, busca), ela nao corresponde — melhor nao mandar nada.
    if (_castArt.folder !== filePath.substring(0, filePath.lastIndexOf('/'))) {
      _castArt = { folder: null, poster: null, fanart: null, year: null, studio: null, plot: null };
    }
    // Episódio: capa da série (o arquivo não tem pôster) e fila com os
    // episódios vizinhos para a transmissão emendar sozinha.
    _arteEPlaylistDoEpisodio(filePath);

    // Show loading state
    video.style.display = 'none';
    loading.style.display = 'flex';
    document.getElementById('playerError').style.display = 'none';
    loading.querySelector('span').textContent = _local
      ? 'Abrindo o vídeo...'
      : 'Preparando vídeo da nuvem...';

    overlay.classList.add('active');
    document.body.style.overflow = 'hidden';
    applySubtitleSize();

    // Set up video events
    video.onerror = function() {
      clearBufferTimer();
      const err = video.error;
      // MEDIA_ERR_ABORTED é normal durante seeks — ignora
      if (err && err.code === MediaError.MEDIA_ERR_ABORTED) return;

      // Tenta recarregar até 2x em erro de rede/suporte (rclone pode estar lento)
      if (!video._retryCount) video._retryCount = 0;
      if (video._retryCount < 2 && err && (err.code === MediaError.MEDIA_ERR_NETWORK || err.code === MediaError.MEDIA_ERR_SRC_NOT_SUPPORTED)) {
        video._retryCount++;
        video.src = streamUrl(filePath);
        video.load();
        video.play().catch(function() {});
        return;
      }

      let msg = 'Erro ao carregar vídeo';
      if (err) {
        if (err.code === MediaError.MEDIA_ERR_NETWORK) msg = 'Falha de rede ao carregar vídeo';
        else if (err.code === MediaError.MEDIA_ERR_DECODE) msg = 'Erro de decodificação — formato não suportado';
        else if (err.code === MediaError.MEDIA_ERR_SRC_NOT_SUPPORTED) msg = 'Formato de vídeo não suportado pelo navegador';
      }
      showPlayerError(msg);
    };

    video.oncanplay = function() {
      // Browser pode decodificar — inicia play (só na primeira vez)
      if (!video._started) {
        video._started = true;
        clearBufferTimer();
        loading.style.display = 'none';
        video.style.display = 'block';
        video.play().catch(function() {});
        // Seek to saved position if resuming
        if (resumePosition && resumePosition > 0 && video.duration) {
          const target = Math.min(resumePosition, video.duration - 1);
          video.currentTime = target;
        }
      }
    };

    // Se já tem dados suficientes (cache local), pula o loading
    if (video.readyState >= 3) {
      video._started = true;
      clearBufferTimer();
      loading.style.display = 'none';
      video.style.display = 'block';
      video.play().catch(function() {});
      // Seek to saved position if resuming
      if (resumePosition && resumePosition > 0 && video.duration) {
        video.currentTime = Math.min(resumePosition, video.duration - 1);
      }
    }

    video.onloadeddata = function() {
      // Fallback: se oncanplay não disparou rápido, esconde loading
      if (!video._started) return;
      loading.style.display = 'none';
      video.style.display = 'block';
    };

    video.onwaiting = function() {
      if (video.style.display === 'block') {
        loading.style.display = 'flex';
        loading.querySelector('span').textContent = 'Bufferizando...';
      }
    };

    video.onplaying = function() {
      loading.style.display = 'none';
      showControls();
    };

    video.onseeking = function() {
      video._seeking = true;
    };

    video.onseeked = function() {
      video._seeking = false;
      loading.style.display = 'none';
      video.style.display = 'block';
    };

    // Background download tracker
    video.onpause = function() {
      if (video._started) _startBgDownload(filePath);
    };
    video.onplay = function() {
      // Don't stop bg download on play — let it continue in background
    };

    video.onprogress = function() {
      updateBufferStatus(video);
    };

    // Set up subtitle track (and enable automatically if present)
    _applySubtitleTrack(subtitlePath);

    // Filme aberto direto (card da busca ou vídeo solto) sem legenda:
    // resolve pelo detalhe do filme e aplica quando chegar — também garante
    // que o Cast envie o track de legenda
    if (!subtitlePath) {
      cachedFetch('/api/movie-detail?path=' + encodeURIComponent(_currentPlayFolder)).then(detail => {
        if (detail && detail.subtitle && !currentSubtitlePath) {
          currentSubtitlePath = _currentPlayFolder + '/' + detail.subtitle.Name;
          _applySubtitleTrack(currentSubtitlePath);
        }
      });
    }

    // Start loading video — play() antecipado acelera pipeline de mídia
    video.src = streamUrl(filePath);
    video.load();
    video.play().catch(function() {});

    // Fetch file size in background
    cachedFetch('/api/info?path=' + encodeURIComponent(filePath)).then(info => {
      if (info && info.Size) {
        document.getElementById('playerFileSize').textContent = formatSize(info.Size);
      }
    });

    // Inicia loading — stream começa assim que oncanplay disparar
    loading.querySelector('span').textContent = 'Carregando...';
    // Arquivo local não passa por cache nenhum — mostrar "Cache: 0%" seria mentira.
    setStreamStatus('cached', _local ? 'Local' : 'Cache: 0%');

    // Timeout: se readyState=0 após 25s, é erro de conexão
    setTimeout(function() {
      if (video.readyState === 0) {
        clearBufferTimer();
        showPlayerError(_local
          ? 'O servidor demorou a responder. A fonte deste filme ainda está conectada?'
          : 'O servidor demorou a responder. Verifique sua conexão com a nuvem.');
      }
    }, 25000);

    // Clique simples = play/pause
    video.onclick = function(e) {
      // Não dispara se for double-click
      if (e.detail === 1) {
        if (video.paused) {
          video.play().catch(function() {});
        } else {
          video.pause();
        }
      }
    };

    // Double-click no video = fullscreen no container
    video.ondblclick = function(e) {
      const container = document.querySelector('.player-container');
      if (document.fullscreenElement) {
        document.exitFullscreen().catch(function() {});
      } else if (container.requestFullscreen) {
        container.requestFullscreen();
      } else if (container.webkitRequestFullscreen) {
        container.webkitRequestFullscreen();
      }
    };

    // Seek bar + time + play button + volume sync + periodic progress save
    video.ontimeupdate = function() {
      const seek = document.getElementById('seekBar');
      const time = document.getElementById('timeDisplay');
      if (seek && video.duration) seek.value = (video.currentTime / video.duration) * 100;
      if (time) time.textContent = formatTime(video.currentTime) + ' / ' + formatTime(video.duration);
      // Auto-save progress every ~30 seconds
      if (_progressSaveTimer) clearTimeout(_progressSaveTimer);
      _progressSaveTimer = setTimeout(_saveProgress, 30000);
    };
    video.onplay = function() {
      document.getElementById('playBtn').innerHTML = '<svg class="icon-svg"><use href="#i-pause"></use></svg>';
      showControls();
    };
    video.onpause = function() {
      document.getElementById('playBtn').innerHTML = '<svg class="icon-svg"><use href="#i-play"></use></svg>';
    };
    video.onvolumechange = updateMuteBtn;
    // Fim do episódio tocando no próprio aparelho — é por aqui que o AirPlay
    // passa (a TV é comandada pelo <video>). No Chromecast quem emenda é o
    // ticker (IDLE/"finished"), e lá o <video> local fica pausado: o handler
    // nem chega a disparar.
    video.onended = function() {
      if (_isCasting()) return;
      // Fecha o episódio que acabou (pct > 95 vira "assistido"), antes de a
      // chave de progresso passar para o próximo.
      _saveProgress(video.duration, video.duration);
      _avancarFilaNoPlayer();
    };

    document.getElementById('seekBar').oninput = function() {
      const dur = _castDuration();
      if (dur) { _castSeekTo((this.value / 100) * dur); return; }
      const v = document.getElementById('videoPlayer');
      if (v && v.duration) v.currentTime = (this.value / 100) * v.duration;
    };
    document.getElementById('volumeSlider').oninput = function() {
      if (_isCasting() && _castSession) {
        try {
          _castSession.setVolume(parseFloat(this.value)).catch(function(e) {
            console.warn('[Cast] setVolume falhou:', e);
          });
          return;
        } catch (e) {
          console.warn('[Cast] volume indisponivel:', e);
        }
      }
      const v = document.getElementById('videoPlayer');
      if (v) { v.volume = parseFloat(this.value); v.muted = false; }
      updateMuteBtn();
    };
    const vs = document.getElementById('volumeSlider');
    if (vs) vs.value = video.volume;
    updateMuteBtn();
  }

  function showPlayerError(msg) {
    const loading = document.getElementById('playerLoading');
    const video = document.getElementById('videoPlayer');
    const errorEl = document.getElementById('playerError');
    loading.style.display = 'none';
    video.style.display = 'none';
    video.src = '';
    errorEl.querySelector('.error-msg').textContent = msg;
    errorEl.style.display = 'flex';
  }

  function retryPlay() {
    if (currentVideoPath) {
      const movieTitle = document.getElementById('playerMovieName');
      const name = movieTitle.textContent;
      playMovie(currentVideoPath, name, currentSubtitlePath);
    }
  }

  function toggleSubtitles() {
    const track = document.getElementById('subtitleTrack');
    const btn = document.getElementById('subtitleToggleBtn');
    const m = _castMedia();
    if (m) {
      // Na TV a faixa e ligada/desligada pelo receiver, nao pelo <track> local.
      const ativa = (m.activeTrackIds || []).indexOf(1) !== -1;
      const novoTrack = ativa ? [] : [1];
      // Ao ligar, o estilo vai junto: sem isto o receiver as vezes volta ao
      // visual padrao do Google, ignorando o que foi mandado no load.
      m.editTracksInfo(
        new chrome.cast.media.EditTracksInfoRequest(novoTrack, _estiloLegendaCast()),
        function() {
          btn.classList.toggle('active', !ativa);
          const cc = document.getElementById('castingCcBtn');
          if (cc) cc.classList.toggle('active', !ativa);
        },
        function(e) { console.warn('[Cast] editTracksInfo falhou:', e); });
      return;
    }
    if (track && track.track) {
      if (track.track.mode === 'showing') {
        track.track.mode = 'disabled';
        btn.classList.remove('active');
      } else {
        track.track.mode = 'showing';
        btn.classList.add('active');
      }
    }
  }

  function updateSubtitleButton(subtitlePath) {
    const btn = document.getElementById('subtitleToggleBtn');
    if (!subtitlePath) {
      subtitlesEnabled = false;
      if (btn) btn.classList.remove('active');
    } else {
      subtitlesEnabled = true;
      if (btn) btn.classList.add('active');
    }
  }

  function closePlayer() {
    // Se estiver em fullscreen, sai primeiro para o modal ficar visível
    if (document.fullscreenElement) {
      document.exitFullscreen().catch(function() {});
      // Mostra modal depois de sair (curto delay pro browser processar)
      setTimeout(function() {
        document.getElementById('confirmModal').classList.add('active');
      }, 200);
    } else {
      document.getElementById('confirmModal').classList.add('active');
    }
    document.getElementById('confirmYesBtn').onclick = function() {
      document.getElementById('confirmModal').classList.remove('active');
      _doClosePlayer();
    };
  }

  function closeConfirmModal() {
    document.getElementById('confirmModal').classList.remove('active');
  }

  function _doClosePlayer() {
    fecharPlayerMore();
    _showCastingPanel(false);
    const video = document.getElementById('videoPlayer');
    // Não fecha durante seek
    if (video && video._seeking) {
      console.log('[closePlayer] ignorado — seeking em andamento');
      return;
    }
    // Save progress before closing
    if (_progressSaveTimer) clearTimeout(_progressSaveTimer);
    _saveProgress();
    clearBufferTimer();
    clearTimeout(_controlsTimer);
    const controls = document.getElementById('playerControls');
    if (controls) controls.classList.remove('force-show');
    const hdr = document.querySelector('.player-container .player-header');
    if (hdr) hdr.classList.remove('force-show');
    const pcontainer = document.querySelector('.player-container');
    if (pcontainer) pcontainer.classList.remove('controls-visible');
    const overlay = document.getElementById('playerOverlay');
    const loading = document.getElementById('playerLoading');
    const errorEl = document.getElementById('playerError');
    video.pause();
    video.src = '';
    video.onerror = null;
    video.oncanplay = null;
    video.onwaiting = null;
    video.onplaying = null;
    video.onseeking = null;
    video.onseeked = null;
    video.onprogress = null;
    video.ontimeupdate = null;
    video.onclick = null;
    video.ondblclick = null;
    video.onplay = null;
    video.onpause = null;
    video.onvolumechange = null;
    video.onloadeddata = null;
    video.onended = null;
    // Stop background download
    _stopBgDownload();
    loading.style.display = 'none';
    errorEl.style.display = 'none';
    overlay.classList.remove('active');
    document.body.style.overflow = '';
    _currentPlayFolder = null;
    _progressSaveTimer = null;
    // O filme saiu do ar: devolve o título da página ao nome do app.
    _limparNomeNaTela();
  }

  let subtitlesEnabled = true;
  let subtitleSizeIndex = 2;
  // Tamanho proporcional à altura do player (fração da altura visível).
  // Ex.: 0.05 = 5% da altura → fullscreen grande, janela pequena.
  // `castScale` leva a MESMA escolha para a TV: vira o fontScale do
  // TextTrackStyle do receiver (1.0 = padrão do Google). O 0.8 de antes —
  // que já saía grande numa TV vista do sofá — virou o "Grande".
  const subtitleSizes = [
    { ratio: 0.035, label: 'Peq', nome: 'Pequena',      castScale: 0.5 },
    { ratio: 0.045, label: 'Méd', nome: 'Média',        castScale: 0.65 },
    { ratio: 0.06,  label: 'Gde', nome: 'Grande',       castScale: 0.8 },
    { ratio: 0.08,  label: 'Ext', nome: 'Extra grande', castScale: 1.05 },
  ];

  // Calcula o px da legenda com base na altura real do player
  function applySubtitleSize() {
    const container = document.querySelector('.player-container');
    const overlay = document.querySelector('.player-overlay');
    if (!container || !overlay) return;
    const h = container.clientHeight;
    if (h <= 0) return;
    const size = subtitleSizes[subtitleSizeIndex];
    const px = Math.max(14, Math.round(h * size.ratio));
    overlay.style.setProperty('--sub-size', px + 'px');
  }

  let subtitleColorIndex = 0;
  const subtitleColors = [
    { color: '#ffd700', label: 'Amar', nome: 'Amarelo', castColor: '#FFD700FF' },
    { color: '#ffffff', label: 'Bran', nome: 'Branco',  castColor: '#FFFFFFFF' },
  ];

  // Escolha lembrada entre sessões: quem regula a legenda uma vez não quer
  // regular de novo a cada filme. O valor entra antes da primeira pintura dos
  // menus (os _renderSubtitleMenu logo abaixo), então a UI já nasce certa.
  try {
    const ss = parseInt(localStorage.getItem('media_server_sub_size'), 10);
    if (ss >= 0 && ss < subtitleSizes.length) subtitleSizeIndex = ss;
    const sc = parseInt(localStorage.getItem('media_server_sub_color'), 10);
    if (sc >= 0 && sc < subtitleColors.length) subtitleColorIndex = sc;
  } catch (e) { /* storage indisponível: segue no padrão */ }

  // Espelha a escolha atual nos botões da barra e no rótulo do painel de
  // transmissão — tudo num lugar só, para nenhum ficar dessincronizado.
  function _syncSubtitleControls() {
    const size = subtitleSizes[subtitleSizeIndex];
    const cor = subtitleColors[subtitleColorIndex];
    const sizeLabel = document.getElementById('subtitleSizeLabel');
    if (sizeLabel) sizeLabel.textContent = size.label;
    const colorLabel = document.getElementById('subtitleColorLabel');
    if (colorLabel) colorLabel.textContent = cor.label;
    const colorIcon = document.getElementById('subtitleColorIcon');
    if (colorIcon) colorIcon.style.background = cor.color;
    const overlay = document.querySelector('.player-overlay');
    if (overlay) overlay.style.setProperty('--sub-color', cor.color);
    const castLabel = document.getElementById('castingSizeLabel');
    if (castLabel) castLabel.textContent = size.label;
  }

  // Menuzinho ancorado no proprio botao (ver .ctrl-sub-menu no CSS), em vez
  // de ciclar o valor a cada clique — com so 2-4 opcoes, escolher direto da
  // lista e mais rapido que adivinhar quantos cliques faltam.
  function _renderSubtitleMenu(menuId, opcoes, indiceAtual, aoEscolher) {
    const menu = document.getElementById(menuId);
    if (!menu) return;
    menu.innerHTML = opcoes.map(function (op, i) {
      const swatch = op.color
        ? '<span class="subtitle-swatch" style="background:' + op.color + '"></span> '
        : '';
      return '<button type="button" class="ctrl-sub-menu-item'
        + (i === indiceAtual ? ' active' : '') + '" onclick="' + aoEscolher + '(' + i + ')">'
        + swatch + op.nome + '</button>';
    }).join('');
  }

  function fecharSubtitleMenus(exceto) {
    ['subtitleSizeMenu', 'subtitleColorMenu'].forEach(function (id) {
      if (id === exceto) return;
      const m = document.getElementById(id);
      if (m) m.classList.remove('aberto');
    });
  }

  function toggleSubtitleSizeMenu(ev) {
    if (ev) ev.stopPropagation();
    fecharSubtitleMenus('subtitleSizeMenu');
    document.getElementById('subtitleSizeMenu').classList.toggle('aberto');
    showControls();
  }

  function selectSubtitleSize(i) {
    subtitleSizeIndex = i;
    try { localStorage.setItem('media_server_sub_size', String(i)); } catch (e) {}
    _syncSubtitleControls();
    applySubtitleSize();
    _renderSubtitleMenu('subtitleSizeMenu', subtitleSizes, subtitleSizeIndex, 'selectSubtitleSize');
    fecharSubtitleMenus();
    // Na transmissão quem desenha a legenda é a TV: a escolha vai junto, ao
    // vivo, via TextTrackStyle (ver _aplicarEstiloLegendaCast).
    if (_isCasting()) {
      _aplicarEstiloLegendaCast();
      showToast('🔠 Legenda na TV: ' + subtitleSizes[i].nome, 'info');
    }
  }

  // Botão "Aa" do painel de transmissão: cicla Peq > Méd > Gde > Ext. O toast
  // é a única confirmação — a TV está do outro lado da sala.
  function cycleSubtitleSize() {
    selectSubtitleSize((subtitleSizeIndex + 1) % subtitleSizes.length);
  }

  function toggleSubtitleColorMenu(ev) {
    if (ev) ev.stopPropagation();
    fecharSubtitleMenus('subtitleColorMenu');
    document.getElementById('subtitleColorMenu').classList.toggle('aberto');
    showControls();
  }

  function selectSubtitleColor(i) {
    subtitleColorIndex = i;
    try { localStorage.setItem('media_server_sub_color', String(i)); } catch (e) {}
    _syncSubtitleControls();
    _renderSubtitleMenu('subtitleColorMenu', subtitleColors, subtitleColorIndex, 'selectSubtitleColor');
    fecharSubtitleMenus();
    // Mesma viagem do tamanho: a cor escolhida troca na TV na hora.
    if (_isCasting()) {
      _aplicarEstiloLegendaCast();
      showToast('🎨 Legenda na TV: ' + subtitleColors[i].nome, 'info');
    }
  }

  _renderSubtitleMenu('subtitleSizeMenu', subtitleSizes, subtitleSizeIndex, 'selectSubtitleSize');
  _renderSubtitleMenu('subtitleColorMenu', subtitleColors, subtitleColorIndex, 'selectSubtitleColor');
  // Nasce com o que ficou salvo (rótulos, amostra de cor e a legenda local).
  _syncSubtitleControls();

  function setStreamStatus(type, text) {
    const el = document.getElementById('streamStatus');
    if (!el) return;
    el.textContent = text;
    el.className = 'stream-status';
    if (type) el.classList.add(type);
  }

  function updateBufferStatus(video) {
    const el = document.getElementById('streamStatus');
    if (!el) return;
    try {
      if (video.buffered && video.buffered.length > 0 && video.duration > 0) {
        const end = video.buffered.end(video.buffered.length - 1);
        const pct = Math.round((end / video.duration) * 100);
        // Update seek buffer bar
        const buf = document.getElementById('seekBuffer');
        if (buf) buf.style.width = Math.min(pct, 100) + '%';
        // Mark as offline-cached once >= 80% buffer
        if (currentMovieFolder && pct >= 85 && !_cachedSet.has(currentMovieFolder)) {
          _verifyServerCache(currentMovieFolder, currentVideoPath);
        }
        // Update cache info in controls
        if (pct >= 100) {
          el.innerHTML = '<svg class="icon-svg"><use href="#i-save"></use></svg> Cache total';
          el.className = 'stream-status cached';
        } else {
          el.textContent = 'Cache: ' + pct + '%';
          el.className = 'stream-status';
        }
      }
    } catch(e) {}
  }

  // ==================== CONTROLES CUSTOMIZADOS ====================

  function formatTime(t) {
    if (!t || !isFinite(t)) return '00:00';
    const h = Math.floor(t / 3600);
    const m = Math.floor((t % 3600) / 60);
    const s = Math.floor(t % 60);
    const pad = n => String(n).padStart(2, '0');
    return (h > 0 ? pad(h) + ':' : '') + pad(m) + ':' + pad(s);
  }

  function togglePlay() {
    const m = _castMedia();
    if (m) {
      const tocando = (m.playerState === chrome.cast.media.PlayerState.PLAYING
                       || m.playerState === chrome.cast.media.PlayerState.BUFFERING);
      const falhou = function(e) { console.warn('[Cast] play/pause falhou:', e); };
      if (tocando) m.pause(null, function() {}, falhou);
      else m.play(null, function() {}, falhou);
      return;   // o ticker atualiza o botao com o estado real do receiver
    }
    const v = document.getElementById('videoPlayer');
    if (!v) return;
    if (v.paused) v.play().catch(function() {});
    else v.pause();
    document.getElementById('playBtn').innerHTML = v.paused ? '<svg class="icon-svg"><use href="#i-play"></use></svg>' : '<svg class="icon-svg"><use href="#i-pause"></use></svg>';
  }

  function skip(sec) {
    const m = _castMedia();
    if (m) { _castSeekTo(m.getEstimatedTime() + sec); return; }
    const v = document.getElementById('videoPlayer');
    if (!v || !v.duration) return;
    v.currentTime = Math.max(0, Math.min(v.duration, v.currentTime + sec));
  }

  let _volumeBeforeMute = 1;
  function toggleMute() {
    if (_isCasting() && _castSession) {
      // Volume da TV, nao do computador. Em try: se a sessao cair entre o
      // clique e a chamada, o erro nao pode travar o controle.
      try {
        const mudo = !_castSession.isMute();
        _castSession.setMute(mudo).catch(function(e) {
          console.warn('[Cast] setMute falhou:', e);
        });
        const btn = document.getElementById('muteBtn');
        if (btn) {
          btn.innerHTML = mudo
            ? '<svg class="icon-svg"><use href="#i-volume-mute"></use></svg>'
            : '<svg class="icon-svg"><use href="#i-volume"></use></svg>';
        }
        return;
      } catch (e) {
        console.warn('[Cast] mudo indisponivel:', e);
      }
    }
    const v = document.getElementById('videoPlayer');
    if (!v) return;
    if (v.volume === 0) {
      v.volume = _volumeBeforeMute;
      v.muted = false;
    } else {
      _volumeBeforeMute = v.volume;
      v.volume = 0;
      v.muted = true;
    }
    updateMuteBtn();
  }

  function updateMuteBtn() {
    const v = document.getElementById('videoPlayer');
    const btn = document.getElementById('muteBtn');
    if (!v || !btn) return;
    if (v.volume === 0 || v.muted) {
      btn.innerHTML = '<svg class="icon-svg"><use href="#i-volume-mute"></use></svg>';
    } else if (v.volume < 0.5) {
      btn.innerHTML = '<svg class="icon-svg"><use href="#i-volume-low"></use></svg>';
    } else {
      btn.innerHTML = '<svg class="icon-svg"><use href="#i-volume"></use></svg>';
    }
  }

  const SPEEDS = [1, 1.5, 2, 0.5];
  let _speedIndex = 0;
  function cycleSpeed() {
    // Na transmissão a linha do tempo é do receptor, e a API de envio do
    // Cast não muda a taxa de reprodução: avisar é melhor que mexer só no
    // player local (que está parado) e nada acontecer na TV.
    if (_castMedia()) {
      showToast('⏩ A velocidade vale só no player local, não na transmissão', 'info');
      return;
    }
    _speedIndex = (_speedIndex + 1) % SPEEDS.length;
    const v = document.getElementById('videoPlayer');
    if (v) v.playbackRate = SPEEDS[_speedIndex];
    const btn = document.getElementById('speedBtn');
    if (btn) btn.textContent = SPEEDS[_speedIndex] + '×';
  }

  function toggleFullscreen() {
    const container = document.querySelector('.player-container');
    if (!container) return;
    if (document.fullscreenElement) {
      document.exitFullscreen().catch(function() {});
    } else if (container.requestFullscreen) {
      container.requestFullscreen();
    } else if (container.webkitRequestFullscreen) {
      container.webkitRequestFullscreen();
    }
  }

  // Auto-hide controls
  let _controlsTimer = null;
  // Menu dos controles secundarios (so aparece no celular).
  function togglePlayerMore(ev) {
    if (ev) ev.stopPropagation();
    const m = document.getElementById('playerMore');
    if (m) m.classList.toggle('ativo');
    showControls();
  }

  function fecharPlayerMore() {
    const m = document.getElementById('playerMore');
    if (m) m.classList.remove('ativo');
  }

  // Toque fora fecha o menu — sem isto ele ficaria aberto sobre o filme.
  document.addEventListener('click', function(e) {
    const m = document.getElementById('playerMore');
    if (m && m.classList.contains('ativo')
        && !m.contains(e.target) && !e.target.closest('.ctrl-more')) {
      fecharPlayerMore();
    }
    if (!e.target.closest('.ctrl-sub-wrap')) fecharSubtitleMenus();
  });

  function showControls() {
    const bar = document.getElementById('playerControls');
    const hdr = document.querySelector('.player-container .player-header');
    const container = document.querySelector('.player-container');
    if (!bar) return;
    bar.classList.add('force-show');
    if (hdr) hdr.classList.add('force-show');
    if (container) container.classList.add('controls-visible');
    clearTimeout(_controlsTimer);
    const v = document.getElementById('videoPlayer');
    if (v && !v.paused) {
      _controlsTimer = setTimeout(function() {
        bar.classList.remove('force-show');
        if (hdr) hdr.classList.remove('force-show');
        if (container) container.classList.remove('controls-visible');
        // 5s em vez de 3: no celular o dedo leva mais tempo para achar o botao
        // do que o cursor, e nao ha mousemove para trazer a barra de volta.
      }, 5000);
    }
  }
  // Show on any mouse move over player
  document.addEventListener('mousemove', function() {
    const bar = document.getElementById('playerControls');
    if (bar && bar.closest('.player-overlay.active')) showControls();
  });

  // Em tela de toque nao ha hover nem mousemove: sem isto os controles so
  // apareciam no onplay e sumiam sozinhos, sem jeito de trazer de volta.
  document.addEventListener('touchstart', function(e) {
    const overlay = document.getElementById('playerOverlay');
    if (!overlay || !overlay.classList.contains('active')) return;
    // Toque num controle nao deve reiniciar o ciclo antes da acao acontecer.
    if (e.target.closest('.player-controls, .player-header')) return;
    showControls();
  }, { passive: true });

  document.getElementById('playerOverlay').onclick = function(e) {
    // Apenas o botão fechar e Escape fecham — clique fora não fecha
  };

  document.addEventListener('keydown', function(e) {
    if (e.key === 'Escape') closePlayer();
    const v = document.getElementById('videoPlayer');
    if (!v || !v.closest('.player-overlay.active')) return;
    if (e.key === ' ' || e.key === 'k') { e.preventDefault(); togglePlay(); }
    if (e.key === 'ArrowLeft') { e.preventDefault(); skip(-10); }
    if (e.key === 'ArrowRight') { e.preventDefault(); skip(10); }
    if (e.key === 'ArrowUp') { e.preventDefault(); const s = document.getElementById('volumeSlider'); if (s) { s.value = Math.min(1, parseFloat(s.value) + 0.1); s.oninput(); } }
    if (e.key === 'ArrowDown') { e.preventDefault(); const s = document.getElementById('volumeSlider'); if (s) { s.value = Math.max(0, parseFloat(s.value) - 0.1); s.oninput(); } }
    if (e.key === 'f') { e.preventDefault(); toggleFullscreen(); }
  });

  // Fullscreen: mantém classe .is-fullscreen no container para CSS
  document.addEventListener('fullscreenchange', function() {
    const container = document.querySelector('.player-container');
    if (!container) return;
    container.classList.toggle('is-fullscreen', !!document.fullscreenElement);
    applySubtitleSize();
  });
  document.addEventListener('webkitfullscreenchange', function() {
    const container = document.querySelector('.player-container');
    if (!container) return;
    container.classList.toggle('is-fullscreen', !!document.webkitFullscreenElement);
    applySubtitleSize();
  });
  // Recalcula a legenda se a janela mudar de tamanho (player redimensionado)
  window.addEventListener('resize', function() {
    applySubtitleSize();
  });

  // ==================== AJUSTES (hub) ====================
  // Os painéis de manutenção eram sete botões no rodapé da sidebar, cada um
  // usado uma vez a cada muito tempo. Agora moram atrás de um item só; o que
  // fica visível é o que se usa toda hora (Atualizar e Sair).
  function openSettingsModal() {
    document.getElementById('settingsModal').classList.add('active');
    document.body.style.overflow = 'hidden';
  }

  function closeSettingsModal() {
    document.getElementById('settingsModal').classList.remove('active');
    document.body.style.overflow = '';
  }

  // Sai do hub e abre o painel escolhido — dois modais abertos ao mesmo tempo
  // deixariam o fundo escurecido duas vezes.
  function fromSettings(abrir) {
    closeSettingsModal();
    abrir();
  }

  document.getElementById('settingsModal').addEventListener('click', function (e) {
    if (e.target === this) closeSettingsModal();
  });

  // ==================== INSTALAR NO CELULAR ====================
  // As instrucoes vivem no desktop, para configurar o celular. O endereco
  // .local e as portas vem do servidor (window.__NET__) — e o mesmo nome que
  // o certificado HTTPS cobre, entao nao ha como divergir do que esta no ar.
  let _phoneUrls = {};

  function openPhoneModal() {
    document.getElementById('phoneModal').classList.add('active');
    document.body.style.overflow = 'hidden';
    _renderPhone();
  }

  function closePhoneModal() {
    document.getElementById('phoneModal').classList.remove('active');
    document.body.style.overflow = '';
  }

  document.getElementById('phoneModal').addEventListener('click', function (e) {
    if (e.target === this) closePhoneModal();
  });

  // Copia sem depender da Clipboard API: ela nao existe em http:// pela rede
  // (so localhost e HTTPS contam como contexto seguro). O textarea e o plano B.
  function _copyText(texto, btn) {
    const aviso = () => {
      if (!btn) return;
      const antes = btn.textContent;
      btn.textContent = 'Copiado!';
      setTimeout(() => { btn.textContent = antes; }, 1400);
    };
    if (navigator.clipboard && window.isSecureContext) {
      navigator.clipboard.writeText(texto).then(aviso).catch(() => _copyTextFallback(texto, aviso));
    } else {
      _copyTextFallback(texto, aviso);
    }
  }

  function _copyTextFallback(texto, aviso) {
    const ta = document.createElement('textarea');
    ta.value = texto;
    ta.style.position = 'fixed';
    ta.style.opacity = '0';
    document.body.appendChild(ta);
    ta.select();
    try { document.execCommand('copy'); aviso(); } catch (e) {}
    document.body.removeChild(ta);
  }

  function copyPhone(btn, qual) {
    _copyText(_phoneUrls[qual] || '', btn);
  }

  function _renderPhone() {
    const box = document.getElementById('phoneBox');
    const net = window.__NET__ || {};
    const host = net.host || '';
    const httpsPort = net.httpsPort || 0;
    const httpPort = net.httpPort || 9187;
    const ip = net.ip || '';
    if (!host || !httpsPort) {
      box.innerHTML = '<div class="user-msg err">O HTTPS não subiu nesta sessão — instalar o app no celular depende dele. Confira o log do servidor.</div>';
      return;
    }
    const porta = httpsPort === 443 ? '' : ':' + httpsPort;
    const appUrl = 'https://' + host + porta;
    const ipUrl = ip ? 'https://' + ip + porta : appUrl;
    const caUrl = 'http://' + host + ':' + httpPort + '/ca.crt';
    _phoneUrls = { app: appUrl, ip: ipUrl, ca: caUrl };

    box.innerHTML =
      '<div class="phone-url">'
      + '<code>' + escHtml(appUrl) + '</code>'
      + '<button class="user-btn" onclick="copyPhone(this, \'app\')">Copiar</button>'
      + '</div>'
      + '<div class="src-hint">O celular precisa estar no mesmo Wi-Fi do computador. '
      + 'Use este endereço em vez do IP: o nome .local continua valendo mesmo se o roteador trocar o IP do Mac.</div>'

      + '<div class="user-section-title">iPhone / iPad</div>'
      + '<ol class="phone-steps">'
      + '<li>Instale o certificado do app: abra <a href="' + escHtml(caUrl) + '"><code>' + escHtml(caUrl) + '</code></a> '
      + 'no Safari e permita o download. Depois vá em Ajustes › Geral › VPN e Gerenciamento de Dispositivo, instale o perfil '
      + 'e ative a confiança em Ajustes › Geral › Sobre › Ajustes de Confiança do Certificado.</li>'
      + '<li>Abra <code>' + escHtml(appUrl) + '</code> no Safari — deve abrir sem aviso de certificado.</li>'
      + '<li>Toque em Compartilhar › Adicionar à Tela de Início. O app entra na tela inicial com ícone e nome próprios.</li>'
      + '</ol>'

      + '<div class="user-section-title">Android</div>'
      + '<ol class="phone-steps">'
      + '<li>Instale o certificado do app: abra <a href="' + escHtml(caUrl) + '"><code>' + escHtml(caUrl) + '</code></a> '
      + 'no Chrome. Depois, nas Configurações do Android, busque "certificado" › Instalar certificado › Certificado de CA e escolha o arquivo baixado.</li>'
      + '<li>Abra <code>' + escHtml(appUrl) + '</code> no Chrome.</li>'
      + '<li>Menu ⋮ › Instalar app (ou Adicionar à tela inicial). O Android cria um app de verdade, com ícone próprio.</li>'
      + '</ol>'
      + '<div class="src-hint">Nomes <code>.local</code> só resolvem no Android 12 ou mais novo — em aparelhos mais antigos, use o endereço por IP abaixo.</div>'

      + '<div class="phone-alt">'
      + 'Não conseguiu pelo nome? Use o IP: <code>' + escHtml(ipUrl) + '</code> '
      + '<button class="user-btn" onclick="copyPhone(this, \'ip\')">Copiar</button>'
      + '<div>O arquivo é só a parte pública do certificado HTTPS deste computador (gerado pelo mkcert) — '
      + 'o celular passa a confiar no site, e a chave privada nunca sai daqui.</div>'
      + '</div>';
  }

  // ==================== FONTES ====================
  // Prefixo logico das fontes locais (espelha LOCAL_ROOT no servidor).
  const LOCAL_ROOT = '/Local';

  function isLocalPath(path) {
    const p = '/' + String(path || '').replace(/^\/+/, '');
    return p === LOCAL_ROOT || p.indexOf(LOCAL_ROOT + '/') === 0;
  }

  function openSourcesModal() {
    document.getElementById('sourcesModal').classList.add('active');
    document.body.style.overflow = 'hidden';
    _loadSources();
  }

  function closeSourcesModal() {
    document.getElementById('sourcesModal').classList.remove('active');
    document.body.style.overflow = '';
  }

  document.getElementById('sourcesModal').addEventListener('click', function (e) {
    if (e.target === this) closeSourcesModal();
  });

  function _srcMsg(text, kind) {
    const el = document.getElementById('sourcesMsg');
    if (el) { el.textContent = text; el.className = 'user-msg ' + kind; }
  }

  async function _loadSources() {
    const box = document.getElementById('sourcesBox');
    if (!box) return;
    box.innerHTML = '<div class="loading" style="min-height:100px"><div class="spinner"></div><span>Carregando fontes...</span></div>';
    try {
      const [srcData, detData] = await Promise.all([
        fetch('/api/sources').then(r => r.json()),
        fetch('/api/sources/detect').then(r => r.json()).catch(() => ({ candidates: [] }))
      ]);
      _renderSources(srcData.sources || [], (detData && detData.candidates) || []);
    } catch (e) {
      box.innerHTML = '<div class="user-msg err">Não foi possível carregar as fontes.</div>';
    }
  }

  function _renderSources(sources, candidates) {
    let html = '<div class="user-section-title">No acervo</div>';

    sources.forEach(src => {
      const isCloud = src.kind === 'cloud';
      const offline = src.online === false;
      html += '<div class="user-row src-row">'
        + '<div class="src-main">'
        + '<div class="user-name">' + sourceIcon(src.kind) + ' ' + escHtml(src.name)
        + '<span class="user-tag ' + (isCloud ? 'cloud' : 'local') + '">' + (isCloud ? 'nuvem' : 'local') + '</span>'
        + (offline ? '<span class="user-tag offline">desconectada</span>' : '')
        + '</div>'
        + (src.root ? '<div class="src-path">' + escHtml(src.root) + '</div>' : '')
        + '<div class="src-counts">'
        + src.movies + (src.movies === 1 ? ' filme' : ' filmes') + '</div>'
        + '</div>'
        + '<button class="user-btn" title="Escanear só esta fonte" onclick="scanSource(decodeURIComponent(\'' + enc(src.id) + '\'))">'
        + '<svg class="icon-svg"><use href="#i-refresh"></use></svg></button>'
        + (isCloud ? '' :
            '<button class="user-btn danger" id="srcDel-' + enc(src.id) + '" '
            + 'title="Tirar do acervo (os arquivos no disco não são apagados)" '
            + 'onclick="removeSource(decodeURIComponent(\'' + enc(src.id) + '\'), decodeURIComponent(\'' + enc(src.name) + '\'))">'
            + '<svg class="icon-svg"><use href="#i-trash"></use></svg></button>')
        + '</div>';
    });

    if (candidates.length > 0) {
      html += '<div class="user-section-title">Detectadas neste computador</div>'
        + '<div class="src-hint">As marcadas com <svg class="icon-svg"><use href="#i-check"></use></svg> '
        + 'já têm uma pasta <b>Media Server</b> dentro e entram na hora.</div>'
        + '<div class="src-detected">';
      candidates.forEach(c => {
        const icon = c.kind === 'volume' ? '#i-hard-drive' : '#i-folder';
        // Sem a pasta Media Server dentro, o cadastro seria recusado — melhor
        // deixar isso visivel antes do clique.
        const dica = c.pronto ? c.path : c.path + ' — sem uma pasta Media Server dentro';
        html += '<button class="src-detected-btn' + (c.pronto ? ' pronto' : '') + '" '
          + 'title="' + escHtml(dica) + '" '
          + 'onclick="addSource(decodeURIComponent(\'' + enc(c.name) + '\'), decodeURIComponent(\'' + enc(c.path) + '\'))">'
          + '<svg class="icon-svg"><use href="' + icon + '"></use></svg> ' + escHtml(c.name)
          + (c.pronto
              ? ' <svg class="icon-svg"><use href="#i-check"></use></svg>'
              : ' <svg class="icon-svg"><use href="#i-plus"></use></svg>')
          + '</button>';
      });
      html += '</div>';
    }

    const nomeBiblioteca = (window.__LOGICAL_ROOT__ || '/Media Server').slice(1);
    html += '<div class="user-section-title">Adicionar uma pasta</div>'
      + '<div class="src-hint">A pasta precisa ter uma pasta <b>' + escHtml(nomeBiblioteca) + '</b> dentro '
      + '(ou até dois níveis abaixo), com os filmes nela:<br>'
      + '<code>' + escHtml(nomeBiblioteca) + ' / Filme (ano) / filme.mkv</code> — com o '
      + '<code>.nfo</code> e o <code>poster.jpg</code> junto do vídeo. '
      + 'Arquivo solto também vale, e as tags você cria no app.</div>'
      + '<div class="user-form">'
      + '<input type="text" id="srcName" placeholder="Nome (ex.: HD Externo)" autocomplete="off">'
      + '<input type="text" id="srcPath" placeholder="Caminho (ex.: /Volumes/MeuHD/Filmes)" autocomplete="off">'
      + '<button class="user-btn" onclick="addSourceFromForm()">'
      + '<svg class="icon-svg"><use href="#i-plus"></use></svg> Adicionar</button>'
      + '</div>'
      + '<div id="sourcesMsg"></div>';

    document.getElementById('sourcesBox').innerHTML = html;
    const input = document.getElementById('srcPath');
    if (input) {
      input.addEventListener('keydown', e => { if (e.key === 'Enter') addSourceFromForm(); });
    }
  }

  async function _srcPost(url, body) {
    try {
      const res = await fetch(url, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body)
      });
      const data = await res.json();
      if (data.status !== 'ok') {
        _srcMsg(data.error || 'Falhou.', 'err');
        return null;
      }
      return data;
    } catch (e) {
      _srcMsg('Erro de rede.', 'err');
      return null;
    }
  }

  async function addSource(name, path) {
    const data = await _srcPost('/api/sources/add', { name: name, path: path });
    if (!data) return;
    _invalidateCatalog();
    await _loadSources();
    _srcMsg(data.message || 'Fonte adicionada.', 'ok');
    showToast('💽 ' + name + ' adicionada ao acervo', '');
  }

  function addSourceFromForm() {
    const pathEl = document.getElementById('srcPath');
    const nameEl = document.getElementById('srcName');
    const path = pathEl ? pathEl.value.trim() : '';
    if (!path) { _srcMsg('Informe o caminho da pasta.', 'err'); return; }
    addSource(nameEl && nameEl.value.trim() ? nameEl.value.trim() : path.split('/').pop(), path);
  }

  // Remocao em duas etapas: o primeiro clique so arma o botao. Tirar uma fonte
  // apaga o catalogo dela (os arquivos no disco ficam), entao vale confirmar.
  let _srcPendingRemove = null;
  async function removeSource(id, name) {
    if (_srcPendingRemove !== id) {
      _srcPendingRemove = id;
      const btn = document.getElementById('srcDel-' + id);
      if (btn) btn.innerHTML = 'Confirmar?';
      _srcMsg('Clique de novo para tirar "' + name + '" do acervo. Os arquivos no disco não são apagados.', 'err');
      setTimeout(() => {
        if (_srcPendingRemove === id) { _srcPendingRemove = null; _loadSources(); }
      }, 6000);
      return;
    }
    _srcPendingRemove = null;
    const data = await _srcPost('/api/sources/remove', { id: id });
    if (!data) return;
    _invalidateCatalog();
    await _loadSources();
    _srcMsg('"' + name + '" saiu do acervo. Os arquivos continuam no disco.', 'ok');
  }

  async function scanSource(id) {
    // /api/refresh responde "scanning" | "already_scanning", nao "ok".
    try {
      const res = await fetch('/api/refresh?source=' + encodeURIComponent(id),
                              { method: 'POST' });
      const data = await res.json();
      if (data.status === 'already_scanning') {
        _srcMsg('Já existe um scan em andamento.', 'err');
        return;
      }
      _srcMsg('Escaneando... o catálogo se atualiza sozinho ao terminar.', 'ok');
      _watchScanProgress();
    } catch (e) {
      _srcMsg('Erro de rede.', 'err');
    }
  }

  // O catalogo mudou: derruba o cache do frontend e redesenha home e sidebar.
  function _invalidateCatalog() {
    _frontCache = {};
    _sidebarGenresLoaded = false;
    loadSidebarGenres(true);
    if (isHomePage(currentPath)) loadPath(currentPath || '', true);
  }

  // ==================== CONTAS ====================
  let _me = null;

  async function _loadMe() {
    try {
      const res = await fetch('/api/auth/status');
      const data = await res.json();
      _me = data.user || null;
      if (_me) {
        const chip = document.getElementById('profileSwitchBtn');
        if (chip) {
          chip.style.display = '';
          const img = document.getElementById('profileSwitchAvatar');
          if (img && _me.avatar) img.src = '/static/avatars/' + _me.avatar + '.svg';
          const nome = document.getElementById('profileSwitchName');
          if (nome) nome.textContent = _me.username;
        }
        if (_me.role === 'admin') {
          ['settingsUsers', 'settingsSources', 'settingsBranding', 'settingsBackup'].forEach(id => {
            const el = document.getElementById(id);
            if (el) el.style.display = '';
          });
        }
      }
    } catch (e) {}
  }

  // Perfis: o seletor "Quem está assistindo?" (/perfis) cuida de criar,
  // editar (avatar, perfil infantil, PIN) e remover.
  function openProfilesManager() {
    window.location.href = '/perfis?gerenciar=1';
  }

  async function switchProfile() {
    try {
      await fetch('/api/profiles/leave', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: '{}'
      });
    } catch (e) {}
    window.location.replace('/');
  }

  // ==================== UTILS ====================
  async function doLogout() {
    try {
      await fetch('/api/auth/logout', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ everywhere: false })
      });
    } catch (e) {}
    window.location.replace('/');
  }

  function escHtml(str) {
    const div = document.createElement('div');
    div.textContent = str;
    return div.innerHTML;
  }

  // Encoda para URL E escapa aspas — seguro para embutir em atributos onclick
  // (encodeURIComponent sozinho NÃO escapa ' e " — quebra com nomes como "Toulon's")
  function enc(str) {
    return encodeURIComponent(str).replace(/'/g, '%27').replace(/"/g, '%22');
  }

  // ==================== TOAST ====================
  let toastTimeout = null;
  function showToast(msg, type) {
    const el = document.getElementById('toast');
    el.textContent = msg;
    el.className = 'toast show' + (type ? ' ' + type : '');
    clearTimeout(toastTimeout);
    toastTimeout = setTimeout(() => { el.classList.remove('show'); }, 4000);
  }

  // ==================== OFFLINE CACHE TRACKER ====================
  // Só filmes da nuvem baixados pro cache VFS. Filme em fonte local está no
  // disco por natureza — não foi "baixado", e misturar os dois esvaziava o
  // sentido da seção. O filter limpa o que versões anteriores gravaram.
  const _cachedSet = new Set(
    JSON.parse(localStorage.getItem('media_server_cached') || '[]')
      .filter(p => !isLocalPath(p))
  );
  function _isCached(folderPath) {
    return _cachedSet.has(folderPath);
  }
  function _markCached(folderPath) {
    if (isLocalPath(folderPath)) return;
    if (!_cachedSet.has(folderPath)) {
      _cachedSet.add(folderPath);
      localStorage.setItem('media_server_cached', JSON.stringify([..._cachedSet]));
    }
  }
  // Sync _cachedSet with server's actual cache state (e.g. after server restart)
  async function _syncCachedFromServer() {
    try {
      const res = await fetch('/api/cache-manager');
      const movies = await res.json();
      if (!movies) return;
      let changed = false;
      movies.forEach(m => {
        // O servidor reporta cached=true para filme local (ele está no disco);
        // aqui a pergunta é outra: foi baixado da nuvem?
        if (isLocalPath(m.path)) return;
        if (m.cached && !_cachedSet.has(m.path)) {
          _cachedSet.add(m.path);
          changed = true;
        } else if (!m.cached && _cachedSet.has(m.path)) {
          _cachedSet.delete(m.path);
          changed = true;
        }
      });
      if (changed) {
        localStorage.setItem('media_server_cached', JSON.stringify([..._cachedSet]));
      }
    } catch(_) {}
  }

  function clearCache() {
    localStorage.removeItem('media_server_cached');
    _cachedSet.clear();
    showToast('🧹 Limpando cache do servidor...', '');
    fetch('/api/clear-cache', { method: 'POST' }).then(r => r.json()).then(d => {
      if (d.status === 'ok') {
        showToast('🧹 Cache limpo com sucesso!', 'success');
        document.getElementById('cacheUsageSize').textContent = '0B';
        // O botao agora fica dentro do gerenciador: se ele estiver aberto,
        // a lista precisa refletir que nada esta mais baixado.
        if (document.getElementById('cacheManagerModal').classList.contains('active')) {
          _cmMovies.forEach(m => { if (!isLocalPath(m.path)) m.cached = false; });
          _renderCacheList(_cmMovies);
          _updateCacheStats();
        }
        loadPath(currentPath || '');
      } else {
        showToast('Erro ao limpar cache: ' + (d.error || 'desconhecido'), 'error');
      }
    }).catch(e => {
      showToast('Erro ao limpar cache: ' + e.message, 'error');
    });
  }

  // Background download — keeps fetching chunks even when video is paused
  let _bgDownloadAbort = null;

  function _startBgDownload(filePath) {
    if (!filePath || _bgDownloadAbort) return;

    // Derive folder path from file path (remove filename)
    const folderPath = filePath.substring(0, filePath.lastIndexOf('/'));

    const controller = new AbortController();
    _bgDownloadAbort = controller;

    // Get file size first
    fetch('/api/info?path=' + encodeURIComponent(filePath)).then(r => r.json()).then(info => {
      if (!info || !info.Size) { _bgDownloadAbort = null; return; }
      const fileSize = info.Size;

      // Fetch the whole file in background via sequential range requests
      // This forces rclone VFS to cache it even when video is paused
      let downloaded = 0;
      const CHUNK = 5 * 1024 * 1024; // 5MB chunks

      function fetchNextChunk() {
        if (!_bgDownloadAbort || downloaded >= fileSize) {
          if (downloaded >= fileSize) {
            // Done — verify and mark as cached
            if (folderPath) {
              _markCached(folderPath);
              _verifyServerCache(folderPath, filePath);
            }
          }
          _bgDownloadAbort = null;
          return;
        }

        const end = Math.min(downloaded + CHUNK - 1, fileSize - 1);
        fetch('/api/stream?path=' + encodeURIComponent(filePath), {
          headers: { 'Range': 'bytes=' + downloaded + '-' + end },
          signal: controller.signal
        }).then(r => {
          return r.blob();
        }).then(blob => {
          downloaded += blob.size;
          // Update cache percentage in controls
          const pct = Math.round((downloaded / fileSize) * 100);
          const el = document.getElementById('streamStatus');
          if (el) {
            if (pct >= 100) {
              el.innerHTML = '<svg class="icon-svg"><use href="#i-save"></use></svg> Cache total';
              el.className = 'stream-status cached';
            } else {
              el.innerHTML = '<svg class="icon-svg"><use href="#i-download"></use></svg> ' + pct + '%';
              el.className = 'stream-status';
            }
          }
          fetchNextChunk();
        }).catch(() => {
          _bgDownloadAbort = null;
        });
      }

      fetchNextChunk();
    }).catch(() => { _bgDownloadAbort = null; });
  }

  function _stopBgDownload() {
    if (_bgDownloadAbort) {
      try { _bgDownloadAbort.abort(); } catch(e) {}
      _bgDownloadAbort = null;
    }
  }

  function _verifyServerCache(folderPath, filePath) {
    if (!filePath) return;
    // Get file size first, then request the last byte
    fetch('/api/info?path=' + encodeURIComponent(filePath)).then(r => r.json()).then(info => {
      if (!info || !info.Size) return;
      const lastByte = info.Size - 1;
      fetch('/api/stream?path=' + encodeURIComponent(filePath), {
        headers: { 'Range': 'bytes=' + lastByte + '-' + lastByte }
      }).then(r => {
        // If we got a valid response, the file is fully cached
        if (r.ok || r.status === 206) {
          _markCached(folderPath);
          // Also notify server to mark it
          fetch('/api/check-cached?path=' + encodeURIComponent(filePath)).catch(() => {});
        }
      }).catch(() => {});
    }).catch(() => {});
  }

  async function _checkServerCached() {
    // Confere com o servidor quais filmes estao 100% baixados no VFS.
    // O A-Z já traz filme de pasta e filme solto; para os de pasta o video
    // vem da listagem da propria pasta, para o solto o arquivo e o proprio
    // path do card.
    try {
      const res = await fetch('/api/all-movies');
      const movies = await res.json();
      if (!movies) return;

      for (const m of movies) {
        if (isLocalPath(m.path) || _cachedSet.has(m.path)) continue;
        let filePath = null;
        if (m.is_file) {
          filePath = m.path;
        } else {
          const listRes = await fetch('/api/list?path=' + encodeURIComponent(m.path));
          const listData = await listRes.json();
          const video = listData && (listData.videos || []).find(v =>
            v.Name && /\.(mp4|mkv|avi|mov|wmv|flv|webm|m4v|mpg|mpeg)$/i.test(v.Name));
          if (video) filePath = m.path + '/' + video.Name;
        }
        if (!filePath) continue;
        const checkRes = await fetch('/api/check-cached?path=' + encodeURIComponent(filePath));
        const checkData = await checkRes.json();
        if (checkData.cached) {
          _markCached(m.path);
        }
      }

      if (_cachedSet.size > 0) _renderOfflineGrid();
    } catch(e) {}
  }

  function _renderOfflineGrid() {
    const section = document.getElementById('offlineSection');
    const grid = document.getElementById('offlineGrid');
    if (!section || !grid) return;

    const paths = [..._cachedSet].filter(p => !isLocalPath(p));
    if (paths.length === 0) {
      section.style.display = 'none';
      grid.innerHTML = '';
      return;
    }

    section.style.display = 'block';
    let html = '';
    let loaded = 0;

    paths.forEach((path, idx) => {
      const name = path.split('/').pop().replace(/[._]/g, ' ').replace(/\.[^.]+$/, '');
      const safePath = enc(path);
      html += '<div class="movie-card" onclick="showMovieInfo(decodeURIComponent(\'' + safePath + '\'), event)" title="' + escHtml(name) + '">'
        + '<div class="movie-card-poster-placeholder" style="display:flex"><svg class="icon-svg"><use href="#i-box"></use></svg></div>'
        + '<div class="movie-card-overlay">'
        + '<div class="movie-card-title">' + escHtml(name) + '</div>'
        + '<div class="movie-card-subtitle"><svg class="icon-svg"><use href="#i-download"></use></svg> Offline</div>'
        + '</div></div>';

      // Load poster in background
      cachedFetch('/api/movie-detail?path=' + encodeURIComponent(path)).then(detail => {
        if (!detail || !detail.poster) return;
        const cards = grid.querySelectorAll('.movie-card');
        if (cards[idx]) {
          const img = document.createElement('img');
          img.className = 'movie-card-poster';
          img.src = posterUrl(path, detail.poster.Name);
          img.alt = escHtml(name);
          img.style.cssText = 'width:100%;height:100%;object-fit:cover;position:absolute;inset:0';
          img.onerror = () => img.remove();
          cards[idx].appendChild(img);
        }
      });
    });
    grid.innerHTML = html;
  }

  // ==================== CACHE MANAGER MODAL ====================
  let _cmMovies = [];
  let _cmDownloading = new Set();     // folder_paths being downloaded
  let _cmVideoPaths = {};            // folder_path -> video_path
  let _cmPollTimers = {};            // folder_path -> timer id

  function openCacheManager() {
    document.getElementById('cacheManagerModal').classList.add('active');
    document.body.style.overflow = 'hidden';
    _cmDownloading.clear();
    // Sync cached state from server so modal shows accurate status
    _syncCachedFromServer().then(() => _loadCacheManagerList());
  }

  function closeCacheManager() {
    document.getElementById('cacheManagerModal').classList.remove('active');
    document.body.style.overflow = '';
    // Stop all poll timers
    for (const k in _cmPollTimers) {
      clearInterval(_cmPollTimers[k]);
    }
    _cmPollTimers = {};
  }

  // Close on backdrop click
  document.getElementById('cacheManagerModal').addEventListener('click', function(e) {
    if (e.target === this) closeCacheManager();
  });

  async function _loadCacheManagerList() {
    const list = document.getElementById('cmList');
    list.innerHTML = '<div class="loading" style="min-height:100px"><div class="spinner"></div><span>Carregando filmes...</span></div>';
    try {
      const res = await fetch('/api/cache-manager');
      const movies = await res.json();
      if (!movies || movies.length === 0) {
        list.innerHTML = '<div class="empty-state"><div class="empty-icon"><svg class="icon-svg"><use href="#i-film"></use></svg></div><h3>Nenhum filme encontrado</h3><p>Escaneie suas fontes primeiro.</p></div>';
        return;
      }
      _cmMovies = movies;
      _renderCacheList(movies);
    } catch(e) {
      list.innerHTML = '<div class="empty-state"><div class="empty-icon"><svg class="icon-svg"><use href="#i-error"></use></svg></div><h3>Erro ao carregar</h3></div>';
    }
  }

  function _updateCacheStats() {
    const total = _cmMovies.length;
    const cached = _cmMovies.filter(m => m.cached).length;
    document.getElementById('cmTotalMovies').textContent = total;
    document.getElementById('cmCachedMovies').textContent = cached;
    // Fetch cache usage
    fetch('/api/cache-status').then(r => r.json()).then(s => {
      if (s && s.usage) {
        const t = s.usage.total;
        let h = '';
        if (t < 1024) h = t + 'B';
        else if (t < 1048576) h = (t / 1024).toFixed(1) + 'K';
        else if (t < 1073741824) h = (t / 1048576).toFixed(1) + 'M';
        else h = (t / 1073741824).toFixed(2) + 'G';
        document.getElementById('cmUsageSize').textContent = h;
      }
    }).catch(() => {});
  }

  function _renderCacheList(movies) {
    const list = document.getElementById('cmList');
    const search = document.getElementById('cmSearchInput').value.toLowerCase().trim();
    _updateCacheStats();

    let filtered = movies;
    if (search) {
      filtered = movies.filter(m => {
        const title = (m.title || m.name || '').toLowerCase();
        return title.indexOf(search) !== -1;
      });
    }

    if (filtered.length === 0) {
      list.innerHTML = '<div class="empty-state" style="padding:30px"><div class="empty-icon"><svg class="icon-svg"><use href="#i-search"></use></svg></div><h3>Nenhum filme encontrado</h3></div>';
      return;
    }

    let html = '';
    filtered.forEach((m, idx) => {
      const title = (m.title || m.name || '').replace(/[._]/g, ' ');
      const nameClean = title.replace(/\.[^.]+$/, '');
      const isLocal = isLocalPath(m.path);
      const isCached = m.cached;
      const isDownloading = !isLocal && _cmDownloading.has(m.path);
      const statusClass = isLocal ? 'cached' : (isDownloading ? 'downloading' : (isCached ? 'cached' : 'uncached'));
      let statusLabel = isLocal
        ? '<svg class="icon-svg"><use href="#i-hard-drive"></use></svg> Local'
        : (isDownloading ? '<svg class="icon-svg"><use href="#i-download"></use></svg> 0%' : (isCached ? '<svg class="icon-svg"><use href="#i-download"></use></svg> Offline' : '<svg class="icon-svg"><use href="#i-cloud"></use></svg> Online'));
      // Reuse cached progress from download tracker if available
      if (isDownloading && _cmPcts && _cmPcts[m.path] !== undefined) {
        statusLabel = '<svg class="icon-svg"><use href="#i-download"></use></svg> ' + _cmPcts[m.path] + '%';
      }

      html += '<div class="cache-item" data-path="' + m.path + '">';

      // Poster thumbnail
      if (m.poster) {
        html += '<img class="cache-item-poster" src="' + posterUrl(m.path, m.poster) + '" alt="" onerror="this.outerHTML=\'<div class=cache-item-poster><svg class=\'icon-svg\'><use href=\'#i-film\'></use></svg></div>\'">';
      } else {
        html += '<div class="cache-item-poster"><svg class="icon-svg"><use href="#i-film"></use></svg></div>';
      }

      html += '<div class="cache-item-title" title="' + escHtml(nameClean) + '">' + escHtml(nameClean) + '</div>';
      html += '<span class="cache-item-status ' + statusClass + '" id="cmStatus-' + idx + '">' + statusLabel + '</span>';

      if (isLocal) {
        // Ja esta no disco do usuario: nao ha o que baixar, e apagar aqui
        // significaria mexer no arquivo dele.
        html += '<button class="cache-item-btn" disabled style="opacity:0.4" title="Filme numa fonte local — sempre disponivel"><svg class="icon-svg"><use href="#i-check"></use></svg></button>';
      } else if (isDownloading) {
        html += '<button class="cache-item-btn" disabled style="opacity:0.4"><svg class="icon-svg"><use href="#i-clock"></use></svg></button>';
      } else if (isCached) {
        html += '<button class="cache-item-btn delete" onclick="_cmDeleteCache(\'' + enc(m.path) + '\', ' + idx + ')"><svg class="icon-svg"><use href="#i-trash"></use></svg> Apagar</button>';
      } else {
        html += '<button class="cache-item-btn download" onclick="_cmDownload(\'' + enc(m.path) + '\', ' + idx + ')"><svg class="icon-svg"><use href="#i-download"></use></svg> Baixar</button>';
      }

      html += '</div>';
    });
    list.innerHTML = html;
  }

  let _cmPcts = {};  // folder_path -> percent (shared across renders)

  function filterCacheList() {
    _renderCacheList(_cmMovies);
  }

  async function _cmDownload(encodedPath, idx) {
    const folderPath = decodeURIComponent(encodedPath);
    _cmDownloading.add(folderPath);

    // Update UI immediately
    const statusEl = document.getElementById('cmStatus-' + idx);
    if (statusEl) {
      statusEl.className = 'cache-item-status downloading';
      statusEl.innerHTML = '<svg class="icon-svg"><use href="#i-download"></use></svg> 0%';
    }
    const btn = statusEl ? statusEl.nextElementSibling : null;
    if (btn) {
      btn.outerHTML = '<button class="cache-item-btn" disabled style="opacity:0.4"><svg class="icon-svg"><use href="#i-clock"></use></svg></button>';
    }

    showToast('📥 Baixando ' + (folderPath.split('/').pop() || 'filme') + '...', '');

    try {
      const res = await fetch('/api/cache-download?path=' + encodeURIComponent(folderPath), { method: 'POST' });
      const data = await res.json();
      if (data.status === 'already_cached') {
        _cmDownloading.delete(folderPath);
        const local = _cmMovies.find(m => m.path === folderPath);
        if (local) local.cached = true;
        _renderCacheList(_cmMovies);
        showToast('📥 Filme já estava em cache', 'success');
        return;
      }
      if (data.status !== 'started') {
        _cmDownloading.delete(folderPath);
        _renderCacheList(_cmMovies);
        showToast('Erro: ' + (data.error || 'desconhecido'), 'error');
        return;
      }

      // Store video path for progress polling
      const videoPath = data.path;
      _cmVideoPaths[folderPath] = videoPath;
      showToast('📥 Download iniciado em segundo plano', 'info');

      // Poll progress
      _cmPcts[folderPath] = 0;
      let attempts = 0;
      _cmPollTimers[folderPath] = setInterval(async () => {
        attempts++;
        try {
          const pRes = await fetch('/api/cache-download-progress?path=' + encodeURIComponent(videoPath));
          const prog = await pRes.json();

          if (prog.status === 'done' || prog.percent >= 100) {
            // Complete!
            clearInterval(_cmPollTimers[folderPath]);
            delete _cmPollTimers[folderPath];
            _cmDownloading.delete(folderPath);
            delete _cmPcts[folderPath];
            // Update local data
            const local = _cmMovies.find(m => m.path === folderPath);
            if (local) local.cached = true;
            _markCached(folderPath);
            _renderCacheList(_cmMovies);
            // Refresh offline section on home and cache usage
            _renderOfflineGrid();
            _invalidateCache('/api/cache-status');
            updateCacheUsage();
            showToast('✅ ' + (folderPath.split('/').pop() || 'Filme') + ' está offline!', 'success');
            return;
          }

          if (prog.status === 'error') {
            clearInterval(_cmPollTimers[folderPath]);
            delete _cmPollTimers[folderPath];
            _cmDownloading.delete(folderPath);
            delete _cmPcts[folderPath];
            _renderCacheList(_cmMovies);
            showToast('❌ Erro no download', 'error');
            return;
          }

          // Update progress percentage on tag
          if (prog.percent !== undefined) {
            _cmPcts[folderPath] = prog.percent;
            const stEl = document.getElementById('cmStatus-' + idx);
            if (stEl) {
              stEl.innerHTML = '<svg class="icon-svg"><use href="#i-download"></use></svg> ' + prog.percent + '%';
            }
          }
        } catch(e) {}

        // Timeout after 5 min
        if (attempts > 300) {
          clearInterval(_cmPollTimers[folderPath]);
          delete _cmPollTimers[folderPath];
          _cmDownloading.delete(folderPath);
          delete _cmPcts[folderPath];
          _renderCacheList(_cmMovies);
        }
      }, 1000);
    } catch(e) {
      _cmDownloading.delete(folderPath);
      delete _cmPcts[folderPath];
      _renderCacheList(_cmMovies);
      showToast('Erro ao iniciar download: ' + e.message, 'error');
    }
  }

  async function _cmDeleteCache(encodedPath, idx) {
    const path = decodeURIComponent(encodedPath);
    showToast('🗑 Removendo cache de ' + (path.split('/').pop() || 'filme') + '...', '');
    try {
      const res = await fetch('/api/uncache?path=' + encodeURIComponent(path), { method: 'POST' });
      const data = await res.json();
      if (data.status === 'ok') {
        // Update local data
        const local = _cmMovies.find(m => m.path === path);
        if (local) local.cached = false;
        _renderCacheList(_cmMovies);

        // Also update _cachedSet in localStorage
        _cachedSet.delete(path);
        localStorage.setItem('media_server_cached', JSON.stringify([..._cachedSet]));
        // Re-render offline grid on home if visible
        _renderOfflineGrid();

        showToast('🗑 Cache removido com sucesso!', 'success');
      } else {
        showToast('Erro: ' + (data.error || 'falha ao remover'), 'error');
      }
    } catch(e) {
      showToast('Erro ao remover cache: ' + e.message, 'error');
    }
    updateCacheUsage();
  }

  // ==================== BACKUP MODAL ====================
  function openBackupModal() {
    document.getElementById('backupModal').classList.add('active');
    document.body.style.overflow = 'hidden';
  }
  function closeBackupModal() {
    document.getElementById('backupModal').classList.remove('active');
    document.body.style.overflow = '';
  }
  document.getElementById('backupModal').addEventListener('click', function(e) {
    if (e.target === this) closeBackupModal();
  });

  // ==================== RCLONE MODAL ====================
  function openRcloneModal() {
    document.getElementById('rcloneModal').classList.add('active');
    document.body.style.overflow = 'hidden';
    _loadRcloneStatus();
  }
  function closeRcloneModal() {
    document.getElementById('rcloneModal').classList.remove('active');
    document.body.style.overflow = '';
  }
  document.getElementById('rcloneModal').addEventListener('click', function(e) {
    if (e.target === this) closeRcloneModal();
  });

  // ==================== APARENCIA (marca) ====================
  // Nome de exibicao e cor sao a unica coisa que muda por instalacao — onde
  // os dados moram (cache, banco, nome do servico) nunca depende disto. Ver
  // mediaserver/branding.py.
  function openBrandingModal() {
    document.getElementById('brandingModal').classList.add('active');
    document.body.style.overflow = 'hidden';
    _loadBranding();
  }
  function closeBrandingModal() {
    document.getElementById('brandingModal').classList.remove('active');
    document.body.style.overflow = '';
  }
  document.getElementById('brandingModal').addEventListener('click', function(e) {
    if (e.target === this) closeBrandingModal();
  });

  async function _loadBranding() {
    const box = document.getElementById('brandingBox');
    try {
      const res = await fetch('/api/branding');
      const marca = await res.json();
      box.innerHTML =
        '<div class="user-form" style="flex-direction:column;align-items:stretch">'
        + '<label style="font-size:12px;color:var(--text3)">Cor</label>'
        + '<div style="display:flex;gap:8px;align-items:center">'
        + '<input type="color" id="brandCorPicker" value="' + marca.cor + '" '
        + 'style="width:44px;height:36px;padding:2px;border-radius:var(--radius);'
        + 'border:1px solid rgba(255,255,255,0.14);background:transparent;cursor:pointer">'
        + '<input type="text" id="brandCorTexto" value="' + marca.cor + '" maxlength="7" '
        + 'style="flex:1" placeholder="#f02828">'
        + '</div>'
        + '</div>'
        + '<div class="rclone-help">A cor aparece na tela de login, no menu, no ícone '
        + 'do app instalado no celular e no manifesto.</div>'
        + '<button class="rclone-action-btn primary" style="width:100%;margin-top:12px" '
        + 'onclick="saveBranding()">Salvar</button>'
        + '<div id="brandingMsg" class="user-msg"></div>';

      const picker = document.getElementById('brandCorPicker');
      const texto = document.getElementById('brandCorTexto');
      // Os dois campos de cor ficam sincronizados nos dois sentidos: o seletor
      // visual e o texto hexadecimal, pra quem preferir digitar direto.
      picker.addEventListener('input', () => { texto.value = picker.value; });
      texto.addEventListener('input', () => {
        if (/^#[0-9a-fA-F]{6}$/.test(texto.value)) picker.value = texto.value;
      });
    } catch (e) {
      box.innerHTML = '<div class="user-msg err">Falha ao carregar.</div>';
    }
  }

  async function saveBranding() {
    const cor = (document.getElementById('brandCorTexto').value || '').trim();
    const msg = document.getElementById('brandingMsg');
    const mostrar = (texto, tipo) => { msg.textContent = texto; msg.className = 'user-msg ' + tipo; };
    if (!/^#[0-9a-fA-F]{6}$/.test(cor)) { mostrar('Cor precisa ser hexadecimal, ex: #f02828.', 'err'); return; }
    try {
      const res = await fetch('/api/branding/set', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ cor })
      });
      const data = await res.json().catch(() => ({}));
      if (res.ok && data.status === 'ok') {
        mostrar('Salvo! Atualizando...', 'ok');
        // Recarrega em vez de repintar na hora: a cor nova tem que sair do
        // proprio HTML que o servidor gera (branding.css, icones, login),
        // e nao so do CSS injetado aqui — mais simples e mais confiavel do
        // que sincronizar cada um desses pontos manualmente.
        setTimeout(() => location.reload(), 600);
      } else {
        mostrar(data.error || 'Não foi possível salvar.', 'err');
      }
    } catch (e) {
      mostrar('Falha de conexão com o servidor.', 'err');
    }
  }

  // ==================== CHANGELOG MODAL ====================
  // Só a última entrada é exibida no modal (versões anteriores ficam no README)
  const _CHANGELOG = [
    {
      version: '1.24.0',
      title: 'Renomeia para 12:00 Media Server e visual retrô discreto',
      changes: [
        'Novo nome: 12:00 Media Server',
        'Fonte Jost, cantos menores e calço nos cards',
        'Sem breadcrumb; Sair abaixo do videocassete',
        'Remove compatibilidade com instalações do nome antigo',
      ],
    },
    {
      version: '1.23.0',
      title: 'ficha do filme: \'já assisti\' que desmarca, Gêneros viram Tags e o AirPlay emendando episódios',
      changes: [
        'Botão \'Já assisti\' na ficha vira interruptor: marca e desmarca, e o filme sai na hora de Continuar Assistindo',
        '\'Gêneros\' viram \'Tags\' em todo o app (barra lateral, A-Z, modais e mensagens) — a ficha do filme mostra quantas tags ele tem',
        'Chips de gênero da ficha ganham ícone, e as tags do metadado aparecem rotuladas como \'Palavras-chave\'',
        'Assistidos aparecem nos cards: selo verde no A-Z, home, coleções, TAGs e arquivos da ficha — e na linha do episódio, com clique para retirar a marcação',
        'Fim no Chromecast agora marca o episódio/filme como assistido (antes ficava em \'continuar\' para sempre)',
        'Fim do episódio emenda o próximo também fora do Chromecast: no AirPlay e assistindo no navegador a reprodução não para mais na tela final',
        'AirPlay: a TV anuncia o nome do filme/episódio (antes mostrava o nome do app) — vale também para a tela de bloqueio e a central de mídia',
        'AirPlay: a legenda do filme entra no MP4 preparado (mov_text, o formato que o receptor lê embutido) — aparece na TV, ativada pelo controle remoto do Apple TV; o botão CC do app continua mandando na legenda do Chromecast e do player local',
        'Nuvem ensina a converter para a TV: o MKV/HEVC da B2 agora passa pelo mesmo preparo do disco local (e leva a legenda no AirPlay) — o servidor baixa por trás, converte uma vez e serve do cache; custa tráfego da nuvem na primeira vez de cada filete',
      ],
    },
    {
      version: '1.22.0',
      title: 'transmissão sem sustos: capa da série, próximo episódio e vídeo em toda TV',
      changes: [
        'Transmissão: a capa da série aparece no painel e na TV ao transmitir um episódio (o arquivo não tem pôster próprio)',
        'Transmissão: quando o episódio termina, o próximo da série entra sozinho — a TV não fica mais parada na tela final',
        'Transmissão: vídeo HEVC é convertido para H.264 no preparo — era o HEVC 10-bit que deixava a TV com o som rolando e a proteção de tela ligada',
        'AirPlay: a URL enviada à TV é reconstruída do zero — o token velho do player podia duplicar e derrubar a reprodução',
        'Android: o painel não chama mais o aparelho de \'media receiver\' — mostra o nome do Chromecast, ou nada quando o SDK não informa',
        'Coleções e séries: a capa não duplica mais o caminho do arquivo (adeus, pôster 404)',
      ],
    },
    {
      version: '1.21.0',
      title: 'coleções criadas e editadas no próprio app',
      changes: [
        'Botão "Nova coleção": nome, descrição, escolha dos filmes e da capa — sem NFO nem tinyMediaManager',
        'Editar coleção: adicionar/remover filmes, trocar capa, nome e descrição',
        'Coleções vindas de NFO (<set>) são importadas uma única vez, com os mesmos filmes',
        'Gêneros criados na interface, independentes de pastas: atribua pela ficha do filme ou pelo A-Z',
        'Séries: organize em tv shows/Série/Temporada (S01, S02...)/episódios — listagem própria em A-Z, página da série com temporadas e episódios em lista (com legenda)',
        'Continuar assistindo: episódios de série aparecem como lista na home, com retomada no ponto exato',
        'Perfil infantil vira interruptor claro na ficha e na série (marcar a série vale para todos os episódios)',
        'Pasta movies/ na raiz do acervo organiza os filmes (a regra de filme continua valendo fora dela também)',
        'Perfil infantil: conta com modo criança que só vê (e só pode tocar) os filmes marcados — o resto bloqueia até por URL',
        'Marcar/desmarcar filmes para o perfil infantil pela ficha do filme (admin)',
        'Chromecast: tamanho e cor da legenda regulam na TV ao vivo (a escolha fica salva), e o painel de transmissão virou um controle remoto — play, ±10s, Aa e CC',
        'Instalador visual nas 3 plataformas: assistente gráfico no Windows, diálogos nativos no macOS e zenity/kdialog no Linux',
        'Nuvem vira wizard: use qualquer remote do rclone (da lista) ou crie um novo com formulário guiado — B2, Drive, S3, SFTP...',
        'Gênero por pasta sai de vez: filme é qualquer pasta com vídeo direto, na profundidade que for',
        'Filmes soltos (arquivo avulso na pasta) viram filme no A-Z — clique toca direto',
        'Um filme pode estar em várias coleções; quem sai do acervo sai das coleções e dos gêneros no scan',
      ],
    },
    {
      version: '1.20.0',
      title: 'nuvem passa a ser Backblaze B2, configurada pelo próprio app',
      changes: [
        'Google Drive sai do código: a nuvem agora é um bucket Backblaze B2',
        'Cadastro pela interface: keyID, applicationKey e bucket em Ajustes > Nuvem — sem script externo nem OAuth',
        'Backup/restauração vão para o mesmo bucket (com suporte a uma key de escrita separada)',
        'Streaming, cache e fontes locais continuam iguais',
      ],
    },
    {
      version: '1.19.2',
      title: 'migração do prefixo de marca esquecia folders.parent',
      changes: [
        'migração do prefixo de marca esquecia folders.parent',
      ],
    },
    {
      version: '1.19.1',
      title: 'rclone em modo raiz volta a usar o nome real da pasta no Drive',
      changes: [
        'rclone em modo raiz volta a usar o nome real da pasta no Drive',
      ],
    },
    {
      version: '1.19.0',
      title: 'pasta do acervo deixa de exigir o nome TicianoFlix',
      changes: [
        '`LOGICAL_ROOT`: `/TicianoFlix` → `/Mediaflix` — a pasta exigida no Google Drive',
        '`CATALOG_DIR_NAME`: `ticianoflix` → `mediaflix` — a pasta exigida no HD/pendrive, com **compatibilidade retroativa**: quem já tinha criado `TicianoFlix` continua funcionando',
        'Migração de banco automática, uma única vez, na próxima subida do servidor',
        'Textos ajustados para bater com a pasta de verdade (modal de Fontes, painel de rclone, `setup-rclone-seguro.sh`, README)',
      ],
    },
    {
      version: '1.18.0',
      title: 'metadados via TMDB — editor que substitui o tinyMediaManager',
      changes: [
        '`ticianoflix/scraper.py` — cliente TMDB mínimo (`urllib`, sem dependência nova)',
        'Chave gratuita da própria pessoa (**Ajustes › Metadados**), nunca embutida no projeto',
        'Rotas `/api/scrape/status`, `/pendentes`, `/search`, `/apply`, `/key/set` — todas admin',
        '**Ajustes › Metadados**: formulário de chave, lista de filmes sem metadado, busca com resultados, "Usar este" aplica',
      ],
    },
    {
      version: '1.17.0',
      title: 'marca configurável (nome, cor e ícone por instalação)',
      changes: [
        '`ticianoflix/branding.py` — `get()`/`set()` com validação, persistido em `CACHE_DIR/branding.json`',
        'Rotas públicas `/manifest.webmanifest`, `/branding.css`, `/icone-*.png` — geradas em runtime',
        '`/api/branding` (GET) e `/api/branding/set` (POST) — admin, com `Origin` exigido no POST',
        '`<title>`, topbar, sidebar e a tela de login passam a refletir o nome e a cor escolhidos',
        '**Ajustes › Aparência**: nome + seletor de cor, seguindo o padrão visual de Contas/Fontes',
      ],
    },
    {
      version: '1.16.0',
      title: 'instalar o TicianoFlix como app na tela inicial do celular',
      changes: [
        '`static/manifest.webmanifest` — `display: standalone`, `start_url: /`, cor do tema',
        '`static/icons/` — 192, 512, maskable 512 e apple-touch 180',
        '`tools/gerar-icones.py` — gera os ícones a partir do `favicon.svg`',
        'Metatags `apple-*` e `mobile-web-app-capable` no `index.html`',
        'Manifest e ícones passam a responder sem sessão',
        '`mimetypes.add_type` para `.webmanifest`',
      ],
    },
    {
      version: '1.15.0',
      title: 'instalador único (curl | bash), sem exigir git nem log',
      changes: [
        '`install.sh` único, cobrindo Linux e macOS — substitui `install.sh` (Linux) e `install-macos.sh`, que sai do repositório',
        'Serve por `curl -fsSL <url>',
        'bash`, sem clonar nada antes',
        'Não instala nem exige rclone — Drive é 100% opcional',
        'Ao final, espera o servidor responder, lê o código de instalação do log e mostra na tela — ninguém precisa mais abrir arquivo de log — e abre o navegador sozinho',
      ],
    },
    {
      version: '1.14.0',
      title: 'Google Drive deixa de ser pré-requisito (boot de 31s para 0,3s)',
      changes: [
        '`paths.remote_configurado()` — o servidor só tenta subir o `rclone serve` se houver remote',
        '`_porta_responde()` separa "o processo subiu?" de "o Drive respondeu?"',
        'README: Drive sai dos pré-requisitos e vira seção opcional',
        'Exigência cai de Python 3.10+ para **3.9+**',
      ],
    },
    {
      version: '1.13.0',
      title: 'app de Android TV, com a interface da web navegável por controle',
      changes: [
        'Modo TV na web com `?tv=1`: navegação por setas, foco visível e overscan — nada carrega sem a query',
        'Ponte `TicianoFlixTV` no `playMovie()`, desviando o filme para o player nativo quando o app de TV está presente',
        'App de Android TV em Kotlin em `tv/`: WebView + ExoPlayer + descoberta do servidor na rede',
        'Login e `pushState` deixam de descartar a query string da URL',
        '`tv.js` e `tv.css` entram no cache-busting por mtime',
      ],
    },
    {
      version: '1.12.0',
      title: 'coleções de filmes (Star Wars 1-6 e afins)',
      changes: [
        'Item **Coleções** na barra lateral, listando as coleções do acervo',
        'Tela da coleção com os filmes ordenados por ano',
        'Chip na ficha do filme levando para a saga inteira',
        'Rotas `/api/collections` e `/api/collection?name=`',
        'Tabelas `collections` e `movie_collections` — nada alterado nas existentes',
      ],
    },
    {
      version: '1.11.0',
      title: 'AirPlay como alternativa ao Chromecast no iPhone',
      changes: [
        'Botão de AirPlay ao lado do de Chromecast, visível só quando o próprio `<video>` confirma suporte (feature detection via `webkitShowPlaybackTargetPicker`, não user-agent sniffing)',
        'Ao clicar, vídeo e legenda trocam para uma URL assinada (mesmo mecanismo de token do Chromecast) antes de abrir o seletor nativo do iOS',
        '`_fetchMediaToken()` extraído como helper compartilhado entre Cast e AirPlay, no lugar da lógica duplicada',
      ],
    },
    {
      version: '1.10.3',
      title: 'modais e menu lateral cortados no Safari/Chrome do iPhone',
      changes: [
        'modais e menu lateral cortados no Safari/Chrome do iPhone',
      ],
    },
    {
      version: '1.10.2',
      title: 'icone de play do logo quebrava pra linha de baixo no desktop',
      changes: [
        '`.logo-text` ganha `white-space: nowrap` + `flex-shrink: 0`: ícone e nome nunca mais quebram entre si',
        '`.sidebar-header` ganha `flex-wrap: wrap`: quando o selo de versão não cabe do lado, ele desce para uma segunda linha em vez de espremer o logo',
      ],
    },
    {
      version: '1.10.1',
      title: 'wrapper nativo do macOS para de depender de $HOME/TicianoFlix fixo',
      changes: [
        '`ticianoflix-server.c` resolve `server.py` como caminho relativo ao `cwd`, em vez de montar `$HOME/TicianoFlix/server.py`',
      ],
    },
    {
      version: '1.10.0',
      title: 'responsividade real no celular',
      changes: [
        'Barra lateral vira gaveta abaixo de 768px, com barra superior fixa (menu, logo, busca)',
        'Ordem de empilhamento (z-index) organizada numa escala única e documentada',
        'Controles do player reorganizados em duas faixas, com os secundários (volume, velocidade, legenda) num menu "⋯"',
        'Barra de progresso e controle de volume utilizáveis com o dedo',
        'Título do filme sempre visível nos cartazes (antes só aparecia no hover)',
        'Cabeçalho do gênero compacto (de 200px fixos para altura pelo conteúdo)',
        'Toque revela os controles do player (antes dependia de hover/mousemove)',
      ],
    },
    {
      version: '1.9.0',
      title: 'fontes locais — HD externo, pendrive e pastas do computador',
      changes: [
        'Fontes locais: HD externo, pendrive e pastas do computador no mesmo catálogo do Drive',
        'Cadastro por detecção de volumes conectados ou caminho digitado, restrito a administradores',
        'A fonte precisa conter uma pasta `TicianoFlix` (na raiz escolhida ou até dois níveis abaixo), com os gêneros dentro dela',
        'Streaming direto do disco com suporte a Range, para o player conseguir pular no meio do filme',
        'HD desconectado no scan preserva o catálogo daquela fonte em vez de apagá-lo',
        'Menu lateral enxuto: os painéis de manutenção passam a viver num item "Ajustes"',
        'Home com três seções (Últimos Adicionados, Continuar Assistindo, Baixados do Drive) e estatísticas de acervo, fontes conectadas e último scan',
        'Chromecast: legenda corrigida, ficha do filme na TV (pôster, ano, sinopse) e controles do app comandando a transmissão',
      ],
    },
    {
      version: '1.8.0',
      title: 'feat(ui): troca os emojis por ícones SVG em contorno',
      changes: [
        'feat(ui): troca os emojis por ícones SVG em contorno',
      ],
    },
    {
      version: '1.7.0',
      title: 'feat(segurança): reduz o acesso ao Drive ao mínimo necessário',
      changes: [
        'feat(segurança): reduz o acesso ao Drive ao mínimo necessário',
      ],
    },
    {
      version: '1.6.0',
      title: 'Login com contas e hardening de segurança',
      changes: [
        'Login obrigatório: contas com usuário e senha, sessão de 90 dias por aparelho',
        'Primeiro acesso protegido por código de instalação impresso no log do servidor',
        'Painel 👥 Contas para administradores: adicionar, remover, promover e redefinir senha',
        'Chromecast preservado por URL assinada, válida só para aquele arquivo',
        'Fim do CORS aberto e do acesso sem autenticação: Host e Origin validados em toda requisição',
        'Correções: path traversal em /static/, XSS em metadados NFO e rotas destrutivas via GET',
        'rclone serve e configurador passam a escutar apenas em 127.0.0.1',
      ],
    },
    {
      version: '1.5.3',
      title: 'Botão fechar do player',
      changes: [
        'Corrigido modal de confirmação ao fechar o player — abria atrás do vídeo e o botão ✕ parecia não funcionar',
      ],
    },
    {
      version: '1.5.2',
      title: 'Bloqueio do menu durante reprodução',
      changes: [
        'Menu lateral e navegação ao fundo ficam bloqueados enquanto o filme toca (camada do player acima de tudo)',
      ],
    },
    {
      version: '1.5.1',
      title: 'Controles, header e legenda do player',
      changes: [
        'Controles e header somem no fullscreen com o mouse parado (cursor também) — estilo Netflix',
        'Legenda proporcional ao tamanho do player — deixa de ficar gigante ao sair do fullscreen',
        'Cursor de clicável (mãozinha) no breadcrumb do overlay de detalhes',
      ],
    },
    {
      version: '1.5',
      title: 'Busca na sidebar, scan incremental, home reorganizada',
      changes: [
        'Busca movida para a sidebar (acima de Início), com resultados ao vivo enquanto digita e botão limpar (✕)',
        'Resultados de busca em grade única, sem mostrar as pastas dos filmes',
        'Atualização (scan) incremental: só busca filmes novos/alterados e remove os apagados — ~2s em vez de ~40s',
        'Barra de progresso do scan mais compacta',
        'Home reorganizada: Últimos Adicionados (máx. 7) → Continuar Assistindo → Offline',
        'Acesso rápido ao rclone via ☁️ ao lado do uso de cache; menu: Atualizar, Backup, Gerenciar Cache, Limpar Cache',
      ],
    },
  ];

  function openChangelogModal() {
    document.getElementById('changelogModal').classList.add('active');
    document.body.style.overflow = 'hidden';
    const latest = _CHANGELOG[0];
    let html = '<div style="font-size:18px;font-weight:800;color:var(--text);margin-bottom:2px">'
      + 'v' + escHtml(latest.version) + ' — ' + escHtml(latest.title) + '</div>';
    html += '<ul style="margin:10px 0 0;padding-left:20px;font-size:13px;color:var(--text2);line-height:1.8">';
    latest.changes.forEach(c => { html += '<li>' + escHtml(c) + '</li>'; });
    html += '</ul>';
    document.getElementById('changelogContent').innerHTML = html;
  }
  function closeChangelogModal() {
    document.getElementById('changelogModal').classList.remove('active');
    document.body.style.overflow = '';
  }
  document.getElementById('changelogModal').addEventListener('click', function(e) {
    if (e.target === this) closeChangelogModal();
  });

  async function _loadRcloneStatus() {
    const box = document.getElementById('rcloneStatus');
    box.innerHTML = '<div class="loading" style="min-height:100px"><div class="spinner"></div><span>Verificando status do rclone...</span></div>';
    try {
      // Os dois painéis juntos: o status do rclone e o cadastro da nuvem.
      const [resR, resB] = await Promise.all([
        fetch('/api/rclone/status'),
        fetch('/api/nuvem/status').catch(() => null),
      ]);
      const s = await resR.json();
      let nuvem = null;
      if (resB) { try { nuvem = await resB.json(); } catch (e) { nuvem = null; } }
      _renderRcloneStatus(box, s, nuvem);
    } catch(e) {
      box.innerHTML = '<div class="empty-state"><div class="empty-icon"><svg class="icon-svg"><use href="#i-error"></use></svg></div><h3>Erro ao verificar status</h3></div>';
    }
  }

  function _rcloneBadge(ok, textOk, textBad) {
    return ok
      ? '<span class="rclone-badge ok"><svg class="icon-svg"><use href="#i-check"></use></svg> ' + textOk + '</span>'
      : '<span class="rclone-badge bad"><svg class="icon-svg"><use href="#i-close"></use></svg> ' + textBad + '</span>';
  }

  // ==================== NUVEM: WIZARD DE CONEXÃO ====================
  // Qualquer remote rclone vale: usar um que já exista no rclone.conf ou
  // criar um novo — o formulário é gerado a partir de "rclone config
  // providers", que o próprio rclone descreve (tipo, campos, segredos).

  function _renderAcessoNuvem(a) {
    if (!a) return '';
    var html = '<div class="rclone-row"><span class="rclone-label">Acesso à nuvem</span>'
      + '<span class="rclone-badge ' + (a.nivel === 'ok' ? 'ok' : 'bad') + '">'
      + '<svg class="icon-svg"><use href="#i-' + (a.nivel === 'ok' ? 'check' : 'alert') + '"></use></svg> '
      + escHtml(a.nivel === 'ok' ? 'ok' : '?') + '</span></div>';
    if (a.resumo) {
      html += '<div class="rclone-help">' + escHtml(a.resumo) + '</div>';
    }
    return html;
  }

  function _renderNuvemPanel(st, s) {
    var html = '<div class="rclone-subhead"><svg class="icon-svg"><use href="#i-cloud"></use></svg> Nuvem</div>';
    if (st && st.configurado) {
      html += '<div class="rclone-row"><span class="rclone-label">Remote</span>'
        + _rcloneBadge(true, escHtml(st.remote) + (st.tipo ? ' <span class="rclone-mini">' + escHtml(st.tipo) + '</span>' : ''), '') + '</div>';
      html += '<div class="rclone-row"><span class="rclone-label">Pasta do acervo</span>'
        + _rcloneBadge(true, st.pasta ? escHtml(st.pasta) : 'raiz do remote', '') + '</div>';
      html += '<div class="rclone-row"><span class="rclone-label">Backup</span>'
        + _rcloneBadge(true, 'mesma nuvem, pasta "' + 'Media Server Backups"', '') + '</div>';
      if (s && s.acesso) html += _renderAcessoNuvem(s.acesso);
      html += '<div class="rclone-actions">'
        + '<button class="rclone-action-btn primary" onclick="openNuvemWizard()"><svg class="icon-svg"><use href="#i-refresh"></use></svg> Trocar conexão</button>'
        + '<button class="rclone-action-btn" onclick="nuvemDesconectar()"><svg class="icon-svg"><use href="#i-unplug"></use></svg> Desconectar</button>'
        + '</div>';
      html += '<div class="rclone-help">Os arquivos da nuvem não são tocados por nenhuma das duas ações.</div>';
      return html;
    }
    html += '<div class="rclone-help"><svg class="icon-svg"><use href="#i-bulb"></use></svg> '
      + 'Conecte qualquer nuvem que o rclone conhece — Backblaze B2, Google Drive, S3, '
      + 'Dropbox, SFTP... Use um remote que já existe no seu rclone.conf ou crie um '
      + 'novinho pelo assistente.</div>';
    html += '<div class="rclone-actions">'
      + '<button class="rclone-action-btn primary" onclick="openNuvemWizard()"><svg class="icon-svg"><use href="#i-cloud"></use></svg> Conectar nuvem</button>'
      + '</div>';
    return html;
  }

  // ── Wizard ──
  let _wizard = null;   // {passo, remotes[], providers[], filtro, tipo, nome, campos, pasta}

  function openNuvemWizard() {
    _wizard = { passo: 'origem', pasta: '' };
    document.getElementById('nuvemWizardTitulo').innerHTML =
      '<svg class="icon-svg"><use href="#i-cloud"></use></svg> Conectar nuvem';
    document.getElementById('nuvemWizardCorpo').innerHTML =
      '<div class="loading" style="min-height:100px"><div class="spinner"></div><span>Carregando...</span></div>';
    document.getElementById('nuvemWizardModal').classList.add('active');
    document.body.style.overflow = 'hidden';
    _wizardPassoOrigem();
  }

  function closeNuvemWizard() {
    document.getElementById('nuvemWizardModal').classList.remove('active');
    document.body.style.overflow = '';
    _wizard = null;
    _loadRcloneStatus();
  }
  document.getElementById('nuvemWizardModal').addEventListener('click', function(e) {
    if (e.target === this) closeNuvemWizard();
  });

  function _wizardCorpo(html) {
    document.getElementById('nuvemWizardCorpo').innerHTML = html
      + '<div id="nuvemWizardMsg"></div>';
  }

  function _wizardErro(texto) {
    document.getElementById('nuvemWizardMsg').innerHTML =
      '<div class="user-msg err">' + escHtml(texto) + '</div>';
  }

  function _wizardPassoOrigem() {
    _wizard.passo = 'origem';
    _wizardCorpo(
      '<div class="wizard-origem">'
      + '<button class="wizard-opcao" onclick="_wizardPassoExistente()">'
      + '<span class="wizard-opcao-icone"><svg class="icon-svg"><use href="#i-layers"></use></svg></span>'
      + '<span><b>Usar um remote existente</b><br>'
      + '<small>Escolha na lista do seu rclone.conf</small></span></button>'
      + '<button class="wizard-opcao" onclick="_wizardPassoNovoTipo()">'
      + '<span class="wizard-opcao-icone"><svg class="icon-svg"><use href="#i-plus"></use></svg></span>'
      + '<span><b>Criar um remote novo</b><br>'
      + '<small>Assistente com os campos de cada nuvem</small></span></button>'
      + '</div>'
      + '<div class="colecao-passos"><span></span>'
      + '<button class="rclone-action-btn" onclick="closeNuvemWizard()">Cancelar</button></div>');
  }

  function _wizardPassoExistente() {
    _wizard.passo = 'existente';
    _wizardCorpo('<div class="loading" style="min-height:90px"><div class="spinner"></div><span>Listando remotes...</span></div>');
    fetch('/api/rclone/remotes').then(r => r.json()).then(remotes => {
      if (!Array.isArray(remotes)) {
        _wizardErro((remotes && remotes.error) || 'Falha ao listar remotes.');
        return;
      }
      _wizard.remotes = remotes;
      if (!remotes.length) {
        _wizardCorpo('<p class="colecao-dica">Seu rclone.conf ainda não tem remote nenhum. '
          + 'Crie um pelo assistente:</p>'
          + '<div class="colecao-passos">'
          + '<button class="rclone-action-btn" onclick="_wizardPassoOrigem()">← Voltar</button>'
          + '<button class="rclone-action-btn primary" onclick="_wizardPassoNovoTipo()">Criar remote</button>'
          + '</div>');
        return;
      }
      let opcoes = remotes.map(r =>
        '<button class="wizard-remoto" data-nome="' + escHtml(r.nome) + '" '
        + 'onclick="_wizardEscolherRemote(this, \'' + escHtml(r.nome) + '\')">'
        + '<b>' + escHtml(r.nome) + '</b>'
        + '<span class="wizard-remoto-tipo">' + escHtml(r.tipo || '?') + '</span></button>').join('');
      _wizardCorpo('<div class="colecao-secao-titulo">Escolha o remote</div>'
        + '<div class="wizard-lista">' + opcoes + '</div>'
        + '<label class="colecao-campo"><span>Pasta do acervo dentro do remote <em>(opcional)</em></span>'
        + '<input id="wizardPasta" type="text" placeholder="deixe vazio para usar a raiz do remote"></label>'
        + '<div class="colecao-passos">'
        + '<button class="rclone-action-btn" onclick="_wizardPassoOrigem()">← Voltar</button>'
        + '<button class="rclone-action-btn primary" onclick="_wizardConectar()">Conectar</button>'
        + '</div>');
    }).catch(() => _wizardErro('Falha de conexão com o servidor.'));
  }

  function _wizardEscolherRemote(el, nome) {
    document.querySelectorAll('.wizard-remoto').forEach(b => b.classList.remove('escolhido'));
    el.classList.add('escolhido');
    _wizard.remote = nome;
  }

  function _wizardPastaLida() {
    const el = document.getElementById('wizardPasta');
    return el ? el.value.trim().replace(/^\/+|\/+$/g, '') : '';
  }

  function _wizardConectar() {
    if (!_wizard) return;
    if (_wizard.passo === 'existente' && !_wizard.remote) {
      _wizardErro('Escolha um remote da lista.');
      return;
    }
    const pasta = _wizardPastaLida();
    const btns = document.querySelectorAll('#nuvemWizardCorpo .rclone-action-btn.primary');
    if (btns.length) btns[btns.length - 1].disabled = true;
    fetch('/api/nuvem/conectar', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ remote: _wizard.remote, pasta: pasta }),
    }).then(r => r.json()).then(data => {
      if (data.status === 'ok') {
        showToast('☁️ Nuvem conectada: ' + data.remote, 'success');
        closeNuvemWizard();
      } else {
        _wizardErro(data.error || 'Não foi possível conectar.');
        if (btns.length) btns[btns.length - 1].disabled = false;
      }
    }).catch(() => {
      _wizardErro('Falha de conexão com o servidor.');
      if (btns.length) btns[btns.length - 1].disabled = false;
    });
  }

  function nuvemDesconectar() {
    _confirmarGenerico('Desconectar a nuvem?',
      'O app deixa de mostrar o acervo da nuvem. O remote e os arquivos ficam intactos no rclone.',
      function() {
        fetch('/api/nuvem/desconectar', { method: 'POST' })
          .then(r => r.json())
          .then(data => {
            showToast('Nuvem desconectada', 'info');
            _loadRcloneStatus();
          }).catch(() => showToast('Erro ao desconectar', 'error'));
      });
  }

  // ── Wizard: criar remote novo ──
  function _wizardPassoNovoTipo() {
    _wizard.passo = 'novo';
    _wizardCorpo('<div class="loading" style="min-height:90px"><div class="spinner"></div><span>Carregando nuvens suportadas...</span></div>');
    fetch('/api/rclone/providers').then(r => r.json()).then(providers => {
      if (!Array.isArray(providers)) {
        _wizardErro((providers && providers.error) || 'Falha ao carregar os tipos.');
        return;
      }
      _wizard.providers = providers;
      _wizardRenderTipos();
    }).catch(() => _wizardErro('Falha de conexão com o servidor.'));
  }

  function _wizardRenderTipos() {
    const busca = (_wizard.filtro || '').toLowerCase();
    const lista = _wizard.providers.filter(p =>
      !busca || p.nome.toLowerCase().includes(busca) || p.tipo.toLowerCase().includes(busca));
    const corpos = lista.slice(0, 60).map(p =>
      '<button class="wizard-remoto" onclick="_wizardEscolherTipo(\'' + escHtml(p.tipo) + '\')">'
      + '<b>' + escHtml(p.nome) + '</b>'
      + '<span class="wizard-remoto-tipo">' + escHtml(p.tipo) + '</span></button>').join('');
    _wizardCorpo('<div class="colecao-secao-titulo">Qual é a nuvem?</div>'
      + '<input id="wizardFiltro" class="colecao-busca" type="text" placeholder="Filtrar (ex.: b2, drive, s3, sftp)..." '
      + 'value="' + escHtml(_wizard.filtro || '') + '" oninput="_wizardFiltrarTipos(this.value)">'
      + '<div class="wizard-lista" id="wizardListaTipos">' + corpos + '</div>'
      + (lista.length > 60 ? '<div class="colecao-dica">Mostrando 60 de ' + lista.length + ' — filtre para achar.</div>' : '')
      + '<div class="colecao-passos">'
      + '<button class="rclone-action-btn" onclick="_wizardPassoOrigem()">← Voltar</button><span></span>'
      + '</div>');
  }

  function _wizardFiltrarTipos(valor) {
    _wizard.filtro = valor;
    _wizardRenderTipos();
    const campo = document.getElementById('wizardFiltro');
    if (campo) { campo.focus(); campo.setSelectionRange(valor.length, valor.length); }
  }

  function _wizardEscolherTipo(tipo) {
    const p = _wizard.providers.find(x => x.tipo === tipo);
    if (!p) return;
    _wizard.tipo = tipo;
    _wizard.nomeTipo = p.nome;
    // Campos do backend, na ordem do rclone — senha vira password, exemplos
    // viram sugestões de preenchimento.
    const campos = p.opcoes.map(o => {
      const id = 'wz_' + o.nome;
      const lista = o.exemplos && o.exemplos.length
        ? '<datalist id="dl_' + id + '">' + o.exemplos.map(e => '<option value="' + escHtml(e) + '">').join('') + '</datalist>' : '';
      const obrig = o.obrigatorio ? ' <em>*</em>' : '';
      return lista + '<label class="colecao-campo"><span>' + escHtml(o.nome) + obrig + '</span>'
        + '<input id="' + id + '" type="' + (o.senha ? 'password' : 'text') + '"'
        + (o.exemplos && o.exemplos.length ? ' list="dl_' + id + '"' : '')
        + (o.padrao ? ' placeholder="' + escHtml(o.padrao) + '"' : '')
        + ' autocomplete="off"></label>'
        + (o.ajuda ? '<div class="wizard-ajuda">' + escHtml(o.ajuda) + '</div>' : '');
    }).join('');
    _wizardCorpo('<div class="colecao-secao-titulo">Novo remote: ' + escHtml(p.nome) + '</div>'
      + '<label class="colecao-campo"><span>Nome do remote</span>'
      + '<input id="wizardNome" type="text" value="' + escHtml(tipo) + '" maxlength="30"></label>'
      + campos
      + '<div class="colecao-passos">'
      + '<button class="rclone-action-btn" onclick="_wizardPassoNovoTipo()">← Voltar</button>'
      + '<button class="rclone-action-btn primary" id="wizardCriarBtn" onclick="_wizardCriarRemote()">Criar e testar</button>'
      + '</div>');
  }

  function _wizardCriarRemote() {
    const nome = (document.getElementById('wizardNome').value || '').trim();
    if (!nome) { _wizardErro('Dê um nome ao remote.'); return; }
    const p = _wizard.providers.find(x => x.tipo === _wizard.tipo);
    const parametros = {};
    (p ? p.opcoes : []).forEach(o => {
      const el = document.getElementById('wz_' + o.nome);
      if (el && el.value.trim()) parametros[o.nome] = el.value.trim();
    });
    const btn = document.getElementById('wizardCriarBtn');
    if (btn) { btn.disabled = true; btn.textContent = 'Criando...'; }
    fetch('/api/rclone/wizard', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ nome: nome, tipo: _wizard.tipo, parametros: parametros }),
    }).then(r => r.json()).then(data => {
      if (data.status === 'ok') {
        showToast('✅ Remote "' + data.nome + '" criado e testado.', 'success');
        _wizard.remote = data.nome;
        _wizard.passo = 'existente';
        _wizardCorpo('<p class="colecao-dica">Remote <b>' + escHtml(data.nome) + '</b> criado e respondendo. '
          + 'Agora diga onde o acervo mora dentro dele (ou use a raiz):</p>'
          + '<label class="colecao-campo"><span>Pasta do acervo <em>(opcional)</em></span>'
          + '<input id="wizardPasta" type="text" placeholder="raiz do remote"></label>'
          + '<div class="colecao-passos">'
          + '<button class="rclone-action-btn" onclick="_wizardPassoOrigem()">← Voltar</button>'
          + '<button class="rclone-action-btn primary" onclick="_wizardConectar()">Conectar</button>'
          + '</div>');
      } else {
        _wizardErro(data.error || 'Falha ao criar o remote.');
        if (btn) { btn.disabled = false; btn.textContent = 'Criar e testar'; }
      }
    }).catch(() => {
      _wizardErro('Falha de conexão com o servidor.');
      if (btn) { btn.disabled = false; btn.textContent = 'Criar e testar'; }
    });
  }

  function _renderRcloneStatus(box, s, b2) {
    let html = '';
    html += '<div class="rclone-row"><span class="rclone-label">rclone instalado</span>'
      + (s.installed ? _rcloneBadge(true, s.version || 'ok', '') : _rcloneBadge(false, '', 'não encontrado')) + '</div>';

    if (s.installed) {
      // Conexão da nuvem primeiro: sem ela, o resto do painel é secundário.
      html += _renderNuvemPanel(b2, s);
      html += '<div class="rclone-subhead"><svg class="icon-svg"><use href="#i-gear"></use></svg> rclone</div>';
      html += '<div class="rclone-row"><span class="rclone-label">Remote no rclone.conf</span>'
        + _rcloneBadge(s.remote_configured, escHtml(s.remote || 'configurado'), 'não configurado') + '</div>';
      if (s.remote_configured) {
        html += '<div class="rclone-row"><span class="rclone-label">Conexão com a nuvem</span>'
          + (s.remote_ok ? _rcloneBadge(true, 'ok', '') : _rcloneBadge(false, '', s.remote_error || 'falhou')) + '</div>';
      }
      html += '<div class="rclone-row"><span class="rclone-label">Streaming (serve)</span>'
        + _rcloneBadge(s.serve_running, 'ativo :18082', 'parado') + '</div>';
      html += '<div class="rclone-row"><span class="rclone-label">Web UI de configuração</span>'
        + _rcloneBadge(s.webgui.running, 'ativa :' + s.webgui.port, 'fechada') + '</div>';

      html += '<div class="rclone-actions">';
      if (s.remote_configured) {
        html += '<button class="rclone-action-btn" onclick="rcloneStartWebgui()"><svg class="icon-svg"><use href="#i-gear"></use></svg> Abrir configurador</button>';
      }
      if (!s.serve_running && s.remote_configured) {
        html += '<button class="rclone-action-btn primary" onclick="rcloneRestartServe()"><svg class="icon-svg"><use href="#i-refresh"></use></svg> Reiniciar streaming</button>';
      }
      if (s.webgui.running) {
        html += '<button class="rclone-action-btn" onclick="rcloneStopWebgui()"><svg class="icon-svg"><use href="#i-stop"></use></svg> Fechar web UI</button>';
      }
      html += '<button class="rclone-action-btn" onclick="_loadRcloneStatus()"><svg class="icon-svg"><use href="#i-refresh"></use></svg> Atualizar status</button>';
      html += '</div>';
    } else {
      html += '<div class="rclone-help">O rclone não foi encontrado. Rode o instalador do 12:00 Media Server '
        + '(ele baixa o rclone sozinho) ou instale manualmente:<br>'
        + '<b>Linux:</b> <code>sudo pacman -S rclone</code> ou <code>sudo apt install rclone</code><br>'
        + '<b>macOS:</b> <code>brew install rclone</code><br>'
        + '<b>Windows:</b> <code>winget install Rclone.Rclone</code><br>'
        + 'Ou baixe em <a href="https://rclone.org/downloads/" target="_blank" rel="noopener">rclone.org/downloads</a></div>';
      html += '<div class="rclone-actions">'
        + '<button class="rclone-action-btn" onclick="_loadRcloneStatus()"><svg class="icon-svg"><use href="#i-refresh"></use></svg> Atualizar status</button>'
        + '</div>';
    }

    if (s.webgui.running) {
      html += '<div class="rclone-creds">Web UI aberta — acessível apenas neste computador:<br>'
        + 'URL: <a href="' + escHtml(s.webgui.url) + '" target="_blank" rel="noopener">' + escHtml(s.webgui.url) + '</a><br>'
        + 'Sem login: a interface escuta só em 127.0.0.1.</div>';
    }
    box.innerHTML = html;
  }

  async function rcloneStartWebgui() {
    const box = document.getElementById('rcloneStatus');
    box.innerHTML = '<div class="loading" style="min-height:100px"><div class="spinner"></div><span>Abrindo configurador do rclone...</span></div>';
    try {
      const res = await fetch('/api/rclone/webgui/start', { method: 'POST' });
      const data = await res.json();
      if (data.status === 'ok' && data.url) {
        box.innerHTML = '<div class="rclone-creds"><b><svg class="icon-svg"><use href="#i-check-circle"></use></svg> Configurador aberto!</b><br><br>'
          + 'URL: <a href="' + escHtml(data.url) + '" target="_blank" rel="noopener">' + escHtml(data.url) + '</a><br>'
          + 'Acessível apenas neste computador, sem login.</div>'
          + '<div class="rclone-help">Se a aba não abrir sozinha, clique no link acima e faça login.<br>'
          + '<svg class="icon-svg"><use href="#i-bulb"></use></svg> Cadastre a nuvem em <b>Ajustes &gt; Nuvem</b> — o rclone.conf é escrito pelo próprio app. Esta web UI fica como ferramenta avançada.</div>'
          + '<div class="rclone-actions"><button class="rclone-action-btn" onclick="_loadRcloneStatus()"><svg class="icon-svg"><use href="#i-refresh"></use></svg> Verificar status</button></div>';
        window.open(data.url, '_blank');
      } else {
        box.innerHTML = '<div class="empty-state"><div class="empty-icon"><svg class="icon-svg"><use href="#i-error"></use></svg></div><h3>Erro ao abrir configurador</h3><p>' + escHtml(data.error || 'Erro desconhecido') + '</p></div>'
          + '<div class="rclone-actions"><button class="rclone-action-btn" onclick="_loadRcloneStatus()"><svg class="icon-svg"><use href="#i-arrow-left"></use></svg> Voltar</button></div>';
      }
    } catch(e) {
      box.innerHTML = '<div class="empty-state"><div class="empty-icon"><svg class="icon-svg"><use href="#i-error"></use></svg></div><h3>Erro ao abrir configurador</h3></div>';
    }
  }

  async function rcloneRestartServe() {
    const box = document.getElementById('rcloneStatus');
    box.innerHTML = '<div class="loading" style="min-height:100px"><div class="spinner"></div><span>Reiniciando streaming...</span></div>';
    try {
      const res = await fetch('/api/rclone/serve/restart', { method: 'POST' });
      const data = await res.json();
      if (data.status === 'ok') {
        showToast('✅ Streaming reiniciado', 'success');
      } else {
        showToast('Erro: ' + (data.error || 'falhou'), 'error');
      }
    } catch(e) {
      showToast('Erro ao reiniciar streaming', 'error');
    }
    _loadRcloneStatus();
  }

  async function rcloneStopWebgui() {
    try {
      await fetch('/api/rclone/webgui/stop', { method: 'POST' });
      showToast('⏹ Web UI fechada', 'info');
    } catch(e) {}
    _loadRcloneStatus();
  }

  async function restoreFromFile(input) {
    const file = input.files[0];
    if (!file) return;
    closeBackupModal();
    showToast('📂 Restaurando backup...', '');
    try {
      // Corpo = o proprio arquivo: o servidor le os bytes crus do zip e aplica
      // o teto de tamanho; em FormData o multipart nunca passou no zipfile
      // (a restauracao falhava sempre com "Falha ao restaurar o backup").
      const res = await fetch('/api/restore', { method: 'POST', body: file });
      const data = await res.json();
      if (data.error) {
        showToast('Erro: ' + data.error, 'error');
      } else {
        showToast('✅ ' + (data.message || 'Backup restaurado!'), 'success');
        setTimeout(() => loadPath(''), 3000);
      }
    } catch(e) {
      showToast('Erro ao restaurar: ' + e.message, 'error');
    }
    input.value = '';
  }

  async function restoreFromCloud() {
    closeBackupModal();
    showToast('☁️ Baixando backup da nuvem...', '');
    try {
      const res = await fetch('/api/restore/b2', { method: 'POST' });
      const data = await res.json();
      if (data.error) {
        showToast('Erro: ' + data.error, 'error');
      } else {
        showToast('✅ ' + (data.message || 'Backup restaurado!'), 'success');
        setTimeout(() => loadPath(''), 3000);
      }
    } catch(e) {
      showToast('Erro ao restaurar: ' + e.message, 'error');
    }
  }

  // ==================== BACKUP / DOWNLOAD ====================
  async function downloadBackup() {
    try {
      showToast('📦 Gerando backup...', '');
      const res = await fetch('/api/backup');
      if (!res.ok) { showToast('Erro ao gerar backup', 'error'); return; }
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = 'media-server-backup-' + new Date().toISOString().slice(0,10) + '.zip';
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
      showToast('📦 Backup baixado!', 'success');
    } catch(e) {
      showToast('Erro no backup: ' + e.message, 'error');
    }
  }

  async function backupToCloud() {
    try {
      showToast('☁️ Enviando backup para a nuvem...', '');
      const res = await fetch('/api/backup/b2', { method: 'POST' });
      const data = await res.json();
      if (data.status === 'ok') {
        showToast('☁️ Backup salvo em: ' + data.path, 'success');
      } else {
        showToast('Erro: ' + (data.error || 'falha ao enviar'), 'error');
      }
    } catch(e) {
      showToast('Erro ao enviar: ' + e.message, 'error');
    }
  }

  // ==================== REFRESH CACHE ====================
  let _refreshPollTimer = null;
  let _refreshFallbackTimer = null;
  let _scanProgressTimer = null;

  // Acompanha o scan em andamento: barra de progresso, limpeza dos timers e
  // recarga do catalogo no fim. Usado pelo botao Atualizar e pelo scan de uma
  // fonte so, no modal de Fontes.
  function _watchScanProgress() {
    const btn = document.getElementById('refreshBtn');
    const icon = btn ? btn.querySelector('.icon') : null;
    // Show progress bar
    const pbar = document.getElementById('scanProgressBar');
    const pfill = document.getElementById('scanProgressFill');
    const ptext = document.getElementById('scanProgressText');
    pbar.style.display = 'block';
    pfill.style.width = '0%';
    ptext.textContent = 'Preparando...';

    // Visual feedback: spin icon, highlight text
    if (btn) btn.classList.add('loading');
    if (icon) icon.innerHTML = '<svg class="icon-svg"><use href="#i-refresh"></use></svg>';

    // Start polling scan-progress
    if (_scanProgressTimer) clearInterval(_scanProgressTimer);
    _scanProgressTimer = setInterval(async () => {
      try {
        const r = await fetch('/api/scan-progress');
        const s = await r.json();
        pfill.style.width = s.percent + '%';
        // Com mais de uma fonte, dizer qual esta sendo escaneada agora.
        const srcPrefix = (s.source_total > 1 && s.source_current)
          ? s.source_current + ' — ' : '';
        if (s.phase === 'genres') {
          if (s.movie_index > 0) {
            ptext.textContent = `${srcPrefix}${s.genre_current}: ${s.movie_index} filmes (${s.genre_index}/${s.genre_total})`;
          } else {
            ptext.textContent = `${srcPrefix}${s.genre_index}/${s.genre_total}`;
          }
        } else if (s.phase === 'listing_root') {
          ptext.textContent = s.source_current ? ('Listando ' + s.source_current + '...') : 'Listando raiz...';
        } else if (s.phase === 'done') {
          clearInterval(_scanProgressTimer);
          _scanProgressTimer = null;
          clearInterval(_refreshPollTimer);
          _refreshPollTimer = null;
          clearTimeout(_refreshFallbackTimer);
          _refreshFallbackTimer = null;
          if (btn) btn.classList.remove('loading');
          if (icon) icon.innerHTML = '<svg class="icon-svg"><use href="#i-refresh"></use></svg>';
          pbar.style.display = 'none';
          _frontCache = {};
          _sidebarGenresLoaded = false;
          loadSidebarGenres(true);
          showToast('Escaneamento concluído!', 'success');
          loadPath(currentPath || '');
        } else if (s.phase === 'error') {
          clearInterval(_scanProgressTimer);
          _scanProgressTimer = null;
          if (btn) btn.classList.remove('loading');
          if (icon) icon.innerHTML = '<svg class="icon-svg"><use href="#i-refresh"></use></svg>';
          pbar.style.display = 'none';
          showToast('Erro ao escanear. Confira a nuvem e as fontes locais.', 'error');
          loadPath(currentPath || '');
        }
      } catch (_) {}
    }, 800);

    // Also poll cache-status as fallback (backward compat)
    let attempts = 0;
    _refreshPollTimer = setInterval(async () => {
      attempts++;
      try {
        const r = await fetch('/api/cache-status');
        const s = await r.json();
        if (s.cached) {
          clearInterval(_refreshPollTimer);
          _refreshPollTimer = null;
          clearInterval(_scanProgressTimer);
          _scanProgressTimer = null;
          clearTimeout(_refreshFallbackTimer);
          _refreshFallbackTimer = null;
          if (btn) btn.classList.remove('loading');
          if (icon) icon.innerHTML = '<svg class="icon-svg"><use href="#i-refresh"></use></svg>';
          pbar.style.display = 'none';
          _frontCache = {};
          _sidebarGenresLoaded = false;
          loadSidebarGenres(true);
          showToast('Escaneamento concluído!', 'success');
          loadPath(currentPath || '');
        }
      } catch (_) {}
      if (attempts > 120) {
        clearInterval(_refreshPollTimer);
        _refreshPollTimer = null;
        clearInterval(_scanProgressTimer);
        _scanProgressTimer = null;
        if (btn) btn.classList.remove('loading');
        if (icon) icon.innerHTML = '<svg class="icon-svg"><use href="#i-refresh"></use></svg>';
        pbar.style.display = 'none';
        loadPath(currentPath || '');
      }
    }, 1500);

    _refreshFallbackTimer = setTimeout(() => {
      clearInterval(_refreshPollTimer);
      _refreshPollTimer = null;
      clearInterval(_scanProgressTimer);
      _scanProgressTimer = null;
      btn.classList.remove('loading');
      if (icon) icon.innerHTML = '<svg class="icon-svg"><use href="#i-refresh"></use></svg>';
      pbar.style.display = 'none';
      _frontCache = {};
      loadPath(currentPath || '');
    }, 240000);

  }

  async function refreshCache() {
    const btn = document.getElementById('refreshBtn');
    const icon = btn.querySelector('.icon');

    try {
      const res = await fetch('/api/refresh', { method: 'POST' });
      const body = await res.json();

      if (body.status === 'already_scanning') {
        showToast('Escaneamento já está em andamento...', 'info');
        return;
      }

      _watchScanProgress();

    } catch(e) {
      btn.classList.remove('loading');
      if (icon) icon.innerHTML = '<svg class="icon-svg"><use href="#i-refresh"></use></svg>';
      document.getElementById('scanProgressBar').style.display = 'none';
      console.error('Refresh failed:', e.message || e);
      loadPath(currentPath || '');
    }
  }

  // ==================== INIT ====================
  loadPath("", true);
  loadSidebarGenres();
  // Sync _cachedSet with server's actual cache state (for offline section on home)
  _syncCachedFromServer().then(() => _renderOfflineGrid());

  // Fetch cache usage
  async function updateCacheUsage() {
    try {
      const r = await fetch('/api/cache-status');
      const s = await r.json();
      if (s.usage) {
        const t = s.usage.total;
        let h = '';
        if (t < 1024) h = t + 'B';
        else if (t < 1048576) h = (t / 1024).toFixed(1) + 'K';
        else if (t < 1073741824) h = (t / 1048576).toFixed(1) + 'M';
        else h = (t / 1073741824).toFixed(2) + 'G';
        if (s.usage.details.vfs > 0) h += ' (VFS)';
        document.getElementById('cacheUsageSize').textContent = h;
      }
    } catch(_) {}
  }
  updateCacheUsage();
  // Aba oculta nao precisa do contador: com o app aberto em TV, celular e
  // notebook, o /api/cache-status de 30 em 30s virava consulta constante
  // sem ninguem olhando. Ao reaparecer, atualiza na hora.
  setInterval(() => { if (!document.hidden) updateCacheUsage(); }, 30000);
  document.addEventListener('visibilitychange', () => {
    if (!document.hidden) updateCacheUsage();
  });

  // Quem esta logado: mostra o nome no botao Sair e revela "Contas" para admin.
  _loadMe();
