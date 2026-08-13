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
    const char *home = getenv("HOME");
    if (!home) home = "/Users/ticiano";
    char script[4096];
    snprintf(script, sizeof(script), "%s/TicianoFlix/server.py", home);

    child = fork();
    if (child == 0) {
        char *const args[] = {"/usr/bin/python3", script, NULL};
        execv(args[0], args);
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
