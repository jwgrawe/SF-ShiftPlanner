"""Windows single sign-on for the browser (D121): HTTP «Negotiate».

The browser proves which Windows user is running it, using the login that
already exists (with the ID card) – no password, no PIN in the app. On the
server side Windows itself checks the proof through SSPI (secur32.dll),
called here with ctypes (part of Python; nothing to install).

The handshake (RFC 4559) takes one round with Kerberos and two with NTLM,
which is what Windows uses for a local address. NTLM's rounds must arrive on
the same connection, so unfinished handshakes are kept per connection.

`selftest()` runs a complete handshake inside one process (client and
server side), to check on the PC that Windows lets the app do this:
`python run.py --test-innlogging`.

Only the handshake bookkeeping (`Handshakes`) runs off Windows; it is tested
with a stand-in backend.
"""
from __future__ import annotations

import base64
import ctypes
import sys
import threading
import time
from ctypes import POINTER, byref, c_ulong, c_void_p, c_wchar_p, sizeof

SEC_E_OK = 0x00000000
SEC_I_CONTINUE_NEEDED = 0x00090312
SEC_I_COMPLETE_NEEDED = 0x00090313
SEC_I_COMPLETE_AND_CONTINUE = 0x00090314
SECPKG_CRED_INBOUND = 1
SECPKG_CRED_OUTBOUND = 2
SECBUFFER_VERSION = 0
SECBUFFER_TOKEN = 2
SECURITY_NATIVE_DREP = 0x10
SECPKG_ATTR_NAMES = 1
ASC_REQ_CONNECTION = 0x00000800
ISC_REQ_CONNECTION = 0x00000800
MAX_TOKEN = 48 * 1024
PACKAGE = "Negotiate"

KNOWN_ERRORS = {
    0x8009030C: "innloggingen ble avvist (SEC_E_LOGON_DENIED)",
    0x80090308: "ugyldig innloggingsdata fra nettleseren (SEC_E_INVALID_TOKEN)",
    0x8009030E: "ingen gyldig Windows-innlogging (SEC_E_NO_CREDENTIALS)",
    0x80090311: "fant ingen innloggingsserver (SEC_E_NO_AUTHENTICATING_AUTHORITY)",
    0x80090322: "feil måladresse (SEC_E_WRONG_PRINCIPAL)",
}


class AuthError(Exception):
    pass


def _describe(status: int) -> str:
    status &= 0xFFFFFFFF
    return KNOWN_ERRORS.get(status, f"Windows-feil 0x{status:08X}")


