package com.ticianoflix.tv

import android.annotation.SuppressLint
import android.app.Activity
import android.content.Intent
import android.os.Bundle
import android.webkit.CookieManager
import android.webkit.JavascriptInterface
import android.webkit.WebView
import android.webkit.WebViewClient
import androidx.activity.OnBackPressedCallback
import androidx.appcompat.app.AppCompatActivity
import org.json.JSONObject

/**
 * A interface e a propria web do TicianoFlix, carregada com ?tv=1 — o modo que
 * torna tudo navegavel pelo controle. Reconstruir as telas em Kotlin daria uma
 * segunda interface para manter; assim a TV herda cada novidade da web.
 *
 * A unica coisa que nao acontece na WebView e tocar o filme: para isso a pagina
 * chama TicianoFlixTV.play() e quem assume e o ExoPlayer.
 */
class MainActivity : AppCompatActivity() {

    private lateinit var web: WebView

    @SuppressLint("SetJavaScriptEnabled")
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)

        val base = Servidor.salvo(this)
        if (base == null) {
            startActivity(Intent(this, SetupActivity::class.java))
            finish()
            return
        }

        setContentView(R.layout.activity_main)
        web = findViewById(R.id.web)

        web.settings.javaScriptEnabled = true
        // O app usa localStorage; sem isto ele falha calado.
        web.settings.domStorageEnabled = true

        // O cookie de sessao vale 90 dias, mas so sobrevive a fechar o app se
        // for gravado em disco. Sem o flush do onPause, cada abertura do app
        // pediria login de novo — com o teclado da TV, no controle remoto.
        CookieManager.getInstance().setAcceptCookie(true)
        CookieManager.getInstance().setAcceptThirdPartyCookies(web, false)

        web.addJavascriptInterface(Ponte(), "TicianoFlixTV")
        // WebViewClient padrao para a navegacao ficar dentro do app em vez de
        // abrir o navegador do sistema.
        web.webViewClient = WebViewClient()
        web.loadUrl("$base/?tv=1")

        // O Voltar do controle anda no historico da pagina (a navegacao e
        // pushState) e so sai do app quando nao ha mais para onde voltar.
        onBackPressedDispatcher.addCallback(this, object : OnBackPressedCallback(true) {
            override fun handleOnBackPressed() {
                if (web.canGoBack()) web.goBack() else finish()
            }
        })
    }

    override fun onPause() {
        super.onPause()
        CookieManager.getInstance().flush()
    }

    /** O que a pagina enxerga como window.TicianoFlixTV. */
    inner class Ponte {
        /**
         * Chamado por app.js no lugar de abrir o player da pagina.
         *
         * Roda numa thread do WebView, nao na de interface: por isso o
         * runOnUiThread antes de abrir a Activity.
         */
        @JavascriptInterface
        fun play(json: String) {
            val dados = try {
                JSONObject(json)
            } catch (e: Exception) {
                return
            }
            val i = Intent(this@MainActivity, PlayerActivity::class.java)
                .putExtra(PlayerActivity.EXTRA_URL, dados.optString("url"))
                .putExtra(PlayerActivity.EXTRA_LEGENDA, dados.optString("legenda"))
                .putExtra(PlayerActivity.EXTRA_POSICAO, dados.optLong("posicao", 0L))
            runOnUiThread { startActivityForResult(i, COD_PLAYER) }
        }
    }

    @Suppress("DEPRECATION")
    override fun onActivityResult(requisicao: Int, resultado: Int, dados: Intent?) {
        super.onActivityResult(requisicao, resultado, dados)
        if (requisicao != COD_PLAYER || resultado != Activity.RESULT_OK || dados == null) return
        val posicao = dados.getLongExtra(PlayerActivity.EXTRA_POSICAO, 0L)
        val duracao = dados.getLongExtra(PlayerActivity.EXTRA_DURACAO, 0L)
        // Quem decide se vale gravar e a propria pagina: ela ja ignora os
        // primeiros segundos e limpa o progresso de um filme terminado.
        web.evaluateJavascript("window.tvPlaybackEnded($posicao, $duracao)", null)
    }

    companion object {
        private const val COD_PLAYER = 1
    }
}
