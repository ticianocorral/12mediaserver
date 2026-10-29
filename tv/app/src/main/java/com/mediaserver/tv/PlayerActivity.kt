package com.mediaserver.tv

import android.app.Activity
import android.content.Intent
import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.net.Uri
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.util.Log
import android.view.KeyEvent
import android.view.View
import android.widget.ArrayAdapter
import android.widget.Button
import android.widget.ImageView
import android.widget.TextView
import androidx.annotation.OptIn
import androidx.appcompat.app.AlertDialog
import androidx.appcompat.app.AppCompatActivity
import androidx.lifecycle.lifecycleScope
import androidx.media3.common.C
import androidx.media3.common.MediaItem
import androidx.media3.common.MimeTypes
import androidx.media3.common.Player
import androidx.media3.common.text.Cue
import androidx.media3.common.util.UnstableApi
import androidx.media3.exoplayer.ExoPlayer
import androidx.media3.ui.CaptionStyleCompat
import androidx.media3.ui.PlayerView
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import org.json.JSONArray
import org.json.JSONObject
import java.net.URL

/**
 * O filme em si, no ExoPlayer.
 *
 * A URL ja chega assinada pela pagina (mesmo token do Chromecast), entao aqui
 * nao ha cookie nem sessao: e so tocar. Ao sair devolvemos posicao e duracao,
 * que a MainActivity entrega de volta para a pagina gravar o progresso.
 *
 * Por cima do video ficam a capa e o nome do que esta tocando e o botao
 * Legenda (tamanho, cor e liga/desliga), que aparecem junto com os controles.
 *
 * Em serie, a pagina manda tambem os proximos episodios ja assinados: nos
 * ultimos segundos aparece o cartao "Proximo episodio" e, ao acabar, o
 * seguinte comeca sozinho (ou na hora, em "Assistir agora"). O resultado leva
 * o progresso de cada episodio que passou por aqui.
 */
@OptIn(UnstableApi::class)
class PlayerActivity : AppCompatActivity() {

    private var player: ExoPlayer? = null
    private lateinit var playerView: PlayerView
    private lateinit var barraTopo: View

    // Mesmos tamanhos e cores da pagina (app.js: subtitleSizes / subtitleColors),
    // para a escolha valer nos dois lugares. O indice volta no resultado.
    private var tamanhoLegenda = 1
    private var corLegenda = 0
    private var legendaAtiva = true

    // Fila de episodios: [0] e o que a pagina abriu; os demais vem depois.
    private class Episodio(
        val path: String, val url: String, val legenda: String,
        val titulo: String, val contexto: String, val capa: String
    )
    private var fila: List<Episodio> = emptyList()
    private var indice = 0
    private val saidas = JSONArray()           // episodios que ja passaram: {path,pos,dur}
    private var proximoCancelado = false
    private var cartaoVisivel = false
    private val handler = Handler(Looper.getMainLooper())
    private val vigia = object : Runnable {
        override fun run() {
            atualizarCartaoProximo()
            handler.postDelayed(this, 500)
        }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_player)

        val url = intent.getStringExtra(EXTRA_URL) ?: run { finish(); return }
        val legenda = intent.getStringExtra(EXTRA_LEGENDA).orEmpty()
        val posicao = intent.getLongExtra(EXTRA_POSICAO, 0L)
        // Sempre abre em Média; a escolha vale só até sair do filme.
        corLegenda = intent.getIntExtra(EXTRA_LEG_COR, corLegenda).coerceIn(0, CORES.size - 1)

        val item = montarItem(url, legenda)
        fila = montarFila(url, legenda)

