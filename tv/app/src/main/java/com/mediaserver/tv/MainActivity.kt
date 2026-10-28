package com.mediaserver.tv

import android.annotation.SuppressLint
import android.app.Activity
import android.content.Intent
import android.os.Bundle
import android.util.Log
import android.webkit.CookieManager
import android.webkit.JavascriptInterface
import android.view.View
import android.webkit.WebResourceError
import android.webkit.WebResourceRequest
import android.webkit.WebResourceResponse
import android.webkit.WebView
import android.widget.Button
import android.webkit.WebViewClient
import androidx.activity.OnBackPressedCallback
import androidx.appcompat.app.AppCompatActivity
import androidx.lifecycle.lifecycleScope
import kotlinx.coroutines.launch
import org.json.JSONObject

/**
 * A interface e a propria web do 12:00 Media Server, carregada com ?tv=1 — o modo que
 * torna tudo navegavel pelo controle. Reconstruir as telas em Kotlin daria uma
 * segunda interface para manter; assim a TV herda cada novidade da web.
 *
 * A unica coisa que nao acontece na WebView e tocar o filme: para isso a pagina
 * chama MediaServerTV.play() e quem assume e o ExoPlayer.
 */
class MainActivity : AppCompatActivity() {

    private lateinit var web: WebView
    private lateinit var aviso: View
    private lateinit var botaoAtualizar: Button

    @SuppressLint("SetJavaScriptEnabled")
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)

        val base = Servidor.salvo(this) ?: run {
            startActivity(Intent(this, SetupActivity::class.java))
            finish()
            return
        }

        setContentView(R.layout.activity_main)
        web = findViewById(R.id.web)

        web.settings.javaScriptEnabled = true
        // O app usa localStorage; sem isto ele falha calado.
        web.settings.domStorageEnabled = true

        // A WebView herda o tamanho de fonte do sistema ("textZoom"); com a
        // fonte da TV em um nivel alto a pagina inteira estufa como se tivesse
        // recebido 125%. Travar em 100 deixa a escala nas maos do viewport.
        web.settings.textZoom = 100

        // O cookie de sessao vale 90 dias, mas so sobrevive a fechar o app se
        // for gravado em disco. Sem o flush do onPause, cada abertura do app
        // pediria login de novo — com o teclado da TV, no controle remoto.
        CookieManager.getInstance().setAcceptCookie(true)
        CookieManager.getInstance().setAcceptThirdPartyCookies(web, false)

        web.addJavascriptInterface(Ponte(), "MediaServerTV")
        // WebViewClient padrao para a navegacao ficar dentro do app em vez de
        // abrir o navegador do sistema.
        aviso = findViewById(R.id.desconectado)
        botaoAtualizar = findViewById(R.id.atualizar)
        botaoAtualizar.setOnClickListener { atualizar(base) }

        web.webViewClient = object : WebViewClient() {
            // So a pagina principal: falha de imagem ou de outro recurso nao
            // pode derrubar a interface inteira.
            override fun onReceivedError(
                view: WebView, request: WebResourceRequest, error: WebResourceError
            ) {
                if (request.isForMainFrame) mostrarAviso()
            }

            override fun onReceivedHttpError(
                view: WebView, request: WebResourceRequest, resposta: WebResourceResponse
            ) {
                if (request.isForMainFrame && resposta.statusCode >= 500) mostrarAviso()
            }
        }
        web.loadUrl("$base/?tv=1")

        // Endereco salvo pode ter ficado velho (o roteador troca o IP do Mac) ou
        // o servidor estar desligado: em vez de tela escura, mostra o aviso com
        // o botao Atualizar, que tambem re-escaneia a rede.
        lifecycleScope.launch {
            if (!Servidor.responde(base)) {
                Log.w("12:00 Media Server", "servidor salvo $base nao responde")
                mostrarAviso()
            }
        }

        // O Voltar do controle anda no historico da pagina (a navegacao e
        // pushState) e so sai do app quando nao ha mais para onde voltar.
        onBackPressedDispatcher.addCallback(this, object : OnBackPressedCallback(true) {
            override fun handleOnBackPressed() {
                if (web.canGoBack()) web.goBack() else finish()
            }
        })
    }

    private fun mostrarAviso() {
        aviso.visibility = View.VISIBLE
        botaoAtualizar.requestFocus()
    }

    /**
     * Tenta o endereco salvo; se morreu, varre a rede (o IP pode ter mudado).
     * Achando, recarrega a pagina e some com o aviso.
     */
    private fun atualizar(base: String) {
        botaoAtualizar.isEnabled = false
        botaoAtualizar.setText(R.string.atualizando)
        lifecycleScope.launch {
            var destino: String? = if (Servidor.responde(base)) base else null
            if (destino == null) {
                destino = Servidor.procurar().firstOrNull()
                if (destino != null) Servidor.salvar(this@MainActivity, destino)
            }
            botaoAtualizar.isEnabled = true
            botaoAtualizar.setText(R.string.atualizar)
            if (destino != null) {
                aviso.visibility = View.GONE
                web.loadUrl("$destino/?tv=1")
            } else {
                botaoAtualizar.requestFocus()
            }
        }
    }

    override fun onPause() {
        super.onPause()
        CookieManager.getInstance().flush()
    }

    /** O que a pagina enxerga como window.MediaServerTV. */
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
                Log.w("12:00 Media Server", "play(): json invalido: $json")
                return
            }
            Log.i("12:00 Media Server", "play(): url=${dados.optString("url")} legenda=${dados.optString("legenda")} posicao=${dados.optLong("posicao", 0L)}")
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
