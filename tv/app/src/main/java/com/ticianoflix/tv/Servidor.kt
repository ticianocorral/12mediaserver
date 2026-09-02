package com.ticianoflix.tv

import android.content.Context
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.async
import kotlinx.coroutines.awaitAll
import kotlinx.coroutines.coroutineScope
import kotlinx.coroutines.withContext
import java.net.HttpURLConnection
import java.net.Inet4Address
import java.net.NetworkInterface
import java.net.URL

/**
 * Onde mora o TicianoFlix e como achar.
 *
 * A descoberta e uma varredura da propria faixa da rede: para cada endereco
 * .1 a .254 batemos em /api/auth/status, que e publica e responde um JSON
 * reconhecivel. E rustico, mas nao exige nada do servidor (nenhum mDNS, nenhuma
 * rota nova) e termina em cerca de dois segundos com as sondas em paralelo.
 */
object Servidor {

    const val PORTA = 9187

    private const val PREFS = "ticianoflix"
    private const val CHAVE = "servidor"
    private const val TIMEOUT_MS = 400

    fun salvo(ctx: Context): String? =
        ctx.getSharedPreferences(PREFS, Context.MODE_PRIVATE).getString(CHAVE, null)

    fun salvar(ctx: Context, base: String) {
        ctx.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
            .edit().putString(CHAVE, base).apply()
    }

    fun esquecer(ctx: Context) {
        ctx.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
            .edit().remove(CHAVE).apply()
    }

    /** Aceita "192.168.0.10", "192.168.0.10:9187" ou a URL inteira. */
    fun normalizar(entrada: String): String {
        val limpo = entrada.trim().removeSuffix("/")
        if (limpo.isEmpty()) return ""
        val comEsquema = if (limpo.startsWith("http")) limpo else "http://$limpo"
        return if (comEsquema.substringAfter("://").contains(":")) comEsquema
        else "$comEsquema:$PORTA"
    }

    /**
     * True quando o endereco responde algo que so o TicianoFlix responderia.
     * Nao basta "abriu a porta": qualquer servico poderia estar ali.
     */
    suspend fun responde(base: String): Boolean = withContext(Dispatchers.IO) {
        var conexao: HttpURLConnection? = null
        try {
            conexao = (URL("$base/api/auth/status").openConnection() as HttpURLConnection).apply {
                connectTimeout = TIMEOUT_MS
                readTimeout = TIMEOUT_MS
                requestMethod = "GET"
                setRequestProperty("Accept", "application/json")
            }
            if (conexao.responseCode != 200) return@withContext false
            val corpo = conexao.inputStream.bufferedReader().use { it.readText() }
            corpo.contains("\"configured\"")
        } catch (e: Exception) {
            false
        } finally {
            conexao?.disconnect()
        }
    }

    /** Faixas /24 em que este aparelho esta, sem o ultimo octeto. */
    private fun faixasLocais(): List<String> {
        val faixas = mutableListOf<String>()
        try {
            for (iface in NetworkInterface.getNetworkInterfaces()) {
                if (!iface.isUp || iface.isLoopback) continue
                for (end in iface.interfaceAddresses) {
                    val ip = end.address
                    if (ip !is Inet4Address) continue
                    // Abaixo de /24 a varredura viraria dezenas de milhares de
                    // sondas; acima dela nao ha o que varrer.
                    if (end.networkPrefixLength < 24) continue
                    val texto = ip.hostAddress ?: continue
                    faixas += texto.substringBeforeLast('.')
                }
            }
        } catch (e: Exception) {
            // Sem interfaces legiveis a lista vazia leva a tela de IP manual.
        }
        return faixas.distinct()
    }

    /** Endereco base de cada TicianoFlix achado na rede. */
    suspend fun procurar(): List<String> = coroutineScope {
        val achados = mutableListOf<String>()
        for (faixa in faixasLocais()) {
            val sondas = (1..254).map { n ->
                async(Dispatchers.IO) {
                    val base = "http://$faixa.$n:$PORTA"
                    if (responde(base)) base else null
                }
            }
            achados += sondas.awaitAll().filterNotNull()
        }
        achados
    }
}
