"""
鼠标操作录制监控器 - 基于 Windows 低级鼠标钩子 (WH_MOUSE_LL)

支持录制：左键、右键、中键、侧键(X1/X2)、滚轮、滑动轨迹。
"""

import ctypes
import ctypes.wintypes as wintypes
import threading
import time
from PyQt6.QtCore import QObject, pyqtSignal

# ── Windows API（使用独立实例，避免与全局 windll 的 argtypes 冲突）──
_user32 = ctypes.WinDLL('user32', use_last_error=True)
_kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)

# ── 常量 ──────────────────────────────────────────────────────────
WH_MOUSE_LL = 14
WM_QUIT = 0x0012

WM_LBUTTONDOWN = 0x0201
WM_LBUTTONUP = 0x0202
WM_RBUTTONDOWN = 0x0204
WM_RBUTTONUP = 0x0205
WM_MBUTTONDOWN = 0x0207
WM_MBUTTONUP = 0x0208
WM_MOUSEWHEEL = 0x020A
WM_MOUSEHWHEEL = 0x020E
WM_XBUTTONDOWN = 0x020B
WM_XBUTTONUP = 0x020C
WM_MOUSEMOVE = 0x0200

# XBUTTON 编号（在 MSLLHOOKSTRUCT.mouseData 的高 16 位）
XBUTTON1 = 1
XBUTTON2 = 2

