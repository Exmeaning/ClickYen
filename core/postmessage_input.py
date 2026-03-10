"""
PostMessage 后台输入引擎
通过 Win32 PostMessage/SendMessage 向目标窗口发送鼠标和键盘消息，
完全不移动系统光标，不影响用户的鼠标操作。
"""

import time
import ctypes
import ctypes.wintypes
import threading

import win32gui
import win32con
import win32api


# ============================================================
# Win32 消息常量
# ============================================================
WM_MOUSEMOVE = 0x0200
WM_LBUTTONDOWN = 0x0201
WM_LBUTTONUP = 0x0202
WM_RBUTTONDOWN = 0x0204
WM_RBUTTONUP = 0x0205
WM_MBUTTONDOWN = 0x0207
WM_MBUTTONUP = 0x0208
WM_MOUSEWHEEL = 0x020A

WM_KEYDOWN = 0x0100
WM_KEYUP = 0x0101
WM_CHAR = 0x0102
WM_SYSKEYDOWN = 0x0104
WM_SYSKEYUP = 0x0105

MK_LBUTTON = 0x0001
MK_RBUTTON = 0x0002
MK_MBUTTON = 0x0010

# 按钮 → (down_msg, up_msg, mk_flag)
_BUTTON_MAP = {
    "left":   (WM_LBUTTONDOWN, WM_LBUTTONUP, MK_LBUTTON),
    "right":  (WM_RBUTTONDOWN, WM_RBUTTONUP, MK_RBUTTON),
    "middle": (WM_MBUTTONDOWN, WM_MBUTTONUP, MK_MBUTTON),
}

# Scan Code → VK Code 反向映射（用于 WM_KEYDOWN 的 wParam）
# 从 interception_manager.py 的 VK_TO_SCANCODE 反转
_SCANCODE_TO_VK = {
    # 字母键
    0x1E: 0x41, 0x30: 0x42, 0x2E: 0x43, 0x20: 0x44, 0x12: 0x45,
    0x21: 0x46, 0x22: 0x47, 0x23: 0x48, 0x17: 0x49, 0x24: 0x4A,
    0x25: 0x4B, 0x26: 0x4C, 0x32: 0x4D, 0x31: 0x4E, 0x18: 0x4F,
    0x19: 0x50, 0x10: 0x51, 0x13: 0x52, 0x1F: 0x53, 0x14: 0x54,
    0x16: 0x55, 0x2F: 0x56, 0x11: 0x57, 0x2D: 0x58, 0x15: 0x59,
    0x2C: 0x5A,
    # 数字键
    0x0B: 0x30, 0x02: 0x31, 0x03: 0x32, 0x04: 0x33, 0x05: 0x34,
    0x06: 0x35, 0x07: 0x36, 0x08: 0x37, 0x09: 0x38, 0x0A: 0x39,
    # 功能键
    0x3B: 0x70, 0x3C: 0x71, 0x3D: 0x72, 0x3E: 0x73, 0x3F: 0x74,
    0x40: 0x75, 0x41: 0x76, 0x42: 0x77, 0x43: 0x78, 0x44: 0x79,
    0x57: 0x7A, 0x58: 0x7B,
    # 控制键
    0x01: 0x1B,  # ESC
    0x0F: 0x09,  # TAB
    0x3A: 0x14,  # CAPS LOCK
    0x2A: 0x10,  # SHIFT (左)
    0x1D: 0x11,  # CTRL (左)
    0x38: 0x12,  # ALT (左)
    0x39: 0x20,  # SPACE
    0x1C: 0x0D,  # ENTER
    0x0E: 0x08,  # BACKSPACE
}

# 扩展键 scan code → VK
_EXT_SCANCODE_TO_VK = {
    0xE04B: 0x25,  # LEFT
    0xE048: 0x26,  # UP
    0xE04D: 0x27,  # RIGHT
    0xE050: 0x28,  # DOWN
    0xE052: 0x2D,  # INSERT
    0xE053: 0x2E,  # DELETE
    0xE047: 0x24,  # HOME
    0xE04F: 0x23,  # END
    0xE049: 0x21,  # PAGE UP
    0xE051: 0x22,  # PAGE DOWN
}


def _make_lparam(x, y):
    """将 (x, y) 打包为 lParam（低 16 位 = x，高 16 位 = y）"""
    return (y << 16) | (x & 0xFFFF)


def _make_key_lparam(scan_code, repeat=1, extended=False, down=True):
    """构造键盘消息的 lParam
    
    Bits:
      0-15:  repeat count
      16-23: scan code
      24:    extended key flag
      25-28: reserved
      29:    context code (0 for WM_KEYDOWN/UP)
      30:    previous key state (0=was up, 1=was down)
      31:    transition state (0=pressed, 1=released)
    """
    actual_scan = scan_code & 0xFF if scan_code > 0xFF else scan_code
    lparam = repeat
    lparam |= (actual_scan & 0xFF) << 16
    if extended or scan_code > 0xFF:
        lparam |= (1 << 24)
    if not down:
        lparam |= (1 << 30)  # previous state = was down
        lparam |= (1 << 31)  # transition = being released
    return lparam


