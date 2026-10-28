"""Impede que o sistema suspenda enquanto ha video sendo transmitido.

No macOS usa uma assertion de energia do IOPowerManagement (via ctypes, sem
dependencias): enquanto o contador de referencias estiver acima de zero, o
sistema nao entra em suspensao por inatividade. A tela pode apagar — o que
importa e o servidor continuar servindo o filme. Fora do macOS (ou se a
assertion falhar) tudo vira no-op: o streaming nunca depende disso.

Uso:
    with keepawake.while_streaming():
        ...loop de streaming...
"""

import ctypes
import sys
import threading

# kCFStringEncodingUTF8
_CF_UTF8 = 0x08000100
# kIOPMAssertionTypePreventUserIdleSystemSleep
_ASSERT_TYPE = b"PreventUserIdleSystemSleep"

_lock = threading.Lock()
_refcount = 0
_assertion_id = 0


def _frameworks():
    """(iokit, corefoundation) ou None se nao for macOS / nao carregar."""
    if sys.platform != "darwin":
        return None
    try:
        iokit = ctypes.CDLL(
            "/System/Library/Frameworks/IOKit.framework/IOKit"
        )
        cf = ctypes.CDLL(
            "/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation"
        )
        cf.CFStringCreateWithCString.restype = ctypes.c_void_p
        cf.CFStringCreateWithCString.argtypes = [
            ctypes.c_void_p, ctypes.c_char_p, ctypes.c_uint32,
        ]
        iokit.IOPMAssertionCreateWithName.restype = ctypes.c_int
        iokit.IOPMAssertionCreateWithName.argtypes = [
            ctypes.c_void_p, ctypes.c_uint32, ctypes.c_void_p,
            ctypes.POINTER(ctypes.c_uint32),
        ]
        iokit.IOPMAssertionRelease.restype = ctypes.c_int
        iokit.IOPMAssertionRelease.argtypes = [ctypes.c_uint32]
        return iokit, cf
    except Exception:
        return None


def _create_assertion():
    """Cria a assertion; devolve o id (0 = nao conseguiu, vira no-op)."""
    frameworks = _frameworks()
    if frameworks is None:
        return 0
    iokit, cf = frameworks
    try:
        cf_type = cf.CFStringCreateWithCString(
            None, _ASSERT_TYPE, _CF_UTF8
        )
        cf_reason = cf.CFStringCreateWithCString(
            None, b"12:00 Media Server esta transmitindo um video", _CF_UTF8
        )
        if not cf_type or not cf_reason:
            return 0
        cid = ctypes.c_uint32(0)
        # nivel 0 = assertion simples, sem "o usuario esta ativo"
        status = iokit.IOPMAssertionCreateWithName(
            cf_type, 0, cf_reason, ctypes.byref(cid)
        )
        if status != 0:
            return 0
        return cid.value
    except Exception:
        return 0


def _release_assertion(aid):
    frameworks = _frameworks()
    if frameworks is None or not aid:
        return
    try:
        frameworks[0].IOPMAssertionRelease(aid)
    except Exception:
        pass


class _StreamGuard:
    def __enter__(self):
        global _refcount, _assertion_id
        with _lock:
            _refcount += 1
            if _refcount == 1:
                _assertion_id = _create_assertion()
                if _assertion_id:
                    print(
                        "[12:00 Media Server] Stream iniciado — suspensao do sistema pausada.",
                        flush=True,
                    )
        return self

    def __exit__(self, exc_type, exc, tb):
        global _refcount, _assertion_id
        with _lock:
            _refcount = max(0, _refcount - 1)
            if _refcount == 0 and _assertion_id:
                _release_assertion(_assertion_id)
                _assertion_id = 0
                print(
                    "[12:00 Media Server] Stream encerrado — suspensao do sistema reativada.",
                    flush=True,
                )
        return False


while_streaming = _StreamGuard
