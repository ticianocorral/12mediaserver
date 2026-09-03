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
    const fullPath = folderPath + '/' + imageName;
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
      html += renderMovieCardHtml(name, filePath, item.Size, posterSrc);
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
    return kind === 'drive'
      ? '<svg class="icon-svg"><use href="#i-cloud"></use></svg>'
      : '<svg class="icon-svg"><use href="#i-hard-drive"></use></svg>';
  }

  // Agrupa os generos pela fonte dona deles. O servidor manda o Path completo
  // de cada genero, entao nao ha prefixo remontado no cliente.
  // id da fonte -> nome de exibicao. O id e o mesmo slug que aparece no path
  // ("/Local/hd-externo"), entao o breadcrumb mostra "HD Externo".
  const _sourceNames = {};

  function groupGenresBySource(data) {
    const sources = data.sources || [];
    sources.forEach(src => { _sourceNames[src.id] = src.name; });
    const seen = {};
    const groups = [];
    // A ordem e a das fontes (Drive primeiro, locais em ordem alfabetica), nao
    // a ordem alfabetica dos generos — senao as fontes se intercalariam.
    sources.forEach(src => {
      seen[src.id] = { id: src.id, source: src, items: [] };
      groups.push(seen[src.id]);
    });
    (data.folders || []).forEach(g => {
      const id = g.source || '';
      if (!seen[id]) {
        seen[id] = { id: id, source: null, items: [] };
        groups.push(seen[id]);
      }
      seen[id].items.push(g);
    });
    return groups.filter(grp => grp.items.length > 0);
  }

  function loadSidebarGenres(force) {
    const container = document.getElementById('sidebarGenres');
    if (_sidebarGenresLoaded && !force) return;
    _sidebarGenresLoaded = true;
    cachedFetch('/api/genres').then(data => {
      if (!data || !data.folders) return;
      const groups = groupGenresBySource(data);
      // Com uma fonte so, o cabecalho seria ruido: ele so aparece quando ha
      // mais de uma para separar.
      const showHeaders = groups.length > 1;
      let html = '';
      groups.forEach(grp => {
        const src = grp.source;
        if (showHeaders) {
          const off = src && src.online === false;
          html += '<div class="sidebar-source-label' + (off ? ' offline' : '') + '">'
            + sourceIcon(src ? src.kind : 'local') + ' '
            + escHtml(src ? src.name : 'Outros')
            + (off ? ' · desconectada' : '') + '</div>';
        }
        grp.items.forEach(g => {
          const name = g.Name || '';
          const path = '/' + g.Path;
          html += '<button class="sidebar-item" onclick="loadPath(decodeURIComponent(\'' + enc(path) + '\'))">'
            + '<span class="icon">' + genreIcon(name) + '</span> '
            + escHtml(name) + '</button>';
        });
      });
      container.innerHTML = html;
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
    document.getElementById('content').innerHTML = '<div class="loading"><div class="spinner"></div><span>Carregando...</span></div>';
    document.getElementById('searchInput').value = '';
    _updateSearchClear();

    // Close any open info overlay
    closeMovieInfo();

    // Coleção não é uma pasta, mas entra pelo mesmo caminho de navegação
    // (pushState/popstate) — assim o botão Voltar do navegador funciona nela
    // igual funciona num gênero, sem um segundo mecanismo de histórico.
    if (path && path.indexOf(COLECAO_PREFIXO) === 0) {
      renderCollectionView(path.slice(COLECAO_PREFIXO.length));
      return;
    }
    if (path === LISTA_COLECOES) {
      renderCollectionsList();
      return;
    }

    const isHome = isHomePage(path);
    const url = isHome ? '/api/genres' : ('/api/list?path=' + encodeURIComponent(path));

    cachedFetch(url).then(data => {
      if (!data) {
        document.getElementById('content').innerHTML = '<div class="empty-state"><div class="empty-icon"><svg class="icon-svg"><use href="#i-error"></use></svg></div><h3>Erro ao carregar</h3><p>Não foi possível conectar ao servidor.</p></div>';
        return;
      }
      renderDirectory(data);
    });
  }

  // ==================== A-Z VIEW ====================
  function loadAZ() {
    currentPath = '__az__';
    document.getElementById('searchInput').value = '';
    _updateSearchClear();
    closeMovieInfo();
    document.getElementById('hero').style.display = 'none';
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
        html += '<div class="movie-card" onclick="showMovieInfo(decodeURIComponent(\'' + safePath + '\'), event)" title="' + escHtml(m.name) + '">';
        if (m.poster) {
          html += '<img class="movie-card-poster" src="' + posterUrl(m.path, m.poster) + '" alt="' + escHtml(nameClean) + '" loading="lazy" onerror="this.style.display=\'none\';this.nextElementSibling.style.display=\'flex\'">';
          html += '<div class="movie-card-poster-placeholder" style="display:none"><svg class="icon-svg"><use href="#i-film"></use></svg></div>';
        } else {
          html += '<div class="movie-card-poster-placeholder" style="display:flex"><svg class="icon-svg"><use href="#i-film"></use></svg></div>';
        }
        html += '<div class="movie-card-overlay"><div class="movie-card-title">' + escHtml(nameClean) + '</div></div>';
        html += '</div>';
      });
      html += '</div></div>';
    });
    document.getElementById('content').innerHTML = html;
  }

  function isHomePage(path) {
    return path === '' || path === '/' || path === (window.__LOGICAL_ROOT__ || '/TicianoFlix');
  }

  function renderDirectory(data) {
    const container = document.getElementById('content');
    const hero = document.getElementById('hero');
    hero.style.display = 'block';
    _heroCapa(null, null);

    const isHome = isHomePage(data.path);

    if (!isHome) {
      renderBreadcrumb(data.path);
    } else {
      document.getElementById('breadcrumb').innerHTML = '';
    }
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
        <div class="home-stat">
          <div class="home-stat-icon"><svg class="icon-svg"><use href="#i-film"></use></svg></div>
          <div class="home-stat-num" id="statMovies">—</div>
          <div class="home-stat-label">Filmes no acervo</div>
        </div>
        <div class="home-stat" onclick="openSourcesOrSettings()" title="Fontes do acervo">
          <div class="home-stat-icon"><svg class="icon-svg"><use href="#i-hard-drive"></use></svg></div>
          <div class="home-stat-num" id="statSources">—</div>
          <div class="home-stat-label" id="statSourcesLabel">Fontes conectadas</div>
        </div>
        <div class="home-stat" onclick="openCacheManager()" title="Gerenciar o cache offline">
          <div class="home-stat-icon"><svg class="icon-svg"><use href="#i-download"></use></svg></div>
          <div class="home-stat-num" id="statDownloaded">—</div>
          <div class="home-stat-label" id="statDownloadedLabel">Baixados do Drive</div>
        </div>
        <div class="home-stat" onclick="refreshCache()" title="Escanear todas as fontes agora">
          <div class="home-stat-icon"><svg class="icon-svg"><use href="#i-refresh"></use></svg></div>
          <div class="home-stat-num" id="statScan">—</div>
          <div class="home-stat-label">Último scan</div>
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
      </div>
      <div class="genre-section" id="offlineSection" style="display:none">
        <div class="genre-header" style="cursor:default;border:none">
          <div class="genre-title"><svg class="icon-svg"><use href="#i-download"></use></svg> Baixados do Drive</div>
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
        html += '<div class="movie-card" onclick="showMovieInfo(decodeURIComponent(\'' + safePath + '\'), event)" title="' + escHtml(m.name) + '">'
          + '<div class="movie-card-poster-placeholder" style="display:flex"><svg class="icon-svg"><use href="#i-film"></use></svg></div>'
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
      items.forEach((m, idx) => {
        const pct = (m.duration > 0) ? Math.round((m.position / m.duration) * 100) : 0;
        const nameClean = (m.title || m.name || '').replace(/[._]/g, ' ').replace(/\.[^.]+$/, '');
        const safePath = enc(m.path);
        const posStr = Math.floor(m.position / 60) + ':' + String(Math.floor(m.position % 60)).padStart(2, '0');
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
      grid.innerHTML = html2;
    });

    // Carrega filmes marcados como offline
    _renderOfflineGrid();
  }

  // "há 5 min" / "há 2 h" / "há 3 dias" — o valor cru (timestamp) nao diz nada
  // a quem so quer saber se o catalogo esta velho.
  function tempoDesde(ts) {
    if (!ts) return 'nunca';
    const seg = Math.max(0, Math.floor(Date.now() / 1000) - parseInt(ts, 10));
    if (seg < 90) return 'agora';
    const min = Math.floor(seg / 60);
    if (min < 60) return min + ' min';
    const h = Math.floor(min / 60);
    if (h < 24) return h + ' h';
    const d = Math.floor(h / 24);
    return d + (d === 1 ? ' dia' : ' dias');
  }

  // Estatisticas da home. As duas fontes de dado ja existiam; o que muda e
  // mostrar o que importa num acervo com varias fontes, em vez de contar
  // generos.
  function _loadHomeStats() {
    cachedFetch('/api/cache-status').then(st => {
      if (!st) return;
      const filmes = document.getElementById('statMovies');
      if (filmes) filmes.textContent = st.movies != null ? st.movies : '—';
      const scan = document.getElementById('statScan');
      if (scan) scan.textContent = tempoDesde(st.last_updated);
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
  // Star Wars 1-6 e afins. Vem da tag <set> do NFO — os filmes continuam
  // cada um na sua pasta e no seu gênero; a coleção é só um agrupamento.
  const COLECAO_PREFIXO = 'colecao:';
  const LISTA_COLECOES = 'colecoes';

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

    cachedFetch('/api/collections').then(cols => {
      if (!cols || cols.length === 0) {
        document.getElementById('heroDesc').textContent = '';
        container.innerHTML = '<div class="empty-state">'
          + '<div class="empty-icon"><svg class="icon-svg"><use href="#i-layers"></use></svg></div>'
          + '<h3>Nenhuma coleção no acervo</h3>'
          + '<p>Coleções vêm da tag <code>&lt;set&gt;</code> do NFO — o tinyMediaManager '
          + 'grava sozinho quando você agrupa um conjunto de filmes lá.</p></div>';
        return;
      }
      document.getElementById('heroDesc').innerHTML =
        '<svg class="icon-svg"><use href="#i-layers"></use></svg> ' + cols.length
        + (cols.length === 1 ? ' coleção' : ' coleções');
      let html = '<div class="genre-section"><div class="colecao-lista">';
      cols.forEach(c => {
        html += '<button class="colecao-item" onclick="abrirColecao(decodeURIComponent(\''
          + enc(c.name) + '\'))">'
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

    cachedFetch('/api/collection?name=' + encodeURIComponent(nome)).then(col => {
      if (!col || !col.movies) {
        container.innerHTML = '<div class="empty-state"><div class="empty-icon">'
          + '<svg class="icon-svg"><use href="#i-error"></use></svg></div>'
          + '<h3>Coleção não encontrada</h3></div>';
        return;
      }
      _heroCapa(col.poster, col.fanart);
      document.getElementById('heroTitle').innerHTML =
        (col.poster ? '' : '<svg class="icon-svg"><use href="#i-layers"></use></svg> ')
        + escHtml(col.name);
      document.getElementById('heroDesc').innerHTML =
        '<svg class="icon-svg"><use href="#i-film"></use></svg> ' + col.movies.length
        + (col.movies.length === 1 ? ' filme' : ' filmes')
        + (col.overview ? '<div class="colecao-sinopse">' + escHtml(col.overview) + '</div>' : '');

      // Ordenados por ano no servidor — é o que põe a saga na ordem certa.
      let html = '<div class="genre-section"><div class="movie-grid">';
      col.movies.forEach(m => {
        // Cartão próprio em vez de renderMovieCardHtml: aqui o item é uma
        // PASTA de filme (clique abre a ficha), não um arquivo de vídeo. E o
        // pôster e o ano já vêm prontos da API, sem regex no nome da pasta.
        const titulo = escHtml((m.title || m.name).replace(/[._]/g, ' '));
        const poster = m.poster ? posterUrl(m.path, m.poster) : null;
        html += '<div class="movie-card" onclick="showMovieInfo(decodeURIComponent(\''
          + enc(m.path) + '\'), event)" title="' + titulo + '">'
          + (poster
              ? '<img class="movie-card-poster" src="' + poster + '" alt="' + titulo
                + '" loading="lazy" onerror="this.style.display=\'none\';'
                + 'this.nextElementSibling.style.display=\'flex\'">'
                + '<div class="movie-card-poster-placeholder" style="display:none">'
                + '<svg class="icon-svg"><use href="#i-film"></use></svg></div>'
              : '<div class="movie-card-poster-placeholder">'
                + '<svg class="icon-svg"><use href="#i-film"></use></svg></div>')
          + '<div class="movie-card-overlay"><div class="movie-card-title">' + titulo + '</div>'
          + '<div class="movie-card-subtitle">' + (m.year ? escHtml(m.year) : 'Filme') + '</div>'
          + '</div></div>';
      });
      container.innerHTML = html + '</div></div>';
    });
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
    // Pasta de filme e vídeo solto na pasta do gênero viram o mesmo cartão na
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
              : 'Adicione filmes nesta pasta do Google Drive para vê-los aqui.'}</p>
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
      html += renderMovieCardHtml(name, filePath, video.Size, video.poster ? posterUrl(data.path, video.poster) : null);
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
      html += renderMovieCardHtml(name, filePath, video.Size, posterSrc);
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
        html += renderMovieCardHtml(name, filePath, video.Size, posterSrc);
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
  function renderMovieCardHtml(name, filePath, size, posterSrc) {
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
    document.getElementById('movieInfoBreadcrumb').style.display = 'block';

    // Build breadcrumb for the overlay
    const bcEl = document.getElementById('movieInfoBreadcrumb');
    const path = folderPath || '';
    const parts = path.split('/').filter(Boolean);
    let cur = window.__LOGICAL_ROOT__ || '/TicianoFlix';
    let html = '<a onclick="loadPath(\'\')"><svg class="icon-svg"><use href="#i-home"></use></svg> Início</a>';
    parts.forEach((p, i) => {
      if (i === 0) return; // pula a raiz do Drive (LOGICAL_ROOT, ex.: "/Mediaflix")
      cur += '/' + p;
      const name = p.replace(/[._]/g, ' ');
      if (i === parts.length - 1) {
        html += ' <span class="sep">›</span> <span>' + escHtml(name) + '</span>';
      } else {
        html += ' <span class="sep">›</span> <a onclick="loadPath(decodeURIComponent(\'' + enc(cur) + '\'))">' + escHtml(name) + '</a>';
      }
    });
    bcEl.innerHTML = html;

    content.innerHTML = '<div class="loading" style="min-height:400px"><div class="spinner"></div><span>Carregando informações...</span></div>';
    bg.style.backgroundImage = 'none';

    cachedFetch('/api/movie-detail?path=' + encodeURIComponent(folderPath)).then(detail => {
      if (!detail) {
        content.innerHTML = '<div class="empty-state"><div class="empty-icon"><svg class="icon-svg"><use href="#i-error"></use></svg></div><h3>Erro ao carregar</h3></div>';
        return;
      }

      // Cache VFS só existe pro Drive: em fonte local a pergunta não se aplica
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

      // Genres
      if (nfo && nfo.genres && nfo.genres.length > 0) {
        nfoHtml += '<div class="movie-genres">';
        nfo.genres.forEach(g => { nfoHtml += '<span class="movie-genre-tag">' + escHtml(g) + '</span>'; });
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

      // Tags
      if (nfo && nfo.tags && nfo.tags.length > 0) {
        nfoHtml += '<div class="movie-tags">';
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
            ${'<button class="btn-watched" onclick="_markAsWatched(decodeURIComponent(\'' + enc(folderPath) + '\'))"><svg class="icon-svg"><use href="#i-check"></use></svg> Já assisti</button>'}
            ${detail.collection
                ? '<button class="btn-colecao" onclick="closeMovieInfo(); abrirColecao(decodeURIComponent(\''
                  + enc(detail.collection.name) + '\'))" title="Ver a coleção inteira">'
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
    document.getElementById('movieInfoBreadcrumb').innerHTML = '';
    document.getElementById('movieInfoBreadcrumb').style.display = 'none';
  }

  function playFromInfo(videoPath, movieName, subtitlePath, resumePosition) {
    closeMovieInfo();
    playMovie(videoPath, movieName, subtitlePath, resumePosition);
  }

  // Close movie info on Escape
  document.addEventListener('keydown', function(e) {
    if (e.key === 'Escape') {
      if (gavetaAberta()) { closeSidebar(); return; }
      const confirmModal = document.getElementById('confirmModal');
      if (confirmModal.classList.contains('active')) {
        closeConfirmModal();
        return;
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

  // ==================== BREADCRUMB ====================
  function renderBreadcrumb(path) {
    const el = document.getElementById('breadcrumb');
    if (!el) return;
    const parts = path ? path.split('/').filter(Boolean) : [];
    let html = '<a onclick="loadPath(\'\')"><svg class="icon-svg"><use href="#i-home"></use></svg> Início</a>';

    // A raiz da fonte ocupa 1 segmento no Drive (LOGICAL_ROOT) e 2 nas fontes
    // locais ("/Local/hd-externo"). O caminho e montado a partir do proprio
    // path — remontar com um prefixo fixo gerava link quebrado fora do Drive.
    const rootLen = isLocalPath(path) ? 2 : 1;
    if (rootLen === 2 && parts.length >= 2) {
      const slug = parts[1];
      html += ' <span class="sep">›</span> <span>'
        + escHtml(_sourceNames[slug] || slug) + '</span>';
    }

    let current = '/' + parts.slice(0, rootLen).join('/');
    parts.slice(rootLen).forEach((part, i, rest) => {
      current += '/' + part;
      const name = part.replace(/[._]/g, ' ');
      if (i === rest.length - 1) {
        html += ' <span class="sep">›</span> <span>' + escHtml(name) + '</span>';
      } else {
        html += ' <span class="sep">›</span> <a onclick="loadPath(decodeURIComponent(\'' + enc(current) + '\'))">' + escHtml(name) + '</a>';
      }
    });
    el.innerHTML = html;
  }

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

  function _markAsWatched(folderPath) {
    _clearProgress(folderPath);
    showToast('✔ Marcado como assistido', 'success');
    // Refresh the movie info to hide resume button and show watched state
    const actionsEl = document.querySelector('.movie-info-actions');
    if (actionsEl) {
      const resumeBtn = actionsEl.querySelector('.btn-resume');
      if (resumeBtn) resumeBtn.remove();
      const watchedBtn = actionsEl.querySelector('.btn-watched');
      if (watchedBtn) watchedBtn.innerHTML = '<svg class="icon-svg"><use href="#i-check-circle"></use></svg> Assistido';
    }
    // Invalidate cache so Continue Watching updates on next visit
    _invalidateCache('/api/continue-watching');
    // If on the home page, remove the movie from the visible Continue Watching grid
    var cwSection = document.getElementById('continueWatchingSection');
    if (cwSection && cwSection.style.display !== 'none') {
      var cards = cwSection.querySelectorAll('.movie-card');
      for (var i = 0; i < cards.length; i++) {
        var onclick = cards[i].getAttribute('onclick') || '';
        if (onclick.indexOf(folderPath) !== -1 || onclick.indexOf(encodeURIComponent(folderPath)) !== -1) {
          cards[i].remove();
          break;
        }
      }
      // Hide the entire section if no cards left
      if (cwSection.querySelectorAll('.movie-card').length === 0) {
        cwSection.style.display = 'none';
      }
    }
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
      if (btn) {
        btn.innerHTML = tocando
          ? '<svg class="icon-svg"><use href="#i-pause"></use></svg>'
          : '<svg class="icon-svg"><use href="#i-play"></use></svg>';
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

  function _showCastingPanel(mostrar) {
    var painel = document.getElementById('castingPanel');
    if (!painel) return;
    painel.classList.toggle('active', !!mostrar);
    if (!mostrar) { _stopCastTicker(); return; }
    var nome = '';
    try { nome = _castSession.getCastDevice().friendlyName || ''; } catch (e) {}
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
  async function _fetchMediaToken(video, extraImages) {
    if (!video || !video.src) return null;
    var baseUrl = window.__HTTP_BASE__ || _getBaseUrl();
    var urlObj = new URL(video.src, _getBaseUrl());
    var mediaPath = urlObj.searchParams.get('path') || '';
    if (!mediaPath) return null;
    var body = { path: mediaPath, subtitle: currentSubtitlePath || '' };
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
      streamPath: urlObj.pathname + urlObj.search,
      tokens: tokens,
    };
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
    // panos, sem precisar de um ticker separado como o Cast usa. So refletimos
    // o estado no botao.
    video.addEventListener('webkitcurrentplaybacktargetiswirelesschanged', function() {
      btn.classList.toggle('active', video.webkitCurrentPlaybackTargetIsWireless);
    });
  }

  async function toggleAirplay() {
    var video = document.getElementById('videoPlayer');
    if (!_airplaySupported(video)) return;

    // Troca o src pra versao assinada antes de abrir o seletor: se o usuario
    // escolher o Roku, ele vai buscar essa URL sozinho, sem cookie. Trocar o
    // src reinicia o buffer, entao guardamos e restauramos a posicao.
    var pos = video.currentTime;
    var tocando = !video.paused;
    var info = await _fetchMediaToken(video, []);
    if (info) {
      video.addEventListener('loadedmetadata', function retomar() {
        video.removeEventListener('loadedmetadata', retomar);
        video.currentTime = pos;
        if (tocando) video.play().catch(function() {});
      });
      video.src = info.midiaBase + info.streamPath + '&t=' + encodeURIComponent(info.tokens.t);
      if (currentSubtitlePath && info.tokens.sub) {
        var track = document.getElementById('subtitleTrack');
        if (track) {
          track.src = info.midiaBase + '/api/subtitle?path=' + encodeURIComponent(currentSubtitlePath)
                    + '&t=' + encodeURIComponent(info.tokens.sub);
        }
      }
    }
    // O seletor nativo do iOS precisa ser chamado enquanto o toque do usuario
    // ainda "conta" como gesto ativo — por isso roda logo em seguida, sem mais
    // nenhuma espera depois do fetch acima.
    video.webkitShowPlaybackTargetPicker();
  }

  async function _sendMediaToCast() {
    if (!_castSession) return;
    var video = document.getElementById('videoPlayer');
    if (!video || !video.src) return;

    var info = await _fetchMediaToken(video, [_castArt.poster, _castArt.fanart].filter(Boolean));
    if (!info) {
      showToast('❌ Não foi possível autorizar o envio para a TV', 'error');
      return;
    }
    var baseUrl = info.baseUrl, castTokens = info.tokens;

    // Construct absolute URL for Chromecast (over HTTP)
    var contentUrl = baseUrl + info.streamPath + '&t=' + encodeURIComponent(castTokens.t);

    // Build media info
    var mediaInfo = new chrome.cast.media.MediaInfo(contentUrl, 'video/mp4');
    mediaInfo.streamType = chrome.cast.media.StreamType.BUFFERED;

    // MovieMediaMetadata no lugar do generico: e o que faz a TV desenhar a
    // ficha do filme (arte, ano, estudio) em vez de uma tela vazia com o titulo.
    var meta = new chrome.cast.media.MovieMediaMetadata();
    var titleEl = document.getElementById('playerMovieName');
    meta.title = titleEl ? titleEl.textContent : 'TicianoFlix';
    if (_castArt.year) meta.releaseDate = String(_castArt.year) + '-01-01';
    if (_castArt.studio) meta.studio = _castArt.studio;
    if (_castArt.plot) meta.subtitle = _castArt.plot;
    else if (_castArt.year) meta.subtitle = String(_castArt.year);

    // As imagens tambem saem por /api/stream: sem o token assinado a TV recebe
    // 401 e fica sem arte.
    var imgs = castTokens.imgs || {};
    var arte = [];
    [_castArt.fanart, _castArt.poster].forEach(function(caminho) {
      if (!caminho || !imgs[caminho]) return;
      arte.push(new chrome.cast.Image(
        baseUrl + '/api/stream?path=' + encodeURIComponent(caminho)
        + '&t=' + encodeURIComponent(imgs[caminho])));
    });
    if (arte.length) meta.images = arte;
    mediaInfo.metadata = meta;
    if (video.duration) mediaInfo.duration = video.duration;

    // Add subtitle track if available
    var currentSubPath = currentSubtitlePath;
    if (currentSubPath) {
      console.log('[Cast] Adding subtitle track:', currentSubPath);
      var subUrl = baseUrl + '/api/subtitle?path=' + encodeURIComponent(currentSubPath)
                 + '&t=' + encodeURIComponent(castTokens.sub || '');
      var track = new chrome.cast.media.Track(1, chrome.cast.media.TrackType.TEXT);
      track.trackContentId = subUrl;
      track.trackContentType = 'text/vtt';
      track.name = 'Português';
      track.language = 'pt';
      track.subtype = chrome.cast.media.TextTrackType.SUBTITLES;
      mediaInfo.tracks = [track];
      // Legenda no espirito da Apple TV: texto branco sobre caixa escura, sem
      // contorno nas letras (contorno e o visual "Classic"). O canto
      // arredondado nao da pra reproduzir — veja o comentario do backgroundColor.
      var estilo = new chrome.cast.media.TextTrackStyle();
      estilo.foregroundColor = '#FFFFFFFF';
      estilo.fontGenericFamily = chrome.cast.media.TextTrackFontGenericFamily.SANS_SERIF;
      estilo.fontStyle = chrome.cast.media.TextTrackFontStyle.NORMAL;
      // 0.8 do tamanho padrao do receiver: a legenda do Cast sai grande demais
      // numa TV vista da distancia normal de sofa.
      estilo.fontScale = 0.8;
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
      mediaInfo.textTrackStyle = estilo;
      console.log('[Cast] Subtitle URL:', subUrl);
    } else {
      console.log('[Cast] No subtitle track available (currentSubtitlePath is null)');
    }

    var request = new chrome.cast.media.LoadRequest(mediaInfo);
    // activeTrackIds vive no LoadRequest, nao no MediaInfo — estava no lugar
    // errado, e por isso a legenda dependia inteiramente do editTracksInfo
    // depois do load.
    if (currentSubPath) {
      request.activeTrackIds = [1];
    }
    // Start from current position if the video has played
    if (video.currentTime > 0) {
      request.currentTime = video.currentTime;
    }

    _castSession.loadMedia(request)
      .then(function() {
        console.log('[Cast] Media loaded on Chromecast');
        showToast('📡 Transmitindo para Chromecast', 'info');
        // Pause local video while casting
        video.pause();
        _showCastingPanel(true);
        // Force enable subtitle track after load (some receivers ignore activeTrackIds).
        // Retry a cada 2s até ~30s: o receiver só associa o track depois que o vídeo
        // carregou/bufferizou (stream via rclone→Drive demora a começar).
        if (currentSubPath) {
          _forceCastSubtitles(1, 0);
        }
      })
      .catch(function(err) {
        console.warn('[Cast] Load media error:', err);
        showToast('❌ Erro ao transmitir', 'error');
      });
  }

  function clearBufferTimer() {
    // No-op: _waitForBuffer was removed, but keep for cleanup compatibility
  }

  // Tenta habilitar a legenda no receiver até ~30s (a cada 2s).
  // O receiver do Chromecast só associa o track de texto depois que o vídeo
  // está carregado — com stream via rclone→Drive isso pode levar vários segundos.
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
  // O app de Android TV injeta window.TicianoFlixTV. Quando ele existe, quem
  // toca o filme e o ExoPlayer nativo e nao o <video> desta pagina: a WebView
  // do Android nao e confiavel com MKV e faixas AC3/DTS, que e o grosso do
  // acervo, e o ExoPlayer decodifica por hardware.
  //
  // A URL vai assinada pelo mesmo /api/cast-token do Chromecast, entao o player
  // nativo busca os bytes sozinho, sem depender do cookie de sessao da pagina.
  function _tvNativoDisponivel() {
    return !!(window.TicianoFlixTV && typeof window.TicianoFlixTV.play === 'function');
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
    window.TicianoFlixTV.play(JSON.stringify({
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

  function playMovie(filePath, movieName, subtitlePath, resumePosition) {
    const overlay = document.getElementById('playerOverlay');
    const video = document.getElementById('videoPlayer');
    const loading = document.getElementById('playerLoading');
    const movieTitle = document.getElementById('playerMovieName');

    currentVideoPath = filePath;
    currentSubtitlePath = subtitlePath || null;
    // Derive folder path from video file path
    _currentPlayFolder = filePath.substring(0, filePath.lastIndexOf('/'));

    // Na TV quem toca e o player nativo. Fica depois de _currentPlayFolder de
    // proposito: e dele que _saveProgress depende quando o app devolve a
    // posicao no fim do filme.
    if (_tvNativoDisponivel()) {
      _tvTocarNativo(filePath, movieName, subtitlePath, resumePosition);
      return;
    }

    movieTitle.textContent = movieName.replace(/\.[^.]+$/, '').replace(/[._]/g, ' ');
    document.getElementById('playerFileSize').textContent = '';

    // Proactively load Cast SDK (non-blocking)
    _loadCastSdk();
    // AirPlay nao precisa de SDK — e nativo do <video> em navegadores WebKit.
    _setupAirplay(video);

    // Limpa qualquer timer de buffer pendente
    clearBufferTimer();

    // Download de fundo só faz sentido pro Drive: ele existe para forçar o
    // cache VFS do rclone. Num arquivo local isso leria o filme inteiro do
    // disco à toa, disputando com a própria reprodução.
    const _local = isLocalPath(filePath);
    if (!_local) _startBgDownload(filePath);

    // A arte guardada e da ficha aberta. Se o video vier de outro caminho
    // (lista de pasta, busca), ela nao corresponde — melhor nao mandar nada.
    if (_castArt.folder !== filePath.substring(0, filePath.lastIndexOf('/'))) {
      _castArt = { folder: null, poster: null, fanart: null, year: null, studio: null, plot: null };
    }

    // Show loading state
    video.style.display = 'none';
    loading.style.display = 'flex';
    document.getElementById('playerError').style.display = 'none';
    loading.querySelector('span').textContent = _local
      ? 'Abrindo o vídeo...'
      : 'Preparando vídeo do Google Drive...';

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
          : 'O servidor demorou a responder. Verifique sua conexão com o Google Drive.');
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
      m.editTracksInfo(new chrome.cast.media.EditTracksInfoRequest(ativa ? [] : [1]),
        function() { btn.classList.toggle('active', !ativa); },
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
    // Stop background download
    _stopBgDownload();
    loading.style.display = 'none';
    errorEl.style.display = 'none';
    overlay.classList.remove('active');
    document.body.style.overflow = '';
    _currentPlayFolder = null;
    _progressSaveTimer = null;
  }

  let subtitlesEnabled = true;
  let subtitleSizeIndex = 2;
  // Tamanho proporcional à altura do player (fração da altura visível).
  // Ex.: 0.05 = 5% da altura → fullscreen grande, janela pequena.
  const subtitleSizes = [
    { ratio: 0.035, label: 'Peq' },
    { ratio: 0.045, label: 'Méd' },
    { ratio: 0.06,  label: 'Gde' },
    { ratio: 0.08,  label: 'Ext' },
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

  function cycleSubtitleSize() {
    subtitleSizeIndex = (subtitleSizeIndex + 1) % subtitleSizes.length;
    const size = subtitleSizes[subtitleSizeIndex];
    document.getElementById('subtitleSizeLabel').textContent = size.label;
    applySubtitleSize();
  }

  let subtitleColorIndex = 0;
  const subtitleColors = [
    { color: '#ffd700', label: 'Amarelo' },
    { color: '#ffffff', label: 'Branco' },
  ];
  function cycleSubtitleColor() {
    subtitleColorIndex = (subtitleColorIndex + 1) % subtitleColors.length;
    const c = subtitleColors[subtitleColorIndex];
    document.getElementById('subtitleColorLabel').textContent = c.label;
    document.getElementById('subtitleColorIcon').style.background = c.color;
    document.querySelector('.player-overlay').style.setProperty('--sub-color', c.color);
  }

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
    if (!m || !m.classList.contains('ativo')) return;
    if (!m.contains(e.target) && !e.target.closest('.ctrl-more')) fecharPlayerMore();
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
  }

  function closeSettingsModal() {
    document.getElementById('settingsModal').classList.remove('active');
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

  // ==================== FONTES ====================
  // Prefixo logico das fontes locais (espelha LOCAL_ROOT no servidor).
  const LOCAL_ROOT = '/Local';

  function isLocalPath(path) {
    const p = '/' + String(path || '').replace(/^\/+/, '');
    return p === LOCAL_ROOT || p.indexOf(LOCAL_ROOT + '/') === 0;
  }

  function openSourcesModal() {
    document.getElementById('sourcesModal').classList.add('active');
    _loadSources();
  }

  function closeSourcesModal() {
    document.getElementById('sourcesModal').classList.remove('active');
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
      const isDrive = src.kind === 'drive';
      const offline = src.online === false;
      html += '<div class="user-row src-row">'
        + '<div class="src-main">'
        + '<div class="user-name">' + sourceIcon(src.kind) + ' ' + escHtml(src.name)
        + '<span class="user-tag ' + (isDrive ? 'drive' : 'local') + '">' + (isDrive ? 'nuvem' : 'local') + '</span>'
        + (offline ? '<span class="user-tag offline">desconectada</span>' : '')
        + '</div>'
        + (src.root ? '<div class="src-path">' + escHtml(src.root) + '</div>' : '')
        + '<div class="src-counts">' + src.genres + (src.genres === 1 ? ' gênero · ' : ' gêneros · ')
        + src.movies + (src.movies === 1 ? ' filme' : ' filmes') + '</div>'
        + '</div>'
        + '<button class="user-btn" title="Escanear só esta fonte" onclick="scanSource(decodeURIComponent(\'' + enc(src.id) + '\'))">'
        + '<svg class="icon-svg"><use href="#i-refresh"></use></svg></button>'
        + (isDrive ? '' :
            '<button class="user-btn danger" id="srcDel-' + enc(src.id) + '" '
            + 'title="Tirar do acervo (os arquivos no disco não são apagados)" '
            + 'onclick="removeSource(decodeURIComponent(\'' + enc(src.id) + '\'), decodeURIComponent(\'' + enc(src.name) + '\'))">'
            + '<svg class="icon-svg"><use href="#i-trash"></use></svg></button>')
        + '</div>';
    });

    if (candidates.length > 0) {
      html += '<div class="user-section-title">Detectadas neste computador</div>'
        + '<div class="src-hint">As marcadas com <svg class="icon-svg"><use href="#i-check"></use></svg> '
        + 'já têm uma pasta <b>TicianoFlix</b> dentro e entram na hora.</div>'
        + '<div class="src-detected">';
      candidates.forEach(c => {
        const icon = c.kind === 'volume' ? '#i-hard-drive' : '#i-folder';
        // Sem a pasta TicianoFlix dentro, o cadastro seria recusado — melhor
        // deixar isso visivel antes do clique.
        const dica = c.pronto ? c.path : c.path + ' — sem uma pasta TicianoFlix dentro';
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

    html += '<div class="user-section-title">Adicionar uma pasta</div>'
      + '<div class="src-hint">A pasta precisa ter uma pasta <b>Mediaflix</b> dentro '
      + '(ou até dois níveis abaixo), organizada como no Drive:<br>'
      + '<code>Mediaflix / Gênero / Filme (ano) / filme.mkv</code> — com o '
      + '<code>.nfo</code> e o <code>poster.jpg</code> junto do vídeo.</div>'
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
        const label = document.getElementById('logoutLabel');
        if (label) label.textContent = 'Sair (' + _me.username + ')';
        if (_me.role === 'admin') {
          ['settingsUsers', 'settingsSources', 'settingsScrape', 'settingsBranding'].forEach(id => {
            const el = document.getElementById(id);
            if (el) el.style.display = '';
          });
        }
      }
    } catch (e) {}
  }

  function openUsersModal() {
    document.getElementById('usersModal').classList.add('active');
    _loadUsers();
  }

  function closeUsersModal() {
    document.getElementById('usersModal').classList.remove('active');
  }

  document.getElementById('usersModal').addEventListener('click', function (e) {
    if (e.target === this) closeUsersModal();
  });

  function _usersMsg(text, kind) {
    const el = document.getElementById('usersMsg');
    if (el) { el.textContent = text; el.className = 'user-msg ' + kind; }
  }

  async function _loadUsers() {
    const box = document.getElementById('usersBox');
    box.innerHTML = '<div class="loading" style="min-height:100px"><div class="spinner"></div><span>Carregando contas...</span></div>';
    try {
      const res = await fetch('/api/users');
      const data = await res.json();
      if (!res.ok || data.status !== 'ok') {
        box.innerHTML = '<div class="empty-state"><div class="empty-icon"><svg class="icon-svg"><use href="#i-lock"></use></svg></div><h3>' + escHtml(data.error || 'Sem acesso') + '</h3></div>';
        return;
      }
      _renderUsers(data.users || [], data.me || '');
    } catch (e) {
      box.innerHTML = '<div class="empty-state"><div class="empty-icon"><svg class="icon-svg"><use href="#i-error"></use></svg></div><h3>Erro ao carregar contas</h3></div>';
    }
  }

  function _renderUsers(users, me) {
    let html = '<div class="user-section-title">Quem tem acesso (' + users.length + ')</div>';
    users.forEach(u => {
      const isMe = u.username === me;
      const isAdmin = u.role === 'admin';
      const n = escHtml(u.username);
      html += '<div class="user-row">'
        + '<span class="user-name">' + n + '</span>'
        + (isAdmin ? '<span class="user-tag admin">admin</span>' : '')
        + (isMe ? '<span class="user-tag me">você</span>' : '')
        + '<button class="user-btn" title="' + (isAdmin ? 'Tornar usuário comum' : 'Tornar administrador') + '" '
        + 'onclick="setUserRole(\'' + n + '\', \'' + (isAdmin ? 'user' : 'admin') + '\')">'
        + (isAdmin ? '<svg class="icon-svg"><use href="#i-user"></use></svg>' : '<svg class="icon-svg"><use href="#i-crown"></use></svg>') + '</button>'
        + '<button class="user-btn" title="Redefinir senha" onclick="togglePwForm(\'' + n + '\')"><svg class="icon-svg"><use href="#i-key"></use></svg></button>'
        + (isMe ? '' : '<button class="user-btn danger" title="Remover conta" onclick="removeUser(\'' + n + '\')"><svg class="icon-svg"><use href="#i-trash"></use></svg></button>')
        + '</div>'
        + '<div class="user-form" id="pw-' + n + '" style="display:none">'
        + '<input type="password" id="pwval-' + n + '" placeholder="Nova senha de ' + n + '" autocomplete="new-password">'
        + '<button class="rclone-action-btn primary" style="flex:0 0 auto;min-width:100px" onclick="setUserPassword(\'' + n + '\')">Salvar</button>'
        + '</div>';
    });

    html += '<div class="user-section-title">Adicionar conta</div>'
      + '<div class="user-form">'
      + '<input type="text" id="newUser" placeholder="usuário" autocapitalize="none" spellcheck="false" autocomplete="off">'
      + '<input type="password" id="newPass" placeholder="senha (mín. 8)" autocomplete="new-password">'
      + '<label><input type="checkbox" id="newAdmin"> administrador</label>'
      + '<button class="rclone-action-btn primary" style="flex:0 0 auto;min-width:110px" onclick="addUser()">Adicionar</button>'
      + '</div>'
      + '<div class="rclone-help">Não existe auto-cadastro: só quem aparece nesta lista consegue entrar. '
      + 'Remover uma conta derruba as sessões dela na hora.</div>'
      + '<div id="usersMsg"></div>';

    document.getElementById('usersBox').innerHTML = html;
  }

  function togglePwForm(username) {
    const el = document.getElementById('pw-' + username);
    if (el) el.style.display = el.style.display === 'none' ? 'flex' : 'none';
  }

  async function _usersPost(url, body) {
    try {
      const res = await fetch(url, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body)
      });
      const data = await res.json().catch(() => ({}));
      if (res.ok && data.status === 'ok') return data;
      _usersMsg(data.error || 'Não foi possível concluir.', 'err');
    } catch (e) {
      _usersMsg('Falha de conexão com o servidor.', 'err');
    }
    return null;
  }

  async function addUser() {
    const username = (document.getElementById('newUser').value || '').trim().toLowerCase();
    const password = document.getElementById('newPass').value || '';
    const role = document.getElementById('newAdmin').checked ? 'admin' : 'user';
    if (!username || !password) { _usersMsg('Preencha usuário e senha.', 'err'); return; }
    const data = await _usersPost('/api/users/add', { username, password, role });
    if (data) { _renderUsers(data.users, _me ? _me.username : ''); _usersMsg('Conta "' + username + '" criada.', 'ok'); }
  }

  async function removeUser(username) {
    const data = await _usersPost('/api/users/remove', { username });
    if (data) { _renderUsers(data.users, _me ? _me.username : ''); _usersMsg('Conta "' + username + '" removida.', 'ok'); }
  }

  async function setUserRole(username, role) {
    const data = await _usersPost('/api/users/role', { username, role });
    if (data) {
      _renderUsers(data.users, _me ? _me.username : '');
      _usersMsg('"' + username + '" agora é ' + (role === 'admin' ? 'administrador' : 'usuário comum') + '.', 'ok');
    }
  }

  async function setUserPassword(username) {
    const el = document.getElementById('pwval-' + username);
    const password = el ? el.value : '';
    if (!password) { _usersMsg('Digite a nova senha.', 'err'); return; }
    const data = await _usersPost('/api/users/password', { username, password });
    if (data) {
      togglePwForm(username);
      if (el) el.value = '';
      _usersMsg('Senha de "' + username + '" redefinida. As sessões dela foram encerradas.', 'ok');
    }
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
    window.location.replace('/login');
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
  // Só filmes do Drive baixados pro cache VFS. Filme em fonte local está no
  // disco por natureza — não foi "baixado", e misturar os dois esvaziava o
  // sentido da seção. O filter limpa o que versões anteriores gravaram.
  const _cachedSet = new Set(
    JSON.parse(localStorage.getItem('ticianoflix_cached') || '[]')
      .filter(p => !isLocalPath(p))
  );
  function _isCached(folderPath) {
    return _cachedSet.has(folderPath);
  }
  function _markCached(folderPath) {
    if (isLocalPath(folderPath)) return;
    if (!_cachedSet.has(folderPath)) {
      _cachedSet.add(folderPath);
      localStorage.setItem('ticianoflix_cached', JSON.stringify([..._cachedSet]));
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
        // aqui a pergunta é outra: foi baixado do Drive?
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
        localStorage.setItem('ticianoflix_cached', JSON.stringify([..._cachedSet]));
      }
    } catch(_) {}
  }

  function clearCache() {
    localStorage.removeItem('ticianoflix_cached');
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
    // Scan all movies to check which ones are fully cached on the server
    try {
      const genresRes = await fetch('/api/genres');
      const genresData = await genresRes.json();
      if (!genresData || !genresData.folders) return;

      const allMovies = [];
      for (const genre of genresData.folders) {
        // O path completo do genero vem do servidor — ele pode estar em
        // qualquer fonte, nao so no Drive.
        const genrePath = '/' + genre.Path;
        const listRes = await fetch('/api/list?path=' + encodeURIComponent(genrePath));
        const listData = await listRes.json();
        if (listData && listData.folders) {
          listData.folders.forEach(f => {
            allMovies.push(genrePath + '/' + f.Name);
          });
        }
      }

      for (const moviePath of allMovies) {
        if (isLocalPath(moviePath) || _cachedSet.has(moviePath)) continue;
        const detail = await apiFetch('/api/movie-detail?path=' + encodeURIComponent(moviePath));
        if (!detail || !detail.video) continue;
        const video = detail.video;
        if (!video || !video.Name) continue;
        const filePath = moviePath + '/' + video.Name;
        const checkRes = await fetch('/api/check-cached?path=' + encodeURIComponent(filePath));
        const checkData = await checkRes.json();
        if (checkData.cached) {
          _markCached(moviePath);
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
        localStorage.setItem('ticianoflix_cached', JSON.stringify([..._cachedSet]));
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
  }
  function closeBackupModal() {
    document.getElementById('backupModal').classList.remove('active');
  }

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

  // ==================== METADADOS (TMDB) ====================
  // Editor que substitui o tinyMediaManager: busca no TMDB, mostra os
  // candidatos, e so grava quando uma pessoa escolhe qual e o filme certo —
  // nunca aplica o primeiro resultado sozinho. Ver ticianoflix/scraper.py.
  function openScrapeModal() {
    document.getElementById('scrapeModal').classList.add('active');
    document.body.style.overflow = 'hidden';
    _loadScrapeStatus();
  }
  function closeScrapeModal() {
    document.getElementById('scrapeModal').classList.remove('active');
    document.body.style.overflow = '';
  }
  document.getElementById('scrapeModal').addEventListener('click', function(e) {
    if (e.target === this) closeScrapeModal();
  });

  async function _loadScrapeStatus() {
    const box = document.getElementById('scrapeBox');
    try {
      const res = await fetch('/api/scrape/status');
      const st = await res.json();
      if (!st.configurado) {
        _renderScrapeKeyForm();
      } else {
        _loadScrapePendentes();
      }
    } catch (e) {
      box.innerHTML = '<div class="user-msg err">Falha ao carregar.</div>';
    }
  }

  function _renderScrapeKeyForm(msgTexto, msgTipo) {
    const box = document.getElementById('scrapeBox');
    box.innerHTML =
      '<div class="rclone-help">Sinopse, elenco, nota e pôster vêm do TMDB — a mesma '
      + 'base que Kodi, Jellyfin e o tinyMediaManager usam. Crie uma conta gratuita em '
      + 'themoviedb.org e gere uma "API Key (v3 auth)" em Configurações › API. Sem chave, '
      + 'o app segue igual, só com o nome da pasta.</div>'
      + '<div class="user-form" style="flex-direction:column;align-items:stretch">'
      + '<input type="password" id="scrapeKeyInput" placeholder="Cole a API Key aqui" autocomplete="off">'
      + '<button class="rclone-action-btn primary" onclick="_scrapeSalvarChave()">Salvar chave</button>'
      + '</div>'
      + '<div id="scrapeMsg" class="user-msg' + (msgTipo ? ' ' + msgTipo : '') + '">' + (msgTexto || '') + '</div>';
  }

  async function _scrapeSalvarChave() {
    const chave = (document.getElementById('scrapeKeyInput').value || '').trim();
    if (!chave) return;
    try {
      const res = await fetch('/api/scrape/key/set', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ api_key: chave })
      });
      const data = await res.json().catch(() => ({}));
      if (res.ok && data.status === 'ok') {
        _loadScrapePendentes();
      } else {
        _renderScrapeKeyForm(data.error || 'Não foi possível salvar.', 'err');
      }
    } catch (e) {
      _renderScrapeKeyForm('Falha de conexão com o servidor.', 'err');
    }
  }

  async function _loadScrapePendentes() {
    const box = document.getElementById('scrapeBox');
    box.innerHTML = '<div class="loading" style="min-height:100px"><div class="spinner"></div><span>Carregando...</span></div>';
    try {
      const res = await fetch('/api/scrape/pendentes');
      const data = await res.json();
      _renderScrapePendentes(data.pendentes || [], data.total || 0);
    } catch (e) {
      box.innerHTML = '<div class="user-msg err">Falha ao carregar.</div>';
    }
  }

  function _renderScrapePendentes(lista, total) {
    const box = document.getElementById('scrapeBox');
    if (lista.length === 0) {
      box.innerHTML =
        '<div class="rclone-help">Nenhum filme sem metadado — tudo já tem NFO ou já foi '
        + 'preenchido pelo TMDB.</div>'
        + '<button class="user-btn" onclick="_renderScrapeKeyForm()">Trocar chave do TMDB</button>';
      return;
    }
    let html = '<div class="rclone-help">' + total + (total === 1 ? ' filme sem metadado.' : ' filmes sem metadado.')
      + (total > lista.length ? ' Mostrando os primeiros ' + lista.length + '.' : '') + '</div>';
    for (const item of lista) {
      html += '<div class="user-row">'
        + '<span class="user-name">' + escHtml(item.name) + '</span>'
        + '<button class="user-btn" onclick="_scrapeAbrirBusca(\'' + enc(item.path) + '\', \'' + enc(item.name) + '\')">Buscar</button>'
        + '</div>';
    }
    box.innerHTML = html;
  }

  // Tira o "(2020)" do fim do nome da pasta pro campo de busca vir limpo —
  // mesma convencao que scraper.py usa do lado do servidor.
  function _scrapeTituloLimpo(nome) {
    return nome.replace(/\s*\(\d{4}\)\s*$/, '').trim();
  }

  function _scrapeAbrirBusca(pathEnc, nomeEnc) {
    const path = decodeURIComponent(pathEnc);
    const nome = decodeURIComponent(nomeEnc);
    const box = document.getElementById('scrapeBox');
    box.innerHTML =
      '<button class="user-btn" onclick="_loadScrapePendentes()">← Voltar</button>'
      + '<div class="user-form" style="margin-top:10px">'
      + '<input type="text" id="scrapeQuery" value="' + escHtml(_scrapeTituloLimpo(nome)) + '" style="flex:1 1 auto">'
      + '<button class="rclone-action-btn primary" onclick="_scrapeBuscar(\'' + pathEnc + '\')">Buscar</button>'
      + '</div>'
      + '<div id="scrapeResultados" style="margin-top:12px"></div>';
    _scrapeBuscar(pathEnc);
  }

  async function _scrapeBuscar(pathEnc) {
    const path = decodeURIComponent(pathEnc);
    const q = (document.getElementById('scrapeQuery').value || '').trim();
    const area = document.getElementById('scrapeResultados');
    area.innerHTML = '<div class="loading" style="min-height:80px"><div class="spinner"></div><span>Buscando no TMDB...</span></div>';
    try {
      const url = '/api/scrape/search?path=' + encodeURIComponent(path) + (q ? '&q=' + encodeURIComponent(q) : '');
      const res = await fetch(url);
      const data = await res.json();
      if (data.erro) {
        area.innerHTML = '<div class="user-msg err">' + escHtml(data.erro) + '</div>';
        return;
      }
      const candidatos = data.candidatos || [];
      if (candidatos.length === 0) {
        area.innerHTML = '<div class="user-msg">Nenhum resultado. Tente ajustar o texto da busca.</div>';
        return;
      }
      area.innerHTML = candidatos.map(c =>
        '<div class="user-row" style="align-items:flex-start">'
        + (c.poster
            ? '<img src="' + c.poster + '" alt="" style="width:44px;height:64px;object-fit:cover;'
              + 'border-radius:4px;flex:0 0 auto" onerror="this.remove()">'
            : '')
        + '<div class="src-main">'
        + '<div class="user-name">' + escHtml(c.titulo) + (c.ano ? ' <span style="color:var(--text3);font-weight:400">(' + c.ano + ')</span>' : '') + '</div>'
        + '<div class="src-hint" style="margin:2px 0 0">' + escHtml((c.sinopse || '').slice(0, 140)) + (c.sinopse && c.sinopse.length > 140 ? '…' : '') + '</div>'
        + '</div>'
        + '<button class="user-btn" style="flex:0 0 auto" onclick="_scrapeAplicar(\'' + pathEnc + '\', ' + c.id + ')">Usar este</button>'
        + '</div>'
      ).join('');
    } catch (e) {
      area.innerHTML = '<div class="user-msg err">Falha de conexão com o servidor.</div>';
    }
  }

  async function _scrapeAplicar(pathEnc, tmdbId) {
    const path = decodeURIComponent(pathEnc);
    try {
      const res = await fetch('/api/scrape/apply', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ path: path, tmdb_id: tmdbId })
      });
      const data = await res.json().catch(() => ({}));
      if (res.ok && data.status === 'ok') {
        showToast('Metadados aplicados.', 'success');
        _loadScrapePendentes();
      } else {
        showToast(data.error || 'Não foi possível aplicar.', 'error');
      }
    } catch (e) {
      showToast('Falha de conexão com o servidor.', 'error');
    }
  }

  // ==================== APARENCIA (marca) ====================
  // Nome de exibicao e cor sao a unica coisa que muda por instalacao — onde
  // os dados moram (cache, banco, nome do servico) nunca depende disto. Ver
  // ticianoflix/branding.py.
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
        + '<label style="font-size:12px;color:var(--text3)">Nome</label>'
        + '<input type="text" id="brandNome" maxlength="40" value="' + escHtml(marca.nome) + '" '
        + 'placeholder="Ex.: Família Corral">'
        + '<label style="font-size:12px;color:var(--text3);margin-top:4px">Cor</label>'
        + '<div style="display:flex;gap:8px;align-items:center">'
        + '<input type="color" id="brandCorPicker" value="' + marca.cor + '" '
        + 'style="width:44px;height:36px;padding:2px;border-radius:var(--radius);'
        + 'border:1px solid rgba(255,255,255,0.14);background:transparent;cursor:pointer">'
        + '<input type="text" id="brandCorTexto" value="' + marca.cor + '" maxlength="7" '
        + 'style="flex:1" placeholder="#e50914">'
        + '</div>'
        + '</div>'
        + '<div class="rclone-help">O nome e a cor aparecem na tela de login, no menu, no '
        + 'ícone do app instalado no celular e no manifesto — sem mexer em onde o acervo, '
        + 'as contas e o progresso ficam guardados.</div>'
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
    const nome = (document.getElementById('brandNome').value || '').trim();
    const cor = (document.getElementById('brandCorTexto').value || '').trim();
    const msg = document.getElementById('brandingMsg');
    const mostrar = (texto, tipo) => { msg.textContent = texto; msg.className = 'user-msg ' + tipo; };
    if (!nome) { mostrar('Escolha um nome.', 'err'); return; }
    if (!/^#[0-9a-fA-F]{6}$/.test(cor)) { mostrar('Cor precisa ser hexadecimal, ex: #e50914.', 'err'); return; }
    try {
      const res = await fetch('/api/branding/set', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ nome, cor })
      });
      const data = await res.json().catch(() => ({}));
      if (res.ok && data.status === 'ok') {
        mostrar('Salvo! Atualizando...', 'ok');
        // Recarrega em vez de repintar na hora: o nome novo tem que sair do
        // proprio HTML que o servidor gera (titulo, topbar, sidebar, login),
        // e nao so do CSS — mais simples e mais confiavel que sincronizar
        // cada um desses pontos manualmente por aqui.
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
      const res = await fetch('/api/rclone/status');
      const s = await res.json();
      _renderRcloneStatus(box, s);
    } catch(e) {
      box.innerHTML = '<div class="empty-state"><div class="empty-icon"><svg class="icon-svg"><use href="#i-error"></use></svg></div><h3>Erro ao verificar status</h3></div>';
    }
  }

  function _rcloneBadge(ok, textOk, textBad) {
    return ok
      ? '<span class="rclone-badge ok"><svg class="icon-svg"><use href="#i-check"></use></svg> ' + textOk + '</span>'
      : '<span class="rclone-badge bad"><svg class="icon-svg"><use href="#i-close"></use></svg> ' + textBad + '</span>';
  }

  function _renderAcessoDrive(a) {
    if (!a) return '';
    var rotulo = { ok: 'mínimo', atencao: 'mais largo que o necessário',
                   risco: 'Drive inteiro', desconhecido: '?' }[a.nivel] || '?';
    var html = '<div class="rclone-row"><span class="rclone-label">Acesso ao Google Drive</span>'
      + '<span class="rclone-badge ' + (a.nivel === 'ok' ? 'ok' : 'bad') + '">'
      + '<svg class="icon-svg"><use href="#i-' + (a.nivel === 'ok' ? 'check' : 'alert') + '"></use></svg> '
      + escHtml(rotulo) + '</span></div>';

    if (a.nivel === 'ok') {
      if (a.backup_remote && !a.backup_client_proprio) {
        html += '<div class="rclone-help"><svg class="icon-svg"><use href="#i-bulb"></use></svg> '
          + 'O remote de backup usa o client_id compartilhado do rclone, que o Google '
          + 'aposenta durante 2026. Só afeta backup e restauração.</div>';
      }
      return html;
    }
    if (a.nivel === 'desconhecido') return html;

    // Ainda não protegido: explica o risco e dá o comando exato.
    html += '<div class="rclone-warn rclone-warn-' + a.nivel + '">'
      + '<div class="rclone-warn-head"><svg class="icon-svg"><use href="#i-alert"></use></svg> '
      + escHtml(a.resumo) + '</div>'
      + '<p>O TicianoFlix só precisa <b>ler</b> a pasta <b>Mediaflix</b>. '
      + 'Um script reduz o acesso a exatamente isso — seus outros arquivos do Drive '
      + 'ficam fora de alcance.</p>'
      + '<p class="rclone-warn-cmd">No terminal, dentro da pasta do Mediaflix:'
      + '<code>' + escHtml(a.comando) + '</code></p>'
      + '<p class="rclone-warn-foot">Ele abre o navegador para você reautorizar — '
      + 'é o Google que aplica o limite, não dá para fazer isso daqui. '
      + 'Depois clique em <b>Atualizar status</b>.</p>'
      + '</div>';
    return html;
  }

  function _renderRcloneStatus(box, s) {
    let html = '';
    html += '<div class="rclone-row"><span class="rclone-label">rclone instalado</span>'
      + (s.installed ? _rcloneBadge(true, s.version || 'ok', '') : _rcloneBadge(false, '', 'não encontrado')) + '</div>';
    html += '<div class="rclone-row"><span class="rclone-label">Remote gdrive:</span>'
      + _rcloneBadge(s.remote_configured, 'configurado', 'não configurado') + '</div>';
    if (s.remote_configured) {
      html += '<div class="rclone-row"><span class="rclone-label">Conexão com o Drive</span>'
        + (s.remote_ok ? _rcloneBadge(true, 'ok', '') : _rcloneBadge(false, '', s.remote_error || 'falhou')) + '</div>';
    }
    if (s.remote_configured) html += _renderAcessoDrive(s.acesso);
    html += '<div class="rclone-row"><span class="rclone-label">Streaming (serve)</span>'
      + _rcloneBadge(s.serve_running, 'ativo :18082', 'parado') + '</div>';
    html += '<div class="rclone-row"><span class="rclone-label">Web UI de configuração</span>'
      + _rcloneBadge(s.webgui.running, 'ativa :' + s.webgui.port, 'fechada') + '</div>';

    html += '<div class="rclone-actions">';
    if (!s.installed) {
      html += '<div class="rclone-help">Instale o rclone e reinicie o TicianoFlix.<br>'
        + '<b>Linux:</b> <code>sudo pacman -S rclone</code> ou <code>sudo apt install rclone</code><br>'
        + '<b>macOS:</b> <code>brew install rclone</code><br>'
        + '<b>Windows:</b> <code>winget install Rclone.Rclone</code><br>'
        + 'Ou baixe em <a href="https://rclone.org/downloads/" target="_blank" rel="noopener">rclone.org/downloads</a></div>';
    } else {
      if (!s.remote_configured) {
        html += '<button class="rclone-action-btn primary" onclick="rcloneStartWebgui()"><svg class="icon-svg"><use href="#i-gear"></use></svg> Configurar rclone</button>';
      } else {
        html += '<button class="rclone-action-btn" onclick="rcloneStartWebgui()"><svg class="icon-svg"><use href="#i-gear"></use></svg> Abrir configurador</button>';
      }
      if (!s.serve_running) {
        html += '<button class="rclone-action-btn primary" onclick="rcloneRestartServe()"><svg class="icon-svg"><use href="#i-refresh"></use></svg> Reiniciar streaming</button>';
      }
      if (s.webgui.running) {
        html += '<button class="rclone-action-btn" onclick="rcloneStopWebgui()"><svg class="icon-svg"><use href="#i-stop"></use></svg> Fechar web UI</button>';
      }
    }
    html += '<button class="rclone-action-btn" onclick="_loadRcloneStatus()"><svg class="icon-svg"><use href="#i-refresh"></use></svg> Atualizar status</button>';
    html += '</div>';

    if (s.webgui.running) {
      html += '<div class="rclone-creds">Web UI aberta — acessível apenas neste computador:<br>'
        + 'URL: <a href="' + escHtml(s.webgui.url) + '" target="_blank" rel="noopener">' + escHtml(s.webgui.url) + '</a><br>'
        + 'Sem login: a interface escuta só em 127.0.0.1.</div>';
    }

    if (s.installed && !s.remote_configured) {
      html += '<div class="rclone-help"><svg class="icon-svg"><use href="#i-bulb"></use></svg> No configurador: crie um remote chamado <b>gdrive</b> '
        + '(tipo <b>Google Drive</b>, escopo <b>drive.readonly</b>) seguindo o assistente. '
        + 'Depois volte aqui e clique em <b><svg class="icon-svg"><use href="#i-refresh"></use></svg> Reiniciar streaming</b>.</div>';
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
          + '<svg class="icon-svg"><use href="#i-bulb"></use></svg> Crie o remote <b>gdrive</b> (tipo Google Drive, escopo drive ou drive.file). Ao terminar, feche esta web UI e clique em <b><svg class="icon-svg"><use href="#i-refresh"></use></svg> Reiniciar streaming</b>.</div>'
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
    const formData = new FormData();
    formData.append('backup', file);
    try {
      const res = await fetch('/api/restore', { method: 'POST', body: formData });
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

  async function restoreFromDrive() {
    closeBackupModal();
    showToast('☁️ Baixando backup do Google Drive...', '');
    try {
      const res = await fetch('/api/restore/drive', { method: 'POST' });
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
      a.download = 'ticianoflix-backup-' + new Date().toISOString().slice(0,10) + '.zip';
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
      showToast('📦 Backup baixado!', 'success');
    } catch(e) {
      showToast('Erro no backup: ' + e.message, 'error');
    }
  }

  async function backupToDrive() {
    try {
      showToast('☁️ Enviando backup para o Google Drive...', '');
      const res = await fetch('/api/backup/drive', { method: 'POST' });
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
            ptext.textContent = `${srcPrefix}${s.genre_current}: ${s.movie_index} filmes (gênero ${s.genre_index}/${s.genre_total})`;
          } else {
            ptext.textContent = `${srcPrefix}Gênero ${s.genre_index}/${s.genre_total}`;
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
          showToast('Erro ao escanear. Confira o Drive e as fontes locais.', 'error');
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
  setInterval(updateCacheUsage, 30000);

  // Quem esta logado: mostra o nome no botao Sair e revela "Contas" para admin.
  _loadMe();
