# SPDX-License-Identifier: GPL-2.0-or-later
"""Login against the host's own accounts (PAM) and the sessions that follow it.

Only the user hubd runs as can log in: its shells run as that user, so nobody else
has any business here, and an unprivileged process can only check its own password
anyway (pam_unix goes through unix_chkpwd). Tokens are kept hashed and in memory, so
restarting hubd logs everyone out.
"""
from __future__ import annotations

import ctypes
import ctypes.util
import hashlib
import hmac
import os
import pwd
import secrets
import stat
import time
from pathlib import Path

IDLE_SECONDS = 12 * 3600
MAX_SECONDS = 7 * 24 * 3600
MAX_DELAY = 30.0

_PAM_PROMPT_ECHO_OFF = 1
_PAM_PROMPT_ECHO_ON = 2
_PAM_SUCCESS = 0
_PAM_BUF_ERR = 5
_PAM_CONV_ERR = 19
_PAM_SILENT = 0x8000


class _Message(ctypes.Structure):
    _fields_ = [("msg_style", ctypes.c_int), ("msg", ctypes.c_char_p)]


class _Response(ctypes.Structure):
    _fields_ = [("resp", ctypes.c_void_p), ("resp_retcode", ctypes.c_int)]


_ConvFunc = ctypes.CFUNCTYPE(
    ctypes.c_int, ctypes.c_int, ctypes.POINTER(ctypes.POINTER(_Message)),
    ctypes.POINTER(ctypes.POINTER(_Response)), ctypes.c_void_p,
)


class _Conv(ctypes.Structure):
    _fields_ = [("conv", _ConvFunc), ("appdata_ptr", ctypes.c_void_p)]


def pam_authenticate(user: str, password: str, service: str) -> bool:
    """True if PAM accepts the password and the account. Blocks: call from a thread."""
    libpam = ctypes.CDLL(ctypes.util.find_library("pam") or "libpam.so.0")
    libc = ctypes.CDLL(None)
    libc.calloc.restype = ctypes.c_void_p
    libc.calloc.argtypes = [ctypes.c_size_t, ctypes.c_size_t]
    libc.strdup.restype = ctypes.c_void_p
    libc.strdup.argtypes = [ctypes.c_char_p]
    libpam.pam_start.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.POINTER(_Conv),
                                 ctypes.POINTER(ctypes.c_void_p)]
    libpam.pam_authenticate.argtypes = [ctypes.c_void_p, ctypes.c_int]
    libpam.pam_acct_mgmt.argtypes = [ctypes.c_void_p, ctypes.c_int]
    libpam.pam_end.argtypes = [ctypes.c_void_p, ctypes.c_int]

    secret = password.encode()

    def conv(n, messages, responses, _data):
        # ctypes swallows exceptions here and would return 0: success, with no answer set.
        try:
            # PAM frees the array and the strings, so they come from libc's allocator.
            out = libc.calloc(n, ctypes.sizeof(_Response))
            if not out:
                return _PAM_BUF_ERR
            array = ctypes.cast(out, ctypes.POINTER(_Response))
            for i in range(n):
                if messages[i].contents.msg_style in (_PAM_PROMPT_ECHO_OFF, _PAM_PROMPT_ECHO_ON):
                    array[i].resp = libc.strdup(secret)
            responses[0] = array
            return _PAM_SUCCESS
        except Exception:
            return _PAM_CONV_ERR

    callback = _ConvFunc(conv)
    handle = ctypes.c_void_p()
    conversation = _Conv(callback, None)
    rc = libpam.pam_start(service.encode(), user.encode(), ctypes.byref(conversation), ctypes.byref(handle))
    if rc != _PAM_SUCCESS:
        return False
    try:
        rc = libpam.pam_authenticate(handle, _PAM_SILENT)
        if rc == _PAM_SUCCESS:
            rc = libpam.pam_acct_mgmt(handle, _PAM_SILENT)
        return rc == _PAM_SUCCESS
    finally:
        libpam.pam_end(handle, rc)


def _digest(token: str) -> bytes:
    return hashlib.sha256(token.encode()).digest()


class Sessions:
    def __init__(self, clock=time.monotonic):
        self._clock = clock
        self._live: dict[bytes, dict] = {}
        self._failures = 0
        self._not_before = 0.0

    @staticmethod
    def own_user() -> str:
        return pwd.getpwuid(os.getuid()).pw_name

    def retry_after(self) -> float:
        return max(0.0, self._not_before - self._clock())

    def record_failure(self) -> None:
        self._failures += 1
        self._not_before = self._clock() + min(MAX_DELAY, 2.0 ** (self._failures - 1))

    def create(self) -> str:
        self._failures = 0
        self._not_before = 0.0
        token = secrets.token_urlsafe(32)
        now = self._clock()
        self._live[_digest(token)] = {"created": now, "seen": now}
        return token

    def check(self, token) -> bool:
        if not isinstance(token, str) or not token:
            return False
        key = _digest(token)
        entry = self._live.get(key)
        if entry is None:
            return False
        now = self._clock()
        if now - entry["seen"] > IDLE_SECONDS or now - entry["created"] > MAX_SECONDS:
            del self._live[key]
            return False
        entry["seen"] = now
        return True

    def revoke(self, token) -> None:
        if isinstance(token, str):
            self._live.pop(_digest(token), None)


def load_agent_token(path: Path) -> str:
    """The tool server's bearer token: made once, 0600, handed to hub shells by hubd."""
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        if stat.S_IMODE(path.stat().st_mode) & 0o077:
            raise SystemExit(f"{path} must not be readable by others")
        return path.read_text().strip()
    token = secrets.token_urlsafe(32)
    with os.fdopen(fd, "w") as f:
        f.write(token + "\n")
    return token


def same(a: str, b: str) -> bool:
    return hmac.compare_digest(a.encode(), b.encode())