        player = ExoPlayer.Builder(this).build().also { p ->
            val view = findViewById<PlayerView>(R.id.player)
            playerView = view
            view.player = p
            aplicarEstiloLegenda()
            montarBarraTopo(view)
            // Sem isto todo erro de reproducao e uma tela preta muda: nem o
            // log mostra o motivo. O Toast e o minimo para o dono da TV saber
            // que o app ouviu o comando e foi o servidor/codec que recusou.
            p.addListener(object : androidx.media3.common.Player.Listener {
                override fun onPlaybackStateChanged(estado: Int) {
                    // Fim do episodio: emenda o seguinte, se houver e nao foi cancelado.
                    if (estado == Player.STATE_ENDED && temProximo() && !proximoCancelado) avancar()
                }

                override fun onPlayerError(error: androidx.media3.common.PlaybackException) {
                    Log.e("12:00 Media ServerPlayer", "erro de reproducao: $error")
                    android.widget.Toast.makeText(
                        this@PlayerActivity,
                        "Falha ao tocar: ${error.errorCodeName}",
                        android.widget.Toast.LENGTH_LONG
                    ).show()
                }
            })
            p.setMediaItem(item)
            if (posicao > 0) p.seekTo(posicao * 1000L)
            p.prepare()
            p.playWhenReady = true
        }
        montarCartaoProximo()
        handler.post(vigia)
    }

    private fun montarItem(url: String, legenda: String): MediaItem =
        MediaItem.Builder().setUri(url).apply {
            if (legenda.isNotEmpty()) {
                setSubtitleConfigurations(
                    listOf(
                        MediaItem.SubtitleConfiguration.Builder(Uri.parse(legenda))
                            // O servidor sempre entrega WebVTT, mesmo quando o
                            // arquivo no disco e .srt.
                            .setMimeType(MimeTypes.TEXT_VTT)
                            .setLanguage("pt")
                            .setSelectionFlags(C.SELECTION_FLAG_DEFAULT)
                            .build()
                    )
                )
            }
        }.build()

    /** O episodio aberto + os que a pagina mandou depois dele. */
    private fun montarFila(url: String, legenda: String): List<Episodio> {
        val lista = mutableListOf(
            Episodio(
                intent.getStringExtra(EXTRA_PATH).orEmpty(), url, legenda,
                intent.getStringExtra(EXTRA_TITULO).orEmpty(),
                intent.getStringExtra(EXTRA_CONTEXTO).orEmpty(),
                intent.getStringExtra(EXTRA_CAPA).orEmpty()
            )
        )
        try {
            val arr = JSONArray(intent.getStringExtra(EXTRA_FILA) ?: "[]")
            for (i in 0 until arr.length()) {
                val o = arr.getJSONObject(i)
                lista.add(
                    Episodio(
                        o.optString("path"), o.optString("url"), o.optString("legenda"),
                        o.optString("titulo"), o.optString("contexto"), o.optString("capa")
                    )
                )
            }
        } catch (e: Exception) {
            Log.w("12:00 Media Server", "fila de episodios invalida: $e")
        }
        return lista
    }

    private fun temProximo() = indice < fila.size - 1

    private fun montarCartaoProximo() {
        findViewById<Button>(R.id.prox_agora).setOnClickListener { avancar() }
        findViewById<Button>(R.id.prox_cancelar).setOnClickListener {
            proximoCancelado = true
            esconderCartao()
        }
    }

    private fun esconderCartao() {
        cartaoVisivel = false
        findViewById<View>(R.id.card_proximo).visibility = View.GONE
    }

    /** Nos ultimos segundos de um episodio com sucessor: mostra o cartao e a contagem. */
    private fun atualizarCartaoProximo() {
        val p = player ?: return
        val card = findViewById<View>(R.id.card_proximo)
        val duracao = p.duration
        if (!temProximo() || proximoCancelado || duracao == C.TIME_UNSET || duracao <= 0) {
            if (cartaoVisivel) esconderCartao()
            return
        }
        val resta = (duracao - p.currentPosition) / 1000L
        if (resta !in 0..AVISO_PROXIMO_SEG) {
            if (cartaoVisivel) esconderCartao()
            return
        }
        findViewById<TextView>(R.id.prox_titulo).text = fila[indice + 1].titulo
        findViewById<TextView>(R.id.prox_conta).text = "Começa em ${resta + 1} s"
        if (!cartaoVisivel) {
            cartaoVisivel = true
            card.visibility = View.VISIBLE
            findViewById<Button>(R.id.prox_agora).requestFocus()
        }
    }

    /** Passa para o proximo episodio sem sair do player e registra o que ficou para tras. */
    private fun avancar() {
        val p = player ?: return
        if (!temProximo()) return
        val atual = fila[indice]
        saidas.put(
            JSONObject()
                .put("path", atual.path)
                .put("pos", p.currentPosition / 1000L)
                .put("dur", maxOf(p.duration, 0L) / 1000L)
        )
        indice += 1
        proximoCancelado = false
        esconderCartao()
        val prox = fila[indice]
        p.setMediaItem(montarItem(prox.url, prox.legenda))
        p.prepare()
        p.playWhenReady = true
        mostrarTopo(prox)
        playerView.showController()
    }

    private fun mostrarTopo(ep: Episodio) {
        findViewById<TextView>(R.id.titulo).text = ep.titulo
        findViewById<TextView>(R.id.contexto).apply {
            text = ep.contexto
            visibility = if (ep.contexto.isEmpty()) View.GONE else View.VISIBLE
        }
        findViewById<ImageView>(R.id.capa).visibility = View.GONE
        carregarCapa(ep.capa)
    }

    /**
     * Legenda no estilo da Apple TV (sans medio, caixa preta translucida de
     * 40%), com o tamanho e a cor escolhidos no botao Legenda.
     */
    private fun aplicarEstiloLegenda() {
        val sv = playerView.subtitleView ?: return
        sv.setApplyEmbeddedStyles(false)
        sv.setApplyEmbeddedFontSizes(false)
        sv.setStyle(
            CaptionStyleCompat(
                CORES[corLegenda].cor,
                0x66000000.toInt(),
                android.graphics.Color.TRANSPARENT,
                CaptionStyleCompat.EDGE_TYPE_NONE,
                android.graphics.Color.TRANSPARENT,
                android.graphics.Typeface.create("sans-serif-medium", android.graphics.Typeface.NORMAL)
            )
        )
        sv.setFractionalTextSize(TAMANHOS[tamanhoLegenda].fracao)
        sv.setBottomPaddingFraction(0.05f)
    }

    /** Capa + nome no topo e o botao Legenda; somem junto com os controles. */
    private fun montarBarraTopo(view: PlayerView) {
        barraTopo = findViewById(R.id.barra_topo)
        findViewById<TextView>(R.id.titulo).text = intent.getStringExtra(EXTRA_TITULO).orEmpty()
        val contexto = intent.getStringExtra(EXTRA_CONTEXTO).orEmpty()
        findViewById<TextView>(R.id.contexto).apply {
            text = contexto
            visibility = if (contexto.isEmpty()) View.GONE else View.VISIBLE
        }
        findViewById<Button>(R.id.btn_legenda).setOnClickListener { abrirMenuLegenda() }
        carregarCapa(intent.getStringExtra(EXTRA_CAPA).orEmpty())
        view.setControllerVisibilityListener(
            PlayerView.ControllerVisibilityListener { visibilidade ->
                barraTopo.visibility = if (visibilidade == View.VISIBLE) View.VISIBLE else View.GONE
            }
        )
        // Ao abrir o filme os controles ja aparecem uns segundos, com o nome.
        view.showController()
    }

    /** A capa vem assinada (mesmo token do video); sem lib de imagem, baixa e reduz aqui. */
    private fun carregarCapa(url: String) {
        if (url.isEmpty()) return
        lifecycleScope.launch {
            val bmp: Bitmap? = withContext(Dispatchers.IO) {
                try {
                    val con = URL(url).openConnection().apply {
                        connectTimeout = 8000
                        readTimeout = 8000
                    }
                    val bytes = con.getInputStream().use { it.readBytes() }
                    val limites = BitmapFactory.Options().apply { inJustDecodeBounds = true }
                    BitmapFactory.decodeByteArray(bytes, 0, bytes.size, limites)
                    var amostra = 1
                    while (limites.outWidth / (amostra * 2) >= 300) amostra *= 2
                    val opcoes = BitmapFactory.Options().apply { inSampleSize = amostra }
                    BitmapFactory.decodeByteArray(bytes, 0, bytes.size, opcoes)
                } catch (e: Exception) {
                    Log.w("12:00 Media Server", "capa nao carregou: $e")
                    null
                }
            }
            if (bmp != null) {
                findViewById<ImageView>(R.id.capa).apply {
                    setImageBitmap(bmp)
                    visibility = View.VISIBLE
                }
            }
        }
    }

    /**
     * Menu da legenda: cada item muda de valor ao clicar e o menu continua
     * aberto. Enquanto ele esta aberto o filme pausa e aparece uma legenda de
     * exemplo, para ver o tamanho e a cor na hora.
     */
    private fun abrirMenuLegenda() {
        val p = player ?: return
        val tocava = p.isPlaying
        p.pause()
        val sv = playerView.subtitleView
        sv?.setCues(listOf(Cue.Builder().setText("Exemplo de legenda").build()))

        fun linhas() = listOf(
            "Legenda: " + if (legendaAtiva) "ativada" else "desativada",
            "Tamanho: " + TAMANHOS[tamanhoLegenda].nome,
            "Cor: " + CORES[corLegenda].nome,
            "Fechar"
        )
        val adaptador = ArrayAdapter(this, android.R.layout.simple_list_item_1, linhas().toMutableList())
        val dialogo = AlertDialog.Builder(this)
            .setTitle("Legenda")
            .setAdapter(adaptador, null)
            .create()
        dialogo.setOnDismissListener {
            sv?.setCues(null)
            if (tocava) p.play()
            playerView.showController()
        }
        dialogo.show()
        // Instalado depois do show(): o listener do Builder fecharia o menu a cada clique.
        dialogo.listView.setOnItemClickListener { _, _, posicao, _ ->
            when (posicao) {
                0 -> alternarLegenda(!legendaAtiva)
                1 -> { tamanhoLegenda = (tamanhoLegenda + 1) % TAMANHOS.size; aplicarEstiloLegenda() }
                2 -> { corLegenda = (corLegenda + 1) % CORES.size; aplicarEstiloLegenda() }
                else -> { dialogo.dismiss(); return@setOnItemClickListener }
            }
            adaptador.clear()
            adaptador.addAll(linhas())
            adaptador.notifyDataSetChanged()
        }
    }

    private fun alternarLegenda(ativa: Boolean) {
        legendaAtiva = ativa
        val p = player ?: return
        p.trackSelectionParameters = p.trackSelectionParameters
            .buildUpon()
            .setTrackTypeDisabled(C.TRACK_TYPE_TEXT, !ativa)
            .build()
    }

    /** MENU ou o botao CC do controle abrem o menu da legenda direto. */
    override fun dispatchKeyEvent(event: KeyEvent): Boolean {
        if (event.action == KeyEvent.ACTION_DOWN &&
            (event.keyCode == KeyEvent.KEYCODE_MENU || event.keyCode == KeyEvent.KEYCODE_CAPTIONS)
        ) {
            abrirMenuLegenda()
            return true
        }
        if (event.action == KeyEvent.ACTION_DOWN && event.keyCode == KeyEvent.KEYCODE_MEDIA_NEXT
            && temProximo()
        ) {
            avancar()
            return true
        }
        return super.dispatchKeyEvent(event)
    }

    /**
     *Sair do filme e a unica hora em que sabemos a posicao final, entao o
     * resultado sai daqui e nao do onDestroy — que pode nem rodar a tempo.
     */
    override fun finish() {
        player?.let { p ->
            setResult(
                Activity.RESULT_OK,
                Intent()
                    .putExtra(EXTRA_POSICAO, p.currentPosition / 1000L)
                    .putExtra(EXTRA_DURACAO, maxOf(p.duration, 0L) / 1000L)
                    .putExtra(EXTRA_LEG_TAM, tamanhoLegenda)
                    .putExtra(EXTRA_LEG_COR, corLegenda)
                    .putExtra(EXTRA_SAIDAS, saidas.toString())
                    .putExtra(EXTRA_ATUAL, fila.getOrNull(indice)?.path.orEmpty())
            )
        }
        super.finish()
    }

    override fun onStop() {
        super.onStop()
        handler.removeCallbacks(vigia)
        player?.release()
        player = null
    }

    companion object {
        const val EXTRA_URL = "url"
        const val EXTRA_LEGENDA = "legenda"
        const val EXTRA_POSICAO = "posicao"
        const val EXTRA_DURACAO = "duracao"
        const val EXTRA_TITULO = "titulo"
        const val EXTRA_CONTEXTO = "contexto"
        const val EXTRA_CAPA = "capa"
        const val EXTRA_LEG_TAM = "leg_tam"
        const val EXTRA_LEG_COR = "leg_cor"
        const val EXTRA_PATH = "path"
        const val EXTRA_FILA = "fila"
        const val EXTRA_SAIDAS = "saidas"
        const val EXTRA_ATUAL = "atual"

        // Quantos segundos antes do fim aparece o cartao "Proximo episodio".
        private const val AVISO_PROXIMO_SEG = 20L

        private class OpcaoTamanho(val nome: String, val fracao: Float)
        private class OpcaoCor(val nome: String, val cor: Int)

        // Espelham subtitleSizes e subtitleColors do app.js (mesma ordem).
        private val TAMANHOS = listOf(
            OpcaoTamanho("Pequena", 0.035f),
            OpcaoTamanho("Média", 0.045f),
            OpcaoTamanho("Grande", 0.06f),
            OpcaoTamanho("Extra grande", 0.08f)
        )
        private val CORES = listOf(
            OpcaoCor("Amarelo", 0xFFFFD700.toInt()),
            OpcaoCor("Branco", 0xFFFFFFFF.toInt())
        )
    }
}
