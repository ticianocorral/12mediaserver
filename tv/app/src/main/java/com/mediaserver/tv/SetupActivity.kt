package com.mediaserver.tv

import android.content.Intent
import android.os.Bundle
import android.view.View
import android.widget.Button
import android.widget.EditText
import android.widget.LinearLayout
import android.widget.TextView
import androidx.appcompat.app.AppCompatActivity
import androidx.lifecycle.lifecycleScope
import kotlinx.coroutines.launch

/** Escolha do servidor: o que a varredura achou, ou um endereco digitado. */
class SetupActivity : AppCompatActivity() {

    private lateinit var estado: TextView
    private lateinit var achados: LinearLayout

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_setup)
        estado = findViewById(R.id.estado)
        achados = findViewById(R.id.achados)

        val manual = findViewById<EditText>(R.id.manual)
        findViewById<Button>(R.id.conectar).setOnClickListener {
            conectar(Servidor.normalizar(manual.text.toString()))
        }
        findViewById<Button>(R.id.procurar).setOnClickListener { varrer() }

        varrer()
    }

    private fun varrer() {
        achados.removeAllViews()
        estado.setText(R.string.procurando)
        lifecycleScope.launch {
            val lista = Servidor.procurar()
            if (lista.isEmpty()) {
                estado.setText(R.string.nenhum)
                return@launch
            }
            estado.text = getString(R.string.app_name)
            for (base in lista) {
                achados.addView(botao(base))
            }
            // Foco no primeiro achado: com controle remoto, nada pior do que
            // uma tela com opcoes e nenhuma delas selecionada.
            achados.getChildAt(0)?.requestFocus()
        }
    }

    private fun botao(base: String): View = Button(this).apply {
        text = base.removePrefix("http://")
        setOnClickListener { conectar(base) }
    }

    private fun conectar(base: String) {
        if (base.isEmpty()) return
        lifecycleScope.launch {
            if (!Servidor.responde(base)) {
                estado.setText(R.string.nenhum)
                return@launch
            }
            Servidor.salvar(this@SetupActivity, base)
            startActivity(Intent(this@SetupActivity, MainActivity::class.java))
            finish()
        }
    }
}