if sys.platform == "win32":                       # pragma: no cover - Windows only
    class SecHandle(ctypes.Structure):
        _fields_ = [("dwLower", ctypes.c_size_t), ("dwUpper", ctypes.c_size_t)]

    class SecBuffer(ctypes.Structure):
        _fields_ = [("cbBuffer", c_ulong), ("BufferType", c_ulong), ("pvBuffer", c_void_p)]

    class SecBufferDesc(ctypes.Structure):
        _fields_ = [("ulVersion", c_ulong), ("cBuffers", c_ulong), ("pBuffers", POINTER(SecBuffer))]

    class TimeStamp(ctypes.Structure):
        _fields_ = [("LowPart", c_ulong), ("HighPart", ctypes.c_long)]

    class SecPkgContextNames(ctypes.Structure):
        # A raw pointer: Windows owns the string and it must be freed as such.
        _fields_ = [("sUserName", c_void_p)]

    _secur32 = ctypes.WinDLL("secur32")
    _secur32.AcquireCredentialsHandleW.restype = ctypes.c_long
    _secur32.AcceptSecurityContext.restype = ctypes.c_long
    _secur32.InitializeSecurityContextW.restype = ctypes.c_long
    _secur32.QueryContextAttributesW.restype = ctypes.c_long

    def _credentials(direction: int) -> SecHandle:
        cred, expiry = SecHandle(), TimeStamp()
        status = _secur32.AcquireCredentialsHandleW(None, c_wchar_p(PACKAGE), c_ulong(direction), None,
                                                    None, None, None, byref(cred), byref(expiry))
        if status != SEC_E_OK:
            raise AuthError(f"Kunne ikke starte Windows-innlogging: {_describe(status)}")
        return cred

    def _buffers(data: bytes | None):
        """(descriptor, buffer, keep-alive) for an input (data) or output (None) token."""
        # Tokens are binary (they contain zero bytes): copy them exactly.
        raw = ((ctypes.c_char * len(data)).from_buffer_copy(data) if data
               else (ctypes.c_char * MAX_TOKEN)())
        buf = SecBuffer(len(raw), SECBUFFER_TOKEN, ctypes.cast(raw, c_void_p))
        desc = SecBufferDesc(SECBUFFER_VERSION, 1, ctypes.pointer(buf))
        return desc, buf, raw

    class SSPIServer:
        """One AcceptSecurityContext step per call; the context object is
        kept by the caller between NTLM's rounds."""

        def __init__(self):
            self.cred = _credentials(SECPKG_CRED_INBOUND)

        def step(self, ctx: "SecHandle | None", token: bytes):
            in_desc, _, keep_in = _buffers(token)
            out_desc, out_buf, keep_out = _buffers(None)
            new_ctx = ctx or SecHandle()
            attrs, expiry = c_ulong(0), TimeStamp()
            status = _secur32.AcceptSecurityContext(
                byref(self.cred), byref(ctx) if ctx else None, byref(in_desc), c_ulong(ASC_REQ_CONNECTION),
                c_ulong(SECURITY_NATIVE_DREP), byref(new_ctx), byref(out_desc), byref(attrs), byref(expiry))
            status &= 0xFFFFFFFF
            out = ctypes.string_at(out_buf.pvBuffer, out_buf.cbBuffer) if out_buf.cbBuffer else b""
            if status in (SEC_I_COMPLETE_NEEDED, SEC_I_COMPLETE_AND_CONTINUE):
                _secur32.CompleteAuthToken(byref(new_ctx), byref(out_desc))
                status = SEC_E_OK if status == SEC_I_COMPLETE_NEEDED else SEC_I_CONTINUE_NEEDED
            if status == SEC_I_CONTINUE_NEEDED:
                return False, out, new_ctx, None
            if status != SEC_E_OK:
                if ctx is not None or new_ctx.dwLower or new_ctx.dwUpper:
                    _secur32.DeleteSecurityContext(byref(new_ctx))
                raise AuthError(_describe(status))
            names = SecPkgContextNames()
            status = _secur32.QueryContextAttributesW(byref(new_ctx), c_ulong(SECPKG_ATTR_NAMES), byref(names))
            user = ctypes.wstring_at(names.sUserName) if status == SEC_E_OK and names.sUserName else None
            if status == SEC_E_OK and names.sUserName:
                _secur32.FreeContextBuffer(c_void_p(names.sUserName))
            _secur32.DeleteSecurityContext(byref(new_ctx))
            if not user:
                raise AuthError(f"Fant ikke brukernavnet: {_describe(status)}")
            return True, out, None, user

        def drop(self, ctx) -> None:
            if ctx is not None:
                _secur32.DeleteSecurityContext(byref(ctx))

    def _client_step(cred, ctx, token: bytes | None, target: str):
        out_desc, out_buf, keep_out = _buffers(None)
        new_ctx = ctx or SecHandle()
        attrs, expiry = c_ulong(0), TimeStamp()
        if token is not None:
            in_desc, _, keep_in = _buffers(token)
            in_ref = byref(in_desc)
        else:
            in_ref = None
        status = _secur32.InitializeSecurityContextW(
            byref(cred), byref(ctx) if ctx else None, c_wchar_p(target), c_ulong(ISC_REQ_CONNECTION), c_ulong(0),
            c_ulong(SECURITY_NATIVE_DREP), in_ref, c_ulong(0), byref(new_ctx), byref(out_desc), byref(attrs),
            byref(expiry)) & 0xFFFFFFFF
        out = ctypes.string_at(out_buf.pvBuffer, out_buf.cbBuffer) if out_buf.cbBuffer else b""
        if status not in (SEC_E_OK, SEC_I_CONTINUE_NEEDED):
            raise AuthError(f"Klientsiden: {_describe(status)}")
        return status == SEC_I_CONTINUE_NEEDED, out, new_ctx
else:
    SSPIServer = None


class Handshakes:
    """Unfinished handshakes, per connection, for a backend with
    step(ctx, token) -> (done, out_token, ctx, user) and drop(ctx)."""

    TTL = 60.0

    def __init__(self, backend):
        self.backend = backend
        self.pending: dict[tuple, tuple[object, float]] = {}
        self.lock = threading.Lock()

    def step(self, connection: tuple, token_b64: str) -> tuple[bool, str | None, str | None]:
        """(done, token to send back (base64) or None, user when done)."""
        try:
            token = base64.b64decode(token_b64.strip(), validate=True)
        except ValueError:
            raise AuthError("ugyldig innloggingsdata fra nettleseren") from None
        with self.lock:
            now = time.monotonic()
            for key in [k for k, (_, t) in self.pending.items() if now - t > self.TTL]:
                self.backend.drop(self.pending.pop(key)[0])
            ctx = self.pending.pop(connection, (None, 0))[0]
        try:
            done, out, ctx, user = self.backend.step(ctx, token)
        except AuthError:
            raise
        if not done:
            with self.lock:
                self.pending[connection] = (ctx, time.monotonic())
        return done, base64.b64encode(out).decode() if out else None, user


_server_handshakes: Handshakes | None = None


def handshakes() -> Handshakes:
    """The process-wide handshake keeper (Windows only)."""
    global _server_handshakes
    if _server_handshakes is None:
        if SSPIServer is None:
            raise AuthError("Windows-innlogging virker bare når appen kjører på Windows.")
        _server_handshakes = Handshakes(SSPIServer())
    return _server_handshakes


def selftest(target: str = "localhost") -> str:  # pragma: no cover - Windows only
    """A full client↔server handshake inside this process. Returns the user
    name Windows reports, or raises AuthError with the reason."""
    if SSPIServer is None:
        raise AuthError("Testen må kjøres på Windows-PC-en.")
    server = SSPIServer()
    client_cred = _credentials(SECPKG_CRED_OUTBOUND)
    client_ctx = server_ctx = None
    token = None
    for _ in range(6):
        more, token, client_ctx = _client_step(client_cred, client_ctx, token, target)
        done, token, server_ctx, user = server.step(server_ctx, token)
        if done:
            return user
        if not more and not token:
            break
    raise AuthError("Håndtrykket ble ikke ferdig.")
