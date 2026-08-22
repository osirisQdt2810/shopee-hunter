"""Frameless, translucent window chrome — and the per-OS blur behind it.

Done once, here, because window flags and native effects are exactly the kind of thing that
rots when every component touches them. Components get a rounded, translucent surface to
draw on and never ask which OS they are on.

The rule that keeps this honest: **every visual must remain legible with the blur absent.**
macOS gives real vibrancy, Windows 11 gives acrylic/mica, Windows 10 gives neither, and a
Linux compositor may give nothing at all. So the QML paints its own gradient scrim
underneath; native blur is an enhancement layered on top, never a dependency.
"""

from __future__ import annotations

import ctypes
import os
import sys
from ctypes import wintypes
from typing import Optional

from PySide6.QtCore import QObject, Qt, Slot
from PySide6.QtGui import QColor, QGuiApplication
from PySide6.QtQuick import QQuickWindow

from ..core.logging import get_logger

log = get_logger("gui.window")

# --- Windows DWM constants (dwmapi.h). Named rather than inlined so the calls below read.
_DWMWA_USE_IMMERSIVE_DARK_MODE = 20
_DWMWA_SYSTEMBACKDROP_TYPE = 38
_DWMSBT_TRANSIENTWINDOW = 3  # "Acrylic": the translucent, blurred backdrop we want
_DWMWA_WINDOW_CORNER_PREFERENCE = 33
_DWMWCP_ROUND = 2


class WindowEffects(QObject):
    """Applies native translucency to a QQuickWindow, with a documented fallback.

    Exposed to QML as ``windowEffects`` so ``AppWindow.qml`` can ask whether native blur
    actually took effect and adjust its own scrim opacity accordingly.
    """

    def __init__(self, parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self._native_blur = False

    @property
    def native_blur_active(self) -> bool:
        return self._native_blur

    @Slot(result=bool)
    def hasNativeBlur(
        self,
    ) -> bool:
        return self._native_blur

    @Slot(result=str)
    def platformName(self) -> str:
        return sys.platform

    def apply(self, window: QQuickWindow, *, translucent: bool = True) -> bool:
        """Make ``window`` translucent and blur what is behind it, if the OS can.

        Returns:
            True when a *native* blur was installed. False means the QML scrim is carrying
            the whole look — which it is designed to do.
        """
        if not translucent:
            return False

        # Qt-level transparency has to be set regardless of platform: without it the native
        # blur has nothing to show through, and the rounded corners paint onto grey.
        window.setColor(QColor(0, 0, 0, 0))
        window.setFlag(Qt.FramelessWindowHint, True)

        if sys.platform == "darwin":
            self._native_blur = self._apply_macos(window)
        elif sys.platform == "win32":
            self._native_blur = self._apply_windows(window)
        else:
            log.info(
                "no native window blur on %s; using the painted scrim", sys.platform
            )
            self._native_blur = False
        return self._native_blur

    # -- macOS ------------------------------------------------------------------
    def _apply_macos(self, window: QQuickWindow) -> bool:
        """Ask AppKit for a vibrancy view behind the content.

        Uses pyobjc when it happens to be installed and otherwise degrades: Qt's own
        translucent window on macOS already composites against the desktop, so the painted
        scrim looks close to right without any native call. Adding pyobjc as a hard
        dependency for one nicety is not worth a mandatory wheel.
        """
        try:
            import objc
            from AppKit import (  # type: ignore[import-not-found]
                NSVisualEffectBlendingModeBehindWindow,
                NSVisualEffectMaterialHUDWindow,
                NSVisualEffectView,
            )
        except ImportError:
            log.debug(
                "pyobjc not present; macOS uses Qt translucency + the painted scrim"
            )
            return False

        try:
            import ctypes as _ctypes

            handle = window.winId()
            ns_view = objc.objc_object(c_void_p=_ctypes.c_void_p(int(handle)))
            ns_window = ns_view.window()
            effect = NSVisualEffectView.alloc().initWithFrame_(ns_view.frame())
            effect.setMaterial_(NSVisualEffectMaterialHUDWindow)
            effect.setBlendingMode_(NSVisualEffectBlendingModeBehindWindow)
            effect.setState_(1)  # NSVisualEffectStateActive
            effect.setAutoresizingMask_(18)  # width | height
            content = ns_window.contentView()
            content.addSubview_positioned_relativeTo_(effect, -1, None)  # -1 = below
            ns_window.setOpaque_(False)
            log.info("macOS vibrancy installed")
            return True
        except Exception as exc:
            log.warning("macOS vibrancy unavailable: %s", exc)
            return False

    # -- Windows ----------------------------------------------------------------
    def _apply_windows(self, window: QQuickWindow) -> bool:
        """Ask DWM for the acrylic backdrop, dark title colours, and round corners.

        ``DWMWA_SYSTEMBACKDROP_TYPE`` exists only on Windows 11 build 22621+; on Windows 10
        the call returns a non-zero HRESULT, which is not an error to report — it is the
        documented way to discover the OS cannot do it.
        """
        try:
            dwm = ctypes.windll.dwmapi  # type: ignore[attr-defined]
        except (AttributeError, OSError) as exc:
            log.debug("dwmapi unavailable: %s", exc)
            return False

        hwnd = wintypes.HWND(int(window.winId()))
        applied = False

        def set_attribute(attribute: int, value: int) -> bool:
            data = ctypes.c_int(value)
            result = dwm.DwmSetWindowAttribute(
                hwnd, ctypes.c_uint(attribute), ctypes.byref(data), ctypes.sizeof(data)
            )
            return result == 0

        # Dark mode first: on a light-mode system, skipping this leaves a white 1px frame
        # around an otherwise dark window.
        set_attribute(_DWMWA_USE_IMMERSIVE_DARK_MODE, 1)
        set_attribute(_DWMWA_WINDOW_CORNER_PREFERENCE, _DWMWCP_ROUND)
        if set_attribute(_DWMWA_SYSTEMBACKDROP_TYPE, _DWMSBT_TRANSIENTWINDOW):
            log.info("Windows acrylic backdrop installed")
            applied = True
        else:
            log.info(
                "acrylic backdrop unavailable (pre-Windows 11); using the painted scrim"
            )
        return applied


def configure_graphics() -> None:
    """Pick a rendering setup that behaves the same on both shipping platforms.

    Must run **before** the QGuiApplication exists, which is why it is a module function and
    not a method: Qt reads the high-DPI policy while constructing the application object.

    The scene-graph backend is deliberately NOT forced. Qt picks Metal on macOS and D3D11 on
    Windows, which is what we want; naming a backend explicitly means naming a wrong one on
    some machine. The one exception is a headless run — the `offscreen` platform plugin has
    no GPU surface, so the software renderer is selected there. CI and the screenshot script
    both go down that path, and without it Qt Quick crashes rather than degrading.
    """
    QGuiApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )
    if os.environ.get("QT_QPA_PLATFORM", "").startswith("offscreen"):
        os.environ.setdefault("QT_QUICK_BACKEND", "software")
        QQuickWindow.setSceneGraphBackend("software")