class PostMessageInput:
    """通过 PostMessage/SendMessage 实现后台鼠标键盘注入

    完全不移动系统光标，不影响用户操作。
    所有坐标均为目标窗口客户区坐标。
    """

    def __init__(self):
        self._target_hwnd = None
        self._input_delay_ms = 0
        self._lock = threading.Lock()
        # 跟踪当前按下的鼠标按钮（用于 WM_MOUSEMOVE 的 wParam）
        self._pressed_buttons = set()

    # ==========================================================
    # 目标窗口管理
    # ==========================================================

    def set_target_hwnd(self, hwnd):
        """设置目标窗口句柄"""
        self._target_hwnd = hwnd

    def get_target_hwnd(self):
        """获取当前目标窗口句柄"""
        return self._target_hwnd

    # ==========================================================
    # 内部：子窗口查找
    # ==========================================================

    def _find_child_at(self, x, y):
        """查找目标窗口中 (x, y) 处的最深层子窗口

        Args:
            x, y: 客户区坐标

        Returns:
            (child_hwnd, child_x, child_y) — 子窗口句柄及相对于子窗口的坐标
        """
        hwnd = self._target_hwnd
        if not hwnd:
            return None, x, y

        # 将客户区坐标转为屏幕坐标
        screen_x, screen_y = win32gui.ClientToScreen(hwnd, (x, y))

        # 递归查找最深层子窗口
        child = hwnd
        while True:
            found = ctypes.windll.user32.RealChildWindowFromPoint(
                child, ctypes.wintypes.POINT(screen_x, screen_y)
            )
            if not found or found == child:
                break
            child = found

        # 计算相对于子窗口的客户区坐标
        if child != hwnd:
            child_x, child_y = win32gui.ScreenToClient(child, (screen_x, screen_y))
            return child, child_x, child_y

        return hwnd, x, y

    # ==========================================================
    # 内部：延迟
    # ==========================================================

    def _apply_delay(self):
        """操作间延迟"""
        if self._input_delay_ms > 0:
            time.sleep(self._input_delay_ms / 1000.0)

    def set_input_delay(self, delay_ms):
        """设置操作间延迟"""
        self._input_delay_ms = max(0, delay_ms)

    # ==========================================================
    # 内部：当前 wParam（鼠标按钮状态）
    # ==========================================================

    def _mouse_wparam(self, extra_flag=0):
        """根据当前按下的按钮构造 wParam"""
        wp = extra_flag
        if "left" in self._pressed_buttons:
            wp |= MK_LBUTTON
        if "right" in self._pressed_buttons:
            wp |= MK_RBUTTON
        if "middle" in self._pressed_buttons:
            wp |= MK_MBUTTON
        return wp

    # ==========================================================
    # 鼠标操作
    # ==========================================================

    def mouse_move_to(self, x, y):
        """发送 WM_MOUSEMOVE 到目标窗口

        Args:
            x, y: 窗口客户区坐标
        """
        with self._lock:
            target, tx, ty = self._find_child_at(x, y)
            if target:
                win32gui.PostMessage(
                    target, WM_MOUSEMOVE,
                    self._mouse_wparam(), _make_lparam(tx, ty)
                )
            self._apply_delay()

    def mouse_down(self, x, y, button="left"):
        """发送鼠标按下消息

        Args:
            x, y: 窗口客户区坐标
            button: 'left', 'right', 'middle'
        """
        down_msg, _, mk_flag = _BUTTON_MAP.get(button, _BUTTON_MAP["left"])
        with self._lock:
            self._pressed_buttons.add(button)
            target, tx, ty = self._find_child_at(x, y)
            if target:
                win32gui.PostMessage(
                    target, down_msg,
                    self._mouse_wparam(mk_flag), _make_lparam(tx, ty)
                )
            self._apply_delay()

    def mouse_up(self, x, y, button="left"):
        """发送鼠标释放消息

        Args:
            x, y: 窗口客户区坐标
            button: 'left', 'right', 'middle'
        """
        _, up_msg, _ = _BUTTON_MAP.get(button, _BUTTON_MAP["left"])
        with self._lock:
            self._pressed_buttons.discard(button)
            target, tx, ty = self._find_child_at(x, y)
            if target:
                win32gui.PostMessage(
                    target, up_msg,
                    self._mouse_wparam(), _make_lparam(tx, ty)
                )
            self._apply_delay()

    def mouse_click(self, x, y, button="left"):
        """完整的鼠标点击（move → down → up）

        Args:
            x, y: 窗口客户区坐标
            button: 'left', 'right', 'middle'
        """
        self.mouse_move_to(x, y)
        time.sleep(0.01)
        self.mouse_down(x, y, button)
        time.sleep(0.01)
        self.mouse_up(x, y, button)

    def mouse_scroll(self, x, y, delta):
        """发送滚轮消息

        Args:
            x, y: 窗口客户区坐标
            delta: 滚动量（正值向上，负值向下，通常 ±120）
        """
        with self._lock:
            if not self._target_hwnd:
                return
            # WM_MOUSEWHEEL 的坐标是屏幕坐标
            screen_x, screen_y = win32gui.ClientToScreen(
                self._target_hwnd, (x, y)
            )
            # wParam: HIWORD = delta, LOWORD = key state
            wparam = (delta << 16) | self._mouse_wparam()
            lparam = _make_lparam(screen_x, screen_y)
            win32gui.PostMessage(
                self._target_hwnd, WM_MOUSEWHEEL, wparam, lparam
            )
            self._apply_delay()

    # ==========================================================
    # 滑动操作
    # ==========================================================

    def perform_swipe(self, x1, y1, x2, y2, duration_ms, points=None):
        """通过连续 WM_MOUSEMOVE 模拟滑动

        Args:
            x1, y1: 起始坐标（窗口客户区）
            x2, y2: 结束坐标
            duration_ms: 持续时间（毫秒）
            points: 可选的中间轨迹点 [(x, y), ...]
        """
        # 构建路径
        if points and len(points) > 0:
            path = [(x1, y1)] + list(points) + [(x2, y2)]
        else:
            num_steps = max(2, duration_ms // 10)
            path = []
            for i in range(num_steps + 1):
                t = i / num_steps
                px = int(x1 + (x2 - x1) * t)
                py = int(y1 + (y2 - y1) * t)
                path.append((px, py))

        if len(path) < 2:
            return

        interval = duration_ms / (len(path) - 1) / 1000.0

        # 移动到起点并按下
        self.mouse_move_to(path[0][0], path[0][1])
        time.sleep(0.005)
        self.mouse_down(path[0][0], path[0][1], "left")

        # 逐点移动
        for i in range(1, len(path)):
            time.sleep(interval)
            # 发送带按钮状态的 MOUSEMOVE
            with self._lock:
                target, tx, ty = self._find_child_at(path[i][0], path[i][1])
                if target:
                    win32gui.PostMessage(
                        target, WM_MOUSEMOVE,
                        self._mouse_wparam(), _make_lparam(tx, ty)
                    )

        # 释放
        time.sleep(0.005)
        self.mouse_up(path[-1][0], path[-1][1], "left")

    # ==========================================================
    # 键盘操作
    # ==========================================================

    def _scan_to_vk(self, scan_code):
        """将 scan code 转换为 VK code"""
        # 先查扩展键
        vk = _EXT_SCANCODE_TO_VK.get(scan_code)
        if vk:
            return vk
        # 再查普通键
        vk = _SCANCODE_TO_VK.get(scan_code)
        if vk:
            return vk
        # 回退：使用 MapVirtualKey
        try:
            actual_scan = scan_code & 0xFF if scan_code > 0xFF else scan_code
            vk = ctypes.windll.user32.MapVirtualKeyW(actual_scan, 1)  # MAPVK_VSC_TO_VK
            if vk:
                return vk
        except Exception:
            pass
        return 0

    def key_down(self, scan_code):
        """发送键按下消息

        Args:
            scan_code: 键盘扫描码
        """
        with self._lock:
            if not self._target_hwnd:
                return
            vk = self._scan_to_vk(scan_code)
            extended = scan_code > 0xFF
            lparam = _make_key_lparam(scan_code, extended=extended, down=True)
            win32gui.PostMessage(self._target_hwnd, WM_KEYDOWN, vk, lparam)
            self._apply_delay()

    def key_up(self, scan_code):
        """发送键释放消息

        Args:
            scan_code: 键盘扫描码
        """
        with self._lock:
            if not self._target_hwnd:
                return
            vk = self._scan_to_vk(scan_code)
            extended = scan_code > 0xFF
            lparam = _make_key_lparam(scan_code, extended=extended, down=False)
            win32gui.PostMessage(self._target_hwnd, WM_KEYUP, vk, lparam)
            self._apply_delay()

    def key_press(self, scan_code, duration_ms=50):
        """按下并释放键

        Args:
            scan_code: 键盘扫描码
            duration_ms: 按住时间（毫秒）
        """
        self.key_down(scan_code)
        time.sleep(duration_ms / 1000.0)
        self.key_up(scan_code)

    def type_text(self, text, interval_ms=30):
        """逐字符输入文本

        通过 WM_CHAR 消息直接发送字符，比 WM_KEYDOWN 更可靠。

        Args:
            text: 要输入的文本
            interval_ms: 每个字符之间的间隔（毫秒）
        """
        with self._lock:
            if not self._target_hwnd:
                return

        for ch in text:
            with self._lock:
                win32gui.PostMessage(
                    self._target_hwnd, WM_CHAR, ord(ch), 0
                )
            time.sleep(interval_ms / 1000.0)

    # ==========================================================
    # 状态查询
    # ==========================================================

    def get_status(self):
        """返回引擎状态"""
        return {
            "backend": "postmessage",
            "available": True,  # PostMessage 始终可用
            "target_hwnd": self._target_hwnd,
            "input_delay_ms": self._input_delay_ms,
        }
