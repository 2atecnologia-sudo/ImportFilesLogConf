from __future__ import annotations

import ctypes
import sys
from ctypes import wintypes


class SingleInstance:
    """
    Impede múltiplas instâncias da aplicação no Windows
    utilizando um Mutex nomeado.
    """

    ERROR_ALREADY_EXISTS = 183

    def __init__(self, name: str):
        self.name = name
        self.handle = None

        if sys.platform == "win32":
            self.kernel32 = ctypes.WinDLL(
                "kernel32",
                use_last_error=True
            )

            self.kernel32.CreateMutexW.argtypes = [
                ctypes.c_void_p,
                wintypes.BOOL,
                wintypes.LPCWSTR,
            ]

            self.kernel32.CreateMutexW.restype = wintypes.HANDLE

            self.kernel32.CloseHandle.argtypes = [
                wintypes.HANDLE
            ]

            self.kernel32.CloseHandle.restype = wintypes.BOOL

    def acquire(self) -> bool:

        if sys.platform != "win32":
            return True

        ctypes.set_last_error(0)

        self.handle = self.kernel32.CreateMutexW(
            None,
            False,
            self.name
        )

        if not self.handle:
            raise OSError(
                ctypes.get_last_error(),
                "Não foi possível criar o Mutex."
            )

        erro = ctypes.get_last_error()

        if erro == self.ERROR_ALREADY_EXISTS:
            self.kernel32.CloseHandle(self.handle)
            self.handle = None
            return False

        return True

    def release(self):

        if sys.platform != "win32":
            return

        if self.handle:
            self.kernel32.CloseHandle(self.handle)
            self.handle = None