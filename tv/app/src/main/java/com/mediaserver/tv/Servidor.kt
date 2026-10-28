package com.mediaserver.tv

import android.annotation.SuppressLint
import android.content.Context
import android.net.nsd.NsdManager
import android.net.nsd.NsdServiceInfo
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.async
import kotlinx.coroutines.awaitAll
import kotlinx.coroutines.coroutineScope
import kotlinx.coroutines.suspendCancellableCoroutine
import kotlinx.coroutines.withContext
import kotlinx.coroutines.withTimeoutOrNull
import java.net.HttpURLConnection
import java.net.Inet4Address
import java.net.NetworkInterface
import java.net.URL
import kotlin.coroutines.resume

/**
 * Onde mora o 12:00 Media Server e como achar.
 *
 * A descoberta e uma varredura da propria faixa da rede: para cada endereco
 * .1 a .254 batemos em /api/auth/status, que e publica e responde um JSON
 * reconhecivel. E rustico, mas nao exige nada do servidor (nenhum mDNS, nenhuma
 * rota nova) e termina em cerca de dois segundos com as sondas em paralelo.
 */
object Servidor {

    const val PORTA = 9187

    private const val PREFS = "media-server"
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
     * True quando o endereco responde algo que so o 12:00 Media Server responderia.
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

    /** Endereco base de cada 12:00 Media Server achado na rede. */
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

    /**
     * Acha o servidor pelo anuncio Bonjour/mDNS que o Mac publica
     * (_media-server._tcp, via dns-sd). E o caminho que sobrevive a troca de
     * IP: nomes .local o Android so resolve nativamente a partir do 12, mas o
     * NsdManager funciona desde as versoes antigas.
     *
     * Quem ainda anuncia o tipo de antes da troca de nome (_ticianoflix._tcp)
     * continua sendo achado: tenta o novo e, se nada responder, o antigo.
     */
    suspend fun procurarViaBonjour(ctx: Context): String? =
        descobrir(ctx, "_media-server._tcp", "media-server", 4_000L)
            ?: descobrir(ctx, "_ticianoflix._tcp", "ticianoflix", 4_000L)

    @SuppressLint("ServiceCast")
    private suspend fun descobrir(ctx: Context, tipo: String, marca: String, ms: Long): String? =
        withTimeoutOrNull(ms) {
        suspendCancellableCoroutine { cont ->
            val nsd = ctx.getSystemService(Context.NSD_SERVICE) as NsdManager
            var encerrado = false
            var resolvendo = false
            var listener: NsdManager.DiscoveryListener? = null

            fun terminar(base: String?) {
                if (encerrado) return
                encerrado = true
                listener?.let { try { nsd.stopServiceDiscovery(it) } catch (_: Exception) {} }
                if (cont.isActive) cont.resume(base)
            }

            listener = object : NsdManager.DiscoveryListener {
                override fun onDiscoveryStarted(tipo: String) {}
                override fun onDiscoveryStopped(tipo: String) {}
                override fun onStartDiscoveryFailed(tipo: String, erro: Int) = terminar(null)
                override fun onStopDiscoveryFailed(tipo: String, erro: Int) {}
                override fun onServiceLost(info: NsdServiceInfo) {}

                override fun onServiceFound(info: NsdServiceInfo) {
                    if (encerrado || resolvendo) return
                    if (!info.serviceName.replace(" ", "-").contains(marca, ignoreCase = true)) return
                    resolvendo = true
                    nsd.resolveService(info, object : NsdManager.ResolveListener {
                        override fun onResolveFailed(i: NsdServiceInfo, erro: Int) {
                            resolvendo = false
                        }

                        override fun onServiceResolved(i: NsdServiceInfo) {
                            val host = i.host?.hostAddress
                            if (host == null) terminar(null)
                            else terminar("http://$host:${i.port}")
                        }
                    })
                }
            }
            nsd.discoverServices(tipo, NsdManager.PROTOCOL_DNS_SD, listener)
        }
    }
}
