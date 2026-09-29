"""Small Windows DPAPI wrapper for app-local credentials."""

from __future__ import annotations

import base64
import ctypes
from ctypes import POINTER, Structure, byref, c_ubyte, c_void_p, c_wchar_p
from ctypes.wintypes import DWORD


_CRYPTPROTECT_UI_FORBIDDEN = 0x1
_MAX_SECRET_BYTES = 16 * 1024


class _DataBlob(Structure):
    _fields_ = [("cbData", DWORD), ("pbData", POINTER(c_ubyte))]


def _windows_crypto() -> tuple[object, object]:
    try:
        crypt32 = ctypes.WinDLL("crypt32.dll", use_last_error=True)
        kernel32 = ctypes.WinDLL("kernel32.dll", use_last_error=True)
    except (AttributeError, OSError) as exc:
        raise ValueError("Windows 用户加密服务不可用。") from exc
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


def protect_text(value: str, *, purpose: bytes) -> str:
    if not isinstance(value, str) or not isinstance(purpose, bytes) or not purpose:
        raise ValueError("本机登录信息无效。")
    try:
        plaintext = value.encode("utf-8", errors="strict")
    except UnicodeError as exc:
        raise ValueError("本机登录信息编码无效。") from exc
    if not plaintext or len(plaintext) > _MAX_SECRET_BYTES or len(purpose) > 256:
        raise ValueError("本机登录信息超出长度限制。")
    crypt32, kernel32 = _windows_crypto()
    input_blob, input_storage = _blob(plaintext)
    entropy_blob, entropy_storage = _blob(purpose)
    output_blob = _DataBlob()
    try:
        ok = crypt32.CryptProtectData(
            byref(input_blob), "FLUKE protected setting", byref(entropy_blob),
            None, None, _CRYPTPROTECT_UI_FORBIDDEN, byref(output_blob),
        )
        if not ok:
            raise OSError(ctypes.get_last_error(), "CryptProtectData failed")
        ciphertext = ctypes.string_at(output_blob.pbData, output_blob.cbData)
        return base64.urlsafe_b64encode(ciphertext).decode("ascii")
    except OSError as exc:
        raise ValueError("无法加密保存本机登录信息。") from exc
    finally:
        if output_blob.pbData:
            kernel32.LocalFree(ctypes.cast(output_blob.pbData, c_void_p))
        _ = input_storage, entropy_storage


def unprotect_text(value: object, *, purpose: bytes) -> str:
    if not isinstance(value, str) or not value or len(value) > 65_536:
        raise ValueError("本机登录信息无法解密，请重新设置。")
    if not isinstance(purpose, bytes) or not purpose or len(purpose) > 256:
        raise ValueError("本机加密用途无效。")
    try:
        ciphertext = base64.b64decode(value.encode("ascii"), altchars=b"-_", validate=True)
    except (UnicodeError, ValueError) as exc:
        raise ValueError("本机登录信息无法解密，请重新设置。") from exc
    crypt32, kernel32 = _windows_crypto()
    input_blob, input_storage = _blob(ciphertext)
    entropy_blob, entropy_storage = _blob(purpose)
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
        raise ValueError("本机登录信息无法解密，请重新设置。") from exc
    finally:
        if output_blob.pbData:
            kernel32.LocalFree(ctypes.cast(output_blob.pbData, c_void_p))
        if description:
            kernel32.LocalFree(ctypes.cast(description, c_void_p))
        _ = input_storage, entropy_storage
