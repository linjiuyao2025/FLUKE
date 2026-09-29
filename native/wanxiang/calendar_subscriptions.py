from __future__ import annotations

import base64
import ctypes
from ctypes import POINTER, Structure, byref, c_ubyte, c_void_p, c_wchar_p
from ctypes.wintypes import DWORD
from urllib.parse import SplitResult, urlsplit, urlunsplit


class CalendarSubscriptionError(ValueError):
    pass


_MAX_URL_BYTES = 2_048
_DPAPI_ENTROPY = b"FLUKE calendar subscription URL v1"
_CRYPTPROTECT_UI_FORBIDDEN = 0x1


class _DataBlob(Structure):
    _fields_ = [("cbData", DWORD), ("pbData", POINTER(c_ubyte))]


def normalize_subscription_url(value: object) -> tuple[str, str]:
    if not isinstance(value, str):
        raise CalendarSubscriptionError("订阅地址必须是文本。")
    source = value.strip()
    if not source or len(source.encode("utf-8")) > _MAX_URL_BYTES:
        raise CalendarSubscriptionError("订阅地址不能为空，且不能超过 2048 字节。")
    if any(char.isspace() or ord(char) < 32 or ord(char) == 127 for char in source):
        raise CalendarSubscriptionError("订阅地址不能包含空格或控制字符。")
    try:
        parts = urlsplit(source)
        scheme = parts.scheme.casefold()
        if scheme in {"webcal", "webcals"}:
            scheme = "https"
            parts = parts._replace(scheme=scheme)
        elif scheme not in {"http", "https"}:
            raise CalendarSubscriptionError("订阅地址须使用 HTTP、HTTPS 或 webcal。")
        if parts.username is not None or parts.password is not None:
            raise CalendarSubscriptionError("暂不支持把账号密码写在订阅地址中。")
        hostname = parts.hostname
        if not hostname:
            raise CalendarSubscriptionError("订阅地址缺少服务器名称。")
        # Accessing .port also validates malformed or out-of-range ports.
        port = parts.port
        host_ascii = hostname.encode("idna").decode("ascii").casefold()
        if ":" in host_ascii and not host_ascii.startswith("["):
            host_ascii = f"[{host_ascii}]"
        if port is not None:
            host_display = f"{host_ascii}:{port}"
        else:
            host_display = host_ascii
    except CalendarSubscriptionError:
        raise
    except (UnicodeError, ValueError) as exc:
        raise CalendarSubscriptionError("订阅地址格式无效。") from exc
    normalized = urlunsplit(SplitResult(
        scheme=scheme,
        netloc=parts.netloc,
        path=parts.path or "/",
        query=parts.query,
        fragment="",
    ))
    if len(normalized.encode("utf-8")) > _MAX_URL_BYTES:
        raise CalendarSubscriptionError("订阅地址不能超过 2048 字节。")
    return normalized, host_display


def _windows_dpapi() -> tuple[object, object]:
    try:
        crypt32 = ctypes.WinDLL("crypt32.dll", use_last_error=True)
        kernel32 = ctypes.WinDLL("kernel32.dll", use_last_error=True)
    except (AttributeError, OSError) as exc:
        raise CalendarSubscriptionError("日历订阅链接需要 Windows 用户加密服务。") from exc

    crypt32.CryptProtectData.argtypes = [
        POINTER(_DataBlob), c_wchar_p, POINTER(_DataBlob), c_void_p, c_void_p,
        DWORD, POINTER(_DataBlob),
    ]
    crypt32.CryptProtectData.restype = ctypes.c_int
    crypt32.CryptUnprotectData.argtypes = [
        POINTER(_DataBlob), POINTER(c_wchar_p), POINTER(_DataBlob), c_void_p,
        c_void_p, DWORD, POINTER(_DataBlob),
    ]
    crypt32.CryptUnprotectData.restype = ctypes.c_int
    kernel32.LocalFree.argtypes = [c_void_p]
    kernel32.LocalFree.restype = c_void_p
    return crypt32, kernel32


def _blob(data: bytes) -> tuple[_DataBlob, object]:
    storage = (c_ubyte * len(data)).from_buffer_copy(data)
    return _DataBlob(len(data), ctypes.cast(storage, POINTER(c_ubyte))), storage


def protect_subscription_url(value: object) -> str:
    if not isinstance(value, str) or not value:
        raise CalendarSubscriptionError("订阅地址不能为空。")
    try:
        plaintext = value.encode("utf-8", errors="strict")
    except UnicodeError as exc:
        raise CalendarSubscriptionError("订阅地址编码无效。") from exc
    if len(plaintext) > _MAX_URL_BYTES:
        raise CalendarSubscriptionError("订阅地址不能超过 2048 字节。")
    crypt32, kernel32 = _windows_dpapi()
    input_blob, input_storage = _blob(plaintext)
    entropy_blob, entropy_storage = _blob(_DPAPI_ENTROPY)
    output_blob = _DataBlob()
    try:
        ok = crypt32.CryptProtectData(
            byref(input_blob), "FLUKE calendar subscription", byref(entropy_blob),
            None, None, _CRYPTPROTECT_UI_FORBIDDEN, byref(output_blob),
        )
        if not ok:
            raise OSError(ctypes.get_last_error(), "CryptProtectData failed")
        ciphertext = ctypes.string_at(output_blob.pbData, output_blob.cbData)
        return base64.urlsafe_b64encode(ciphertext).decode("ascii")
    except (OSError, UnicodeError) as exc:
        raise CalendarSubscriptionError("无法保护订阅地址，尚未保存。") from exc
    finally:
        if output_blob.pbData:
            kernel32.LocalFree(ctypes.cast(output_blob.pbData, c_void_p))
        # Keep the input buffers alive until CryptProtectData has returned.
        _ = input_storage, entropy_storage


def unprotect_subscription_url(value: object) -> str:
    if not isinstance(value, str) or not value or len(value) > 16_384:
        raise CalendarSubscriptionError("订阅地址无法解密，请在此设备重新添加。")
    try:
        ciphertext = base64.b64decode(value.encode("ascii"), altchars=b"-_", validate=True)
    except (UnicodeError, ValueError) as exc:
        raise CalendarSubscriptionError("订阅地址无法解密，请在此设备重新添加。") from exc
    crypt32, kernel32 = _windows_dpapi()
    input_blob, input_storage = _blob(ciphertext)
    entropy_blob, entropy_storage = _blob(_DPAPI_ENTROPY)
    output_blob = _DataBlob()
    description = c_wchar_p()
    try:
        ok = crypt32.CryptUnprotectData(
            byref(input_blob), byref(description), byref(entropy_blob), None, None,
            _CRYPTPROTECT_UI_FORBIDDEN, byref(output_blob),
        )
        if not ok:
            raise OSError(ctypes.get_last_error(), "CryptUnprotectData failed")
        plaintext = ctypes.string_at(output_blob.pbData, output_blob.cbData)
        return plaintext.decode("utf-8", errors="strict")
    except (OSError, UnicodeError) as exc:
        raise CalendarSubscriptionError("订阅地址无法解密，请在此设备重新添加。") from exc
    finally:
        if output_blob.pbData:
            kernel32.LocalFree(ctypes.cast(output_blob.pbData, c_void_p))
        if description:
            kernel32.LocalFree(ctypes.cast(description, c_void_p))
        _ = input_storage, entropy_storage