# ── MSLLHOOKSTRUCT 结构体 ────────────────────────────────────────
class MSLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [
        ("pt", wintypes.POINT),
        ("mouseData", wintypes.DWORD),
        ("flags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
    ]


LRESULT = ctypes.c_longlong

LowLevelMouseProc = ctypes.CFUNCTYPE(
    LRESULT,
    ctypes.c_int,
    wintypes.WPARAM,
    wintypes.LPARAM,
)

# ── Win32 API 签名 ───────────────────────────────────────────────
_user32.SetWindowsHookExW.argtypes = [
    ctypes.c_int, LowLevelMouseProc, wintypes.HINSTANCE, wintypes.DWORD
]
_user32.SetWindowsHookExW.restype = ctypes.c_void_p

_user32.CallNextHookEx.argtypes = [
    ctypes.c_void_p, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM
]
_user32.CallNextHookEx.restype = LRESULT

_user32.UnhookWindowsHookEx.argtypes = [ctypes.c_void_p]
_user32.UnhookWindowsHookEx.restype = wintypes.BOOL

_user32.PeekMessageW.argtypes = [
    ctypes.POINTER(wintypes.MSG), wintypes.HWND,
    ctypes.c_uint, ctypes.c_uint, ctypes.c_uint,
]
_user32.PeekMessageW.restype = wintypes.BOOL

_user32.TranslateMessage.argtypes = [ctypes.POINTER(wintypes.MSG)]
_user32.TranslateMessage.restype = wintypes.BOOL

_user32.DispatchMessageW.argtypes = [ctypes.POINTER(wintypes.MSG)]
_user32.DispatchMessageW.restype = LRESULT

_user32.PostThreadMessageW.argtypes = [
    wintypes.DWORD, ctypes.c_uint, wintypes.WPARAM, wintypes.LPARAM
]
_user32.PostThreadMessageW.restype = wintypes.BOOL

_kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
_kernel32.GetModuleHandleW.restype = wintypes.HMODULE

_kernel32.GetCurrentThreadId.argtypes = []
_kernel32.GetCurrentThreadId.restype = wintypes.DWORD

# ── 按钮消息 → 按钮名称 / 方向 映射 ─────────────────────────────
_DOWN_MESSAGES = {WM_LBUTTONDOWN, WM_RBUTTONDOWN, WM_MBUTTONDOWN, WM_XBUTTONDOWN}
_UP_MESSAGES = {WM_LBUTTONUP, WM_RBUTTONUP, WM_MBUTTONUP, WM_XBUTTONUP}

_BUTTON_NAME = {
    WM_LBUTTONDOWN: "left", WM_LBUTTONUP: "left",
    WM_RBUTTONDOWN: "right", WM_RBUTTONUP: "right",
    WM_MBUTTONDOWN: "middle", WM_MBUTTONUP: "middle",
}


def _get_button_name(wParam, mouseData):
    """根据消息类型和 mouseData 获取按钮名称"""
    name = _BUTTON_NAME.get(wParam)
    if name:
        return name
    # XBUTTON
    if wParam in (WM_XBUTTONDOWN, WM_XBUTTONUP):
        xbutton = (mouseData >> 16) & 0xFFFF
        if xbutton == XBUTTON1:
            return "x1"
        elif xbutton == XBUTTON2:
            return "x2"
    return "unknown"


class MouseMonitor(QObject):
    """鼠标操作录制监控器 — 基于 Windows 低级鼠标钩子 (WH_MOUSE_LL)

    支持录制所有鼠标按键（左/右/中/X1/X2）、滚轮、滑动轨迹。
    """

    action_captured = pyqtSignal(dict)

    def __init__(self, window_mgr):
        super().__init__()
        self.window_mgr = window_mgr

        self._running = False
        self._monitor_thread: threading.Thread | None = None
        self._thread_id: int | None = None
        self._hook_handle = None
        self._hook_proc = None

        # 时间
        self._start_time: float | None = None

        # 按钮状态跟踪  {button_name: (down_time_ms, screen_x, screen_y, win_x, win_y)}
        self._button_state: dict[str, tuple] = {}

        # 滑动轨迹（仅左键拖拽时记录）
        self._swipe_trajectory: list[tuple] = []
        self._min_trajectory_distance = 5

        # 随机化设置（录制时不启用，仅保存配置）
        self.enable_randomization = False
        self.position_random_range = 0.01

    # ── 公共接口 ──────────────────────────────────────────────────

    def start_monitoring(self) -> bool:
        """开始监控"""
        if not self.window_mgr.is_target_valid():
            print("[MouseMonitor] 目标窗口无效")
            return False

        if self._running:
            print("[MouseMonitor] 已在运行中")
            return False

        self._running = True
        self._start_time = time.perf_counter()
        self._button_state.clear()
        self._swipe_trajectory.clear()

        self._monitor_thread = threading.Thread(
            target=self._monitor_loop, daemon=True, name="MouseMonitorThread"
        )
        self._monitor_thread.start()
        return True

    def stop_monitoring(self):
        """停止监控"""
        if not self._running:
            return

        self._running = False

        if self._thread_id is not None:
            _user32.PostThreadMessageW(self._thread_id, WM_QUIT, 0, 0)

        if self._monitor_thread and self._monitor_thread.is_alive():
            self._monitor_thread.join(timeout=2)

        self._thread_id = None
        self._monitor_thread = None
        self._button_state.clear()
        self._swipe_trajectory.clear()

        print("[MouseMonitor] 鼠标监控已停止")

    def set_randomization(self, enabled, position_range=0.01, *args):
        """设置随机化参数（录制时不启用，仅保存配置）"""
        self.enable_randomization = False
        self.position_random_range = position_range

    # ── 时间工具 ──────────────────────────────────────────────────

    def get_time_ms(self) -> int:
        if self._start_time is None:
            self._start_time = time.perf_counter()
            return 0
        return int((time.perf_counter() - self._start_time) * 1000)

    # ── 核心监控循环 ──────────────────────────────────────────────

    def _monitor_loop(self):
        self._thread_id = _kernel32.GetCurrentThreadId()

        self._hook_proc = LowLevelMouseProc(self._low_level_callback)

        self._hook_handle = _user32.SetWindowsHookExW(
            WH_MOUSE_LL,
            self._hook_proc,
            _kernel32.GetModuleHandleW(None),
            0,
        )

        if not self._hook_handle:
            err = ctypes.get_last_error()
            print(f"[MouseMonitor] SetWindowsHookExW 失败, error={err}")
            self._running = False
            return

        print(f"[MouseMonitor] 鼠标钩子已安装, handle={self._hook_handle}")

        msg = wintypes.MSG()
        PM_REMOVE = 0x0001
        while self._running:
            while _user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, PM_REMOVE):
                if msg.message == WM_QUIT:
                    self._running = False
                    break
                _user32.TranslateMessage(ctypes.byref(msg))
                _user32.DispatchMessageW(ctypes.byref(msg))
            if self._running:
                time.sleep(0.001)

        if self._hook_handle:
            _user32.UnhookWindowsHookEx(self._hook_handle)
            self._hook_handle = None
            print("[MouseMonitor] 鼠标钩子已卸载")

    # ── 低级回调 ──────────────────────────────────────────────────

    def _low_level_callback(self, nCode, wParam, lParam):
        if nCode >= 0:
            try:
                ms = ctypes.cast(lParam, ctypes.POINTER(MSLLHOOKSTRUCT)).contents
                screen_x = ms.pt.x
                screen_y = ms.pt.y
                mouseData = ms.mouseData

                # 只处理目标窗口内的事件
                if self.window_mgr.is_point_in_target(screen_x, screen_y):
                    self._dispatch_event(wParam, screen_x, screen_y, mouseData)
                else:
                    # 鼠标移出窗口时，如果有按钮按下，取消跟踪
                    if wParam in _UP_MESSAGES:
                        btn = _get_button_name(wParam, mouseData)
                        self._button_state.pop(btn, None)
                        if btn == "left":
                            self._swipe_trajectory.clear()

            except Exception as e:
                print(f"[MouseMonitor] 回调异常: {e}")

        return _user32.CallNextHookEx(self._hook_handle, nCode, wParam, lParam)

    # ── 事件分发 ──────────────────────────────────────────────────

    def _dispatch_event(self, wParam, screen_x, screen_y, mouseData):
        if wParam in _DOWN_MESSAGES:
            self._on_button_down(wParam, screen_x, screen_y, mouseData)

        elif wParam in _UP_MESSAGES:
            self._on_button_up(wParam, screen_x, screen_y, mouseData)

        elif wParam == WM_MOUSEMOVE:
            self._on_mouse_move(screen_x, screen_y)

        elif wParam in (WM_MOUSEWHEEL, WM_MOUSEHWHEEL):
            self._on_scroll(wParam, screen_x, screen_y, mouseData)

    # ── 按钮按下 ─────────────────────────────────────────────────

    def _on_button_down(self, wParam, screen_x, screen_y, mouseData):
        btn = _get_button_name(wParam, mouseData)
        win_x, win_y = self.window_mgr.screen_to_window(screen_x, screen_y)
        now = self.get_time_ms()

        self._button_state[btn] = (now, screen_x, screen_y, win_x, win_y)

        # 左键按下时开始记录轨迹
        if btn == "left":
            self._swipe_trajectory = [(win_x, win_y, now)]

        print(f"[MouseMonitor] ↓ {btn} ({win_x}, {win_y}) @ {now}ms")

    # ── 按钮释放 ─────────────────────────────────────────────────

    def _on_button_up(self, wParam, screen_x, screen_y, mouseData):
        btn = _get_button_name(wParam, mouseData)
        state = self._button_state.pop(btn, None)
        if state is None:
            return

        down_time, start_sx, start_sy, start_wx, start_wy = state
        win_x, win_y = self.window_mgr.screen_to_window(screen_x, screen_y)
        now = self.get_time_ms()
        duration = now - down_time

        move_distance = ((screen_x - start_sx) ** 2 + (screen_y - start_sy) ** 2) ** 0.5

        action = None

        if btn == "left":
            # 左键：区分点击 / 长按 / 滑动
            if move_distance > 10:
                # 滑动
                if self._swipe_trajectory and (win_x, win_y, now) not in self._swipe_trajectory:
                    self._swipe_trajectory.append((win_x, win_y, now))

                from core.trajectory_utils import simplify_trajectory
                simplified = (
                    simplify_trajectory(self._swipe_trajectory)
                    if len(self._swipe_trajectory) > 2
                    else self._swipe_trajectory
                )

                action = {
                    'type': 'swipe',
                    'button': 'left',
                    'x1': start_wx, 'y1': start_wy,
                    'x2': win_x, 'y2': win_y,
                    'start_time_ms': down_time,
                    'end_time_ms': now,
                    'duration': duration,
                    'trajectory': simplified,
                }
            elif duration >= 500:
                action = {
                    'type': 'long_click',
                    'button': 'left',
                    'x': win_x, 'y': win_y,
                    'start_time_ms': down_time,
                    'end_time_ms': now,
                    'duration': duration,
                }
            else:
                action = {
                    'type': 'click',
                    'button': 'left',
                    'x': win_x, 'y': win_y,
                    'start_time_ms': down_time,
                    'end_time_ms': now,
                    'duration': 0,
                }
            self._swipe_trajectory.clear()

        else:
            # 右键 / 中键 / 侧键：统一为 click（带 button 字段）
            action = {
                'type': 'click',
                'button': btn,
                'x': win_x, 'y': win_y,
                'start_time_ms': down_time,
                'end_time_ms': now,
                'duration': duration,
            }

        if action:
            print(f"[MouseMonitor] ↑ {btn} → {action['type']} @ {now}ms")
            self.action_captured.emit(action)

    # ── 鼠标移动（拖拽轨迹）────────────────────────────────────

    def _on_mouse_move(self, screen_x, screen_y):
        # 仅在左键按下时记录轨迹
        if "left" not in self._button_state:
            return

        win_x, win_y = self.window_mgr.screen_to_window(screen_x, screen_y)

        if self._swipe_trajectory:
            last_x, last_y, _ = self._swipe_trajectory[-1]
            distance = ((win_x - last_x) ** 2 + (win_y - last_y) ** 2) ** 0.5
            if distance >= self._min_trajectory_distance:
                self._swipe_trajectory.append((win_x, win_y, self.get_time_ms()))

    # ── 滚轮 ─────────────────────────────────────────────────────

    def _on_scroll(self, wParam, screen_x, screen_y, mouseData):
        # mouseData 高 16 位是有符号的滚动量
        raw = ctypes.c_short((mouseData >> 16) & 0xFFFF).value
        win_x, win_y = self.window_mgr.screen_to_window(screen_x, screen_y)
        now = self.get_time_ms()

        is_horizontal = (wParam == WM_MOUSEHWHEEL)

        action = {
            'type': 'scroll',
            'x': win_x,
            'y': win_y,
            'delta': raw,
            'horizontal': is_horizontal,
            'start_time_ms': now,
            'end_time_ms': now,
        }

        direction = "←" if is_horizontal and raw < 0 else "→" if is_horizontal else "↑" if raw > 0 else "↓"
        print(f"[MouseMonitor] 🖱 scroll {direction} delta={raw} ({win_x}, {win_y}) @ {now}ms")
        self.action_captured.emit(action)
