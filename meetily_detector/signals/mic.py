"""Microphone-in-use detection (PRD 5.2.2, confirmation signal).

Uses CoreAudio's `kAudioDevicePropertyDeviceIsRunningSomewhere` on the default
input device — the reliable "actually joined the call" signal, since a Meet tab
can sit in the lobby indefinitely.

Implemented via ctypes against the CoreAudio framework so no native build
dependency is required. On non-macOS platforms (or if CoreAudio cannot be
loaded) `mic_in_use()` returns None ("unknown"), which the caller treats as
not-active so it never spuriously triggers.
"""

from __future__ import annotations

import ctypes
import ctypes.util
import sys

from ..logutil import get_logger

_kAudioObjectSystemObject = 1
_kAudioObjectPropertyElementMain = 0  # was ...ElementMaster pre-macOS 12


def _fourcc(code: str) -> int:
    return (
        (ord(code[0]) << 24)
        | (ord(code[1]) << 16)
        | (ord(code[2]) << 8)
        | ord(code[3])
    )


_kAudioHardwarePropertyDefaultInputDevice = _fourcc("dIn ")
_kAudioDevicePropertyDeviceIsRunningSomewhere = _fourcc("gone")
_kAudioObjectPropertyScopeGlobal = _fourcc("glob")


class _AudioObjectPropertyAddress(ctypes.Structure):
    _fields_ = [
        ("mSelector", ctypes.c_uint32),
        ("mScope", ctypes.c_uint32),
        ("mElement", ctypes.c_uint32),
    ]


_coreaudio = None
_load_attempted = False


def _load_coreaudio():
    global _coreaudio, _load_attempted
    if _load_attempted:
        return _coreaudio
    _load_attempted = True
    if sys.platform != "darwin":
        return None
    path = (
        ctypes.util.find_library("CoreAudio")
        or "/System/Library/Frameworks/CoreAudio.framework/CoreAudio"
    )
    try:
        _coreaudio = ctypes.CDLL(path)
    except OSError as exc:  # pragma: no cover - platform dependent
        get_logger().warning("CoreAudio unavailable: %s", exc)
        _coreaudio = None
    return _coreaudio


def _get_uint32_property(ca, object_id: int, selector: int) -> int | None:
    addr = _AudioObjectPropertyAddress(
        selector, _kAudioObjectPropertyScopeGlobal, _kAudioObjectPropertyElementMain
    )
    out = ctypes.c_uint32(0)
    size = ctypes.c_uint32(ctypes.sizeof(out))
    status = ca.AudioObjectGetPropertyData(
        ctypes.c_uint32(object_id),
        ctypes.byref(addr),
        ctypes.c_uint32(0),
        None,
        ctypes.byref(size),
        ctypes.byref(out),
    )
    if status != 0:
        return None
    return out.value


def mic_in_use(load=_load_coreaudio) -> bool | None:
    """True if the default input device is running somewhere, None if unknown."""
    ca = load()
    if ca is None:
        return None
    device_id = _get_uint32_property(
        ca, _kAudioObjectSystemObject, _kAudioHardwarePropertyDefaultInputDevice
    )
    if not device_id:
        return None
    running = _get_uint32_property(
        ca, device_id, _kAudioDevicePropertyDeviceIsRunningSomewhere
    )
    if running is None:
        return None
    return running != 0
