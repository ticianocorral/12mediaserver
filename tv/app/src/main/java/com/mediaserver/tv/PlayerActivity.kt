package com.mediaserver.tv

import android.app.Activity
import android.content.Intent
import android.net.Uri
import android.os.Bundle
import android.util.Log
import androidx.annotation.OptIn
import androidx.appcompat.app.AppCompatActivity
import androidx.media3.common.C
import androidx.media3.common.MediaItem
import androidx.media3.common.MimeTypes
import androidx.media3.common.util.UnstableApi
import androidx.media3.exoplayer.ExoPlayer
import androidx.media3.ui.PlayerView

/**
 * O filme em si, no ExoPlayer.
 *
 * A URL ja chega assinada pela pagina (mesmo token do Chromecast), entao aqui
 * nao ha cookie nem sessao: e so tocar. Ao sair devolvemos posicao e duracao,
 * que a MainActivity entrega de volta para a pagina gravar o progresso.
 */
@OptIn(UnstableApi::class)
class PlayerActivity : AppCompatActivity() {

    private var player: ExoPlayer? = null

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_player)

        val url = intent.getStringExtra(EXTRA_URL) ?: run { finish(); return }
        val legenda = intent.getStringExtra(EXTRA_LEGENDA).orEmpty()
        val posicao = intent.getLongExtra(EXTRA_POSICAO, 0L)

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
            view.player = p
            estiloAppleTv(view)
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

    /** Legenda no estilo da Apple TV: branca, sans medio, caixa preta translucida (40%). */
    private fun estiloAppleTv(view: PlayerView) {
        val sv = view.subtitleView ?: return
        sv.setApplyEmbeddedStyles(false)
        sv.setApplyEmbeddedFontSizes(false)
        sv.setStyle(
            androidx.media3.ui.CaptionStyleCompat(
                android.graphics.Color.WHITE,
                0x66000000.toInt(),
                android.graphics.Color.TRANSPARENT,
                androidx.media3.ui.CaptionStyleCompat.EDGE_TYPE_NONE,
                android.graphics.Color.TRANSPARENT,
                android.graphics.Typeface.create("sans-serif-medium", android.graphics.Typeface.NORMAL)
            )
        )
        sv.setFractionalTextSize(0.04f)
        sv.setBottomPaddingFraction(0.05f)
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
    }
}
