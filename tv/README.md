# 12:00 Media Server na Android TV

App para abrir o 12:00 Media Server na TV com o controle remoto.

## Como funciona

A interface **é a própria web do 12:00 Media Server**, carregada numa WebView com
`?tv=1` — o modo que torna tudo navegável pelas setas do controle. Reconstruir
as telas em Kotlin criaria uma segunda interface para manter; assim a TV herda
cada novidade da web (coleções, séries) sem nenhum trabalho aqui.

A única coisa que não acontece na WebView é tocar o filme. O Chromium que a
WebView usa não é confiável com MKV e faixas AC3/DTS, que é o grosso do acervo,
então a página chama `MediaServerTV.play()` e quem assume é o **ExoPlayer**, que
decodifica por hardware. A URL vai assinada pelo mesmo token do Chromecast, então
o player nativo busca os bytes sozinho — o app nunca lida com sessão nem senha.

```
SetupActivity   varre a rede atrás de /api/auth/status, ou aceita o IP digitado
MainActivity    WebView em http://<ip>:9187/?tv=1  +  ponte MediaServerTV
PlayerActivity  ExoPlayer com a URL assinada, devolve a posição ao sair
```

### O player

- **Capa e nome:** no topo, junto com os controles, aparecem a capa (a do filme
  ou a da série, baixada com o mesmo token assinado) e o título. Em episódio, a
  segunda linha traz o nome da série; em filme, o ano.
- **Legenda:** o botão **Legenda** (ou `MENU` / `CC` no controle) abre um menu com
  liga/desliga, **tamanho** (Pequena, Média, Grande, Extra grande) e **cor**
  (Amarelo, Branco). O filme pausa enquanto o menu está aberto e mostra uma
  legenda de exemplo. As opções são as mesmas da página, e a escolha volta para
  ela ao sair do filme.

## Compilar

Precisa do Android Studio (traz o SDK e o JDK). Não há wrapper do Gradle no
repositório porque ele inclui um `.jar` binário — o Android Studio gera na
primeira abertura.

1. Abra a pasta `tv/` no Android Studio.
2. Aceite quando ele oferecer sincronizar o Gradle e baixar o SDK 34.
3. `Run` com a TV conectada, ou `Build > Build APK`.

## Instalar na TV

Ligue o modo desenvolvedor na TV (Ajustes › Sobre › toque 7 vezes em "Versão do
build") e a depuração por rede. Então, no computador:

```bash
adb connect <ip-da-tv>:5555
adb install -r app/build/outputs/apk/debug/app-debug.apk
```

## Primeiro uso

O app varre a rede e lista os 12:00 Media Server que achar; escolha o seu. Depois
aparece a tela de login normal — usuário e senha, uma vez só. O cookie vale 90
dias e é gravado em disco (`CookieManager.flush()` no `onPause`), então não é
preciso repetir a cada abertura.

Se o IP do computador mudar, abra o app e ele não conectará: apague os dados do
app na TV, ou use a tela de endereço manual.
