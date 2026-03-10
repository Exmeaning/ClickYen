"""
键盘操作录制监控器 - 基于 Windows 低级键盘钩子 (WH_KEYBOARD_LL)

使用 SetWindowsHookExW 拦截键盘事件，不与 InterceptionManager 的发送功能冲突。
"""

import ctypes
import ctypes.wintypes as wintypes
import threading
import time
from PyQt6.QtCore import QObject, pyqtSignal

# ── Windows API（使用独立实例，避免与全局 windll 的 argtypes 冲突）──
user32 = ctypes.WinDLL('user32', use_last_error=True)
kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)

WH_KEYBOARD_LL = 13
WM_KEYDOWN = 0x0100
WM_KEYUP = 0x0101
WM_SYSKEYDOWN = 0x0104
WM_SYSKEYUP = 0x0105
WM_QUIT = 0x0012

# KBDLLHOOKSTRUCT flags
LLKHF_EXTENDED = 0x01
LLKHF_ALTDOWN = 0x20
LLKHF_UP = 0x80

# 系统键虚拟键码
VK_LWIN = 0x5B
VK_RWIN = 0x5C
VK_LMENU = 0xA4  # Left Alt
VK_RMENU = 0xA5  # Right Alt
VK_TAB = 0x09


# ── KBDLLHOOKSTRUCT 结构体 ───────────────────────────────────────
class KBDLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [
        ("vkCode", wintypes.DWORD),
        ("scanCode", wintypes.DWORD),
        ("flags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
    ]


# 64 位 Windows 上 LRESULT 是 8 字节
LRESULT = ctypes.c_longlong

# 回调函数类型
LowLevelKeyboardProc = ctypes.CFUNCTYPE(
    LRESULT,             # 返回值 LRESULT（必须 8 字节，否则钩子链断裂）
    ctypes.c_int,        # nCode
    wintypes.WPARAM,     # wParam
    wintypes.LPARAM,     # lParam
)

# ── 设置 Win32 API 签名（防止 64 位指针截断）────────────────
user32.SetWindowsHookExW.argtypes = [
    ctypes.c_int, LowLevelKeyboardProc, wintypes.HINSTANCE, wintypes.DWORD
]
user32.SetWindowsHookExW.restype = ctypes.c_void_p

user32.CallNextHookEx.argtypes = [
    ctypes.c_void_p, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM
]
user32.CallNextHookEx.restype = LRESULT

user32.UnhookWindowsHookEx.argtypes = [ctypes.c_void_p]
user32.UnhookWindowsHookEx.restype = wintypes.BOOL

user32.GetMessageW.argtypes = [
    ctypes.POINTER(wintypes.MSG), wintypes.HWND, ctypes.c_uint, ctypes.c_uint
]
user32.GetMessageW.restype = ctypes.c_int

user32.PostThreadMessageW.argtypes = [wintypes.DWORD, ctypes.c_uint, wintypes.WPARAM, wintypes.LPARAM]
user32.PostThreadMessageW.restype = wintypes.BOOL

user32.TranslateMessage.argtypes = [ctypes.POINTER(wintypes.MSG)]
user32.TranslateMessage.restype = wintypes.BOOL

user32.DispatchMessageW.argtypes = [ctypes.POINTER(wintypes.MSG)]
user32.DispatchMessageW.restype = LRESULT

user32.PeekMessageW.argtypes = [
    ctypes.POINTER(wintypes.MSG), wintypes.HWND, ctypes.c_uint, ctypes.c_uint, ctypes.c_uint
]
user32.PeekMessageW.restype = wintypes.BOOL

kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
kernel32.GetModuleHandleW.restype = wintypes.HMODULE

kernel32.GetCurrentThreadId.argtypes = []
kernel32.GetCurrentThreadId.restype = wintypes.DWORD

user32.MapVirtualKeyW.argtypes = [ctypes.c_uint, ctypes.c_uint]
user32.MapVirtualKeyW.restype = ctypes.c_uint

user32.GetKeyNameTextW.argtypes = [ctypes.c_long, ctypes.c_wchar_p, ctypes.c_int]
user32.GetKeyNameTextW.restype = ctypes.c_int

# ── 虚拟键码 → 键名映射表 ────────────────────────────────────────
_VK_NAME_MAP = {
    0x08: "Backspace", 0x09: "Tab", 0x0D: "Enter", 0x10: "Shift",
    0x11: "Ctrl", 0x12: "Alt", 0x13: "Pause", 0x14: "CapsLock",
    0x1B: "Esc", 0x20: "Space", 0x21: "PageUp", 0x22: "PageDown",
    0x23: "End", 0x24: "Home", 0x25: "Left", 0x26: "Up",
    0x27: "Right", 0x28: "Down", 0x2C: "PrintScreen", 0x2D: "Insert",
    0x2E: "Delete", 0x5B: "LWin", 0x5C: "RWin", 0x5D: "Apps",
    0x60: "Num0", 0x61: "Num1", 0x62: "Num2", 0x63: "Num3",
    0x64: "Num4", 0x65: "Num5", 0x66: "Num6", 0x67: "Num7",
    0x68: "Num8", 0x69: "Num9", 0x6A: "Num*", 0x6B: "Num+",
    0x6C: "NumSeparator", 0x6D: "Num-", 0x6E: "Num.", 0x6F: "Num/",
    0x90: "NumLock", 0x91: "ScrollLock",
    0xA0: "LShift", 0xA1: "RShift", 0xA2: "LCtrl", 0xA3: "RCtrl",
    0xA4: "LAlt", 0xA5: "RAlt",
    0xBA: ";", 0xBB: "=", 0xBC: ",", 0xBD: "-",
    0xBE: ".", 0xBF: "/", 0xC0: "`",
    0xDB: "[", 0xDC: "\\", 0xDD: "]", 0xDE: "'",
}

# F1-F12
for _i in range(12):
    _VK_NAME_MAP[0x70 + _i] = f"F{_i + 1}"

# 0-9
for _i in range(10):
    _VK_NAME_MAP[0x30 + _i] = str(_i)

# A-Z
for _i in range(26):
    _VK_NAME_MAP[0x41 + _i] = chr(0x41 + _i)


class KeyboardMonitor(QObject):
    """键盘操作录制监控器 — 基于 Windows 低级键盘钩子"""

    # ── 信号 ──────────────────────────────────────────────────────
    action_captured = pyqtSignal(dict)
    monitoring_started = pyqtSignal()
    monitoring_stopped = pyqtSignal()

    def __init__(self):
        super().__init__()
        self._running = False
        self._monitor_thread: threading.Thread | None = None
        self._thread_id: int | None = None
        self._start_time: float | None = None          # perf_counter 起始
        self._pressed_keys: dict[int, int] = {}        # {vk_code: press_time_ms}
        self._filter_system_keys = True
        self._filter_vk_codes: set[int] = set()        # 需要过滤的额外 VK 码

        # 钩子句柄（线程内使用）
        self._hook_handle = None
        # 必须持有回调引用，防止被 GC 回收
        self._hook_proc = None

    # ── 公共接口 ──────────────────────────────────────────────────

    def start_monitoring(self) -> bool:
        """启动键盘监控，返回是否成功"""
        if self._running:
            print("[KeyboardMonitor] 已在运行中")
            return False

        self._running = True
        self._start_time = time.perf_counter()
        self._pressed_keys.clear()

        self._monitor_thread = threading.Thread(
            target=self._monitor_loop, daemon=True, name="KeyboardMonitorThread"
        )
        self._monitor_thread.start()

        print("[KeyboardMonitor] 键盘监控已启动")
        self.monitoring_started.emit()
        return True

    def stop_monitoring(self):
        """停止键盘监控"""
        if not self._running:
            return

        self._running = False

        # 向监控线程发送 WM_QUIT 以退出 GetMessage 循环
        if self._thread_id is not None:
            user32.PostThreadMessageW(self._thread_id, WM_QUIT, 0, 0)

        if self._monitor_thread and self._monitor_thread.is_alive():
            self._monitor_thread.join(timeout=2)

        self._thread_id = None
        self._monitor_thread = None
        self._pressed_keys.clear()

        print("[KeyboardMonitor] 键盘监控已停止")
        self.monitoring_stopped.emit()

    def set_filter_system_keys(self, enabled: bool):
        """设置是否过滤系统键（Win / Alt+Tab 等）"""
        self._filter_system_keys = enabled

    def set_filter_vk_codes(self, vk_codes: set[int]):
        """设置需要过滤的额外 VK 码（如录制快捷键 F9）"""
        self._filter_vk_codes = vk_codes

    # ── 时间工具 ──────────────────────────────────────────────────

    def _get_time_ms(self) -> int:
        """获取相对于录制开始的毫秒时间戳"""
        if self._start_time is None:
            self._start_time = time.perf_counter()
            return 0
        return int((time.perf_counter() - self._start_time) * 1000)

    # ── 核心监控循环 ──────────────────────────────────────────────

    def _monitor_loop(self):
        """在独立线程中安装低级键盘钩子并运行消息循环"""
        # 记录线程 ID，用于 PostThreadMessage 退出
        self._thread_id = kernel32.GetCurrentThreadId()

        # 创建回调（必须保持引用）
        self._hook_proc = LowLevelKeyboardProc(self._low_level_callback)

        # 安装钩子
        self._hook_handle = user32.SetWindowsHookExW(
            WH_KEYBOARD_LL,
            self._hook_proc,
            kernel32.GetModuleHandleW(None),
            0,
        )

        if not self._hook_handle:
            err = ctypes.get_last_error()
            print(f"[KeyboardMonitor] SetWindowsHookExW 失败, error={err}")
            self._running = False
            return

        print(f"[KeyboardMonitor] 钩子已安装, handle={self._hook_handle}")

        # 消息循环 —— 使用 PeekMessageW 非阻塞轮询
        # 注意：GetMessageW 在 PyQt6 事件循环并存时会导致低级钩子回调无法触发，
        # 必须用 PeekMessageW + sleep 的方式泵送消息。
        msg = wintypes.MSG()
        PM_REMOVE = 0x0001
        while self._running:
            while user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, PM_REMOVE):
                if msg.message == WM_QUIT:
                    self._running = False
                    break
                user32.TranslateMessage(ctypes.byref(msg))
                user32.DispatchMessageW(ctypes.byref(msg))
            if self._running:
                time.sleep(0.001)  # 1ms 轮询，避免 CPU 空转

        # 卸载钩子
        if self._hook_handle:
            user32.UnhookWindowsHookEx(self._hook_handle)
            self._hook_handle = None
            print("[KeyboardMonitor] 钩子已卸载")

    def _low_level_callback(self, nCode, wParam, lParam):
        """WH_KEYBOARD_LL 回调函数"""
        if nCode >= 0:
            try:
                kb = ctypes.cast(lParam, ctypes.POINTER(KBDLLHOOKSTRUCT)).contents
                vk_code = kb.vkCode
                scan_code = kb.scanCode
                flags = kb.flags

                # 扩展键标志 → 合并到 scan_code 高位
                is_extended = bool(flags & LLKHF_EXTENDED)
                if is_extended:
                    scan_code |= 0xE000

                is_down = wParam in (WM_KEYDOWN, WM_SYSKEYDOWN)

                self._process_key_event(vk_code, scan_code, flags, is_down)
            except Exception as e:
                print(f"[KeyboardMonitor] 回调异常: {e}")

        # 必须透传给下一个钩子
        return user32.CallNextHookEx(self._hook_handle, nCode, wParam, lParam)

    # ── 事件处理 ──────────────────────────────────────────────────

    def _process_key_event(self, vk_code: int, scan_code: int, flags: int, is_down: bool):
        """处理单个键盘事件，生成 action dict 并发射信号"""

        # 过滤系统键
        if self._filter_system_keys and self._is_system_key(vk_code, flags):
            return

        # 过滤指定的 VK 码（如录制快捷键）
        if vk_code in self._filter_vk_codes:
            return

        timestamp_ms = self._get_time_ms()
        key_name = self._get_key_name(vk_code)

        if is_down:
            # 避免重复的 key_down（按住不放时系统会重复发送）
            if vk_code in self._pressed_keys:
                return

            self._pressed_keys[vk_code] = timestamp_ms

            action = {
                "type": "key_down",
                "scan_code": scan_code,
                "vk_code": vk_code,
                "key_name": key_name,
                "start_time_ms": timestamp_ms,
            }
            print(f"[KeyboardMonitor] ↓ {key_name} (vk=0x{vk_code:02X}, sc=0x{scan_code:04X}) @ {timestamp_ms}ms")
            self.action_captured.emit(action)

        else:
            # key_up
            press_time = self._pressed_keys.pop(vk_code, None)
            hold_duration = (timestamp_ms - press_time) if press_time is not None else 0

            action = {
                "type": "key_up",
                "scan_code": scan_code,
                "vk_code": vk_code,
                "key_name": key_name,
                "start_time_ms": timestamp_ms,
                "hold_duration_ms": hold_duration,
            }
            print(f"[KeyboardMonitor] ↑ {key_name} (hold={hold_duration}ms) @ {timestamp_ms}ms")
            self.action_captured.emit(action)

    # ── 辅助方法 ──────────────────────────────────────────────────

    @staticmethod
    def _get_key_name(vk_code: int) -> str:
        """获取人类可读的键名"""
        name = _VK_NAME_MAP.get(vk_code)
        if name:
            return name
        # 回退：尝试用 MapVirtualKeyW + GetKeyNameTextW
        try:
            scan = user32.MapVirtualKeyW(vk_code, 0)  # MAPVK_VK_TO_VSC
            if scan:
                buf = ctypes.create_unicode_buffer(64)
                # lParam for GetKeyNameTextW: scan code in bits 16-23
                lparam = scan << 16
                ret = user32.GetKeyNameTextW(lparam, buf, 64)
                if ret:
                    return buf.value
        except Exception:
            pass
        return f"VK_0x{vk_code:02X}"

    def _is_system_key(self, vk_code: int, flags: int) -> bool:
        """判断是否为需要过滤的系统键"""
        # Win 键
        if vk_code in (VK_LWIN, VK_RWIN):
            return True
        # Alt+Tab 组合：Alt 按下时按 Tab
        if vk_code == VK_TAB and (flags & LLKHF_ALTDOWN):
            return True
        return False
