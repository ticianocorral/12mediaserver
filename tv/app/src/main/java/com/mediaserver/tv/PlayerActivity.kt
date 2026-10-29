package com.mediaserver.tv

import android.app.Activity
import android.content.Intent
import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.net.Uri
import android.os.Bundle
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
import androidx.media3.common.text.Cue
import androidx.media3.common.util.UnstableApi
import androidx.media3.exoplayer.ExoPlayer
import androidx.media3.ui.CaptionStyleCompat
import androidx.media3.ui.PlayerView
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
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
 */
@OptIn(UnstableApi::class)
class PlayerActivity : AppCompatActivity() {

    private var player: ExoPlayer? = null
    private lateinit var playerView: PlayerView
    private lateinit var barraTopo: View

    // Mesmos tamanhos e cores da pagina (app.js: subtitleSizes / subtitleColors),
    // para a escolha valer nos dois lugares. O indice volta no resultado.
    private var tamanhoLegenda = 2
    private var corLegenda = 0
    private var legendaAtiva = true

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_player)

        val url = intent.getStringExtra(EXTRA_URL) ?: run { finish(); return }
        val legenda = intent.getStringExtra(EXTRA_LEGENDA).orEmpty()
        val posicao = intent.getLongExtra(EXTRA_POSICAO, 0L)
        tamanhoLegenda = intent.getIntExtra(EXTRA_LEG_TAM, tamanhoLegenda).coerceIn(0, TAMANHOS.size - 1)
        corLegenda = intent.getIntExtra(EXTRA_LEG_COR, corLegenda).coerceIn(0, CORES.size - 1)

        val item = MediaItem.Builder().setUri(url).apply {
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
        val adaptador = ArrayAdapter(this, android.R.layout.simple_list_item_1, linhas())
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
            )
        }
        super.finish()
    }

    override fun onStop() {
        super.onStop()
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
