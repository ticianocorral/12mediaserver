// TicianoFlix — wrapper nativo (nome legível no Activity Monitor / Login Items).
// Fica vivo como pai e roda o servidor python como filho, propagando sinais.
// Compilado: clang -O2 -o ticianoflix-server ticianoflix-server.c
#include <unistd.h>
#include <stdio.h>
#include <stdlib.h>
#include <signal.h>
#include <sys/wait.h>

static pid_t child = 0;

static void forward(int sig) {
    if (child > 0) kill(child, sig);
}

int main(void) {
    // server.py e resolvido relativo ao cwd do processo — o WorkingDirectory
    // que o launchd/plist ja configura — e nao a um caminho fixo de HOME. Um
    // caminho fixo aqui exigia recompilar o wrapper toda vez que a pasta do
    // projeto mudasse de lugar; assim, so o plist precisa saber onde ela esta.
    child = fork();
    if (child == 0) {
        // Interpretador: o python3 do sistema (Apple) esta congelado no 3.9,
        // sem atualizacoes e sem hashlib.scrypt. Preferimos um python3 do
        // Homebrew (atual); TICIANOFLIX_PYTHON permite apontar outro na mao.
        // (Fora do array: getenv pode devolver NULL e um NULL no inicio do
        // array encerraria o loop antes de testar qualquer candidato.)
        const char *env_py = getenv("TICIANOFLIX_PYTHON");
        if (env_py && env_py[0] && access(env_py, X_OK) == 0) {
            char *const args[] = {(char *)env_py, "server.py", NULL};
            execv(env_py, args);
        }
        const char *cands[] = {
            "/opt/homebrew/bin/python3",   // Homebrew (Apple Silicon)
            "/usr/local/bin/python3",      // Homebrew (Intel) / python.org
            "/usr/bin/python3",            // fallback do sistema
            NULL
        };
        for (int i = 0; cands[i]; i++) {
            if (access(cands[i], X_OK) == 0) {
                char *const args[] = {(char *)cands[i], "server.py", NULL};
                execv(cands[i], args);
            }
        }
        // Nenhum candidato fixo: ultimo recurso, o python3 do PATH.
        char *const args[] = {(char *)"python3", "server.py", NULL};
        execvp("python3", args);
        perror("execv");
        _exit(127);
    }
    if (child < 0) { perror("fork"); return 1; }

    struct sigaction sa = {0};
    sa.sa_handler = forward;
    sigaction(SIGTERM, &sa, NULL);
    sigaction(SIGINT,  &sa, NULL);
    sigaction(SIGHUP,  &sa, NULL);

    int status;
    while (waitpid(child, &status, 0) > 0) {
        if (WIFEXITED(status)) return WEXITSTATUS(status);
        if (WIFSIGNALED(status)) return 128 + WTERMSIG(status);
    }
    return 1;
}
