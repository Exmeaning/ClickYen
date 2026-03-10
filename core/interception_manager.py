"""
Interception 驱动封装层
提供硬件级键鼠模拟接口，支持光标锁定模式

interception-python 的真实 API：
  - auto_capture_devices() 返回 None，通过遍历 HWID 设置全局 _g_context
  - 所有操作（move_to, click, key_down 等）都是模块级函数
  - key_down/key_up 接受字符串键名（如 "a", "enter"），不是 scan code
  - scroll 接受 "up"/"down" 字符串
  - get_keyboard()/get_mouse() 返回设备号（int），0 表示未捕获
"""

import time
import threading
import ctypes
import ctypes.wintypes
from PyQt6.QtCore import QObject, pyqtSignal

# ============================================================
# VK Code → Scan Code 常用映射表
# ============================================================
VK_TO_SCANCODE = {
    # 字母键
    0x41: 0x1E, 0x42: 0x30, 0x43: 0x2E, 0x44: 0x20, 0x45: 0x12,
    0x46: 0x21, 0x47: 0x22, 0x48: 0x23, 0x49: 0x17, 0x4A: 0x24,
    0x4B: 0x25, 0x4C: 0x26, 0x4D: 0x32, 0x4E: 0x31, 0x4F: 0x18,
    0x50: 0x19, 0x51: 0x10, 0x52: 0x13, 0x53: 0x1F, 0x54: 0x14,
    0x55: 0x16, 0x56: 0x2F, 0x57: 0x11, 0x58: 0x2D, 0x59: 0x15,
    0x5A: 0x2C,
    # 数字键
    0x30: 0x0B, 0x31: 0x02, 0x32: 0x03, 0x33: 0x04, 0x34: 0x05,
    0x35: 0x06, 0x36: 0x07, 0x37: 0x08, 0x38: 0x09, 0x39: 0x0A,
    # 功能键
    0x70: 0x3B, 0x71: 0x3C, 0x72: 0x3D, 0x73: 0x3E, 0x74: 0x3F,
    0x75: 0x40, 0x76: 0x41, 0x77: 0x42, 0x78: 0x43, 0x79: 0x44,
    0x7A: 0x57, 0x7B: 0x58,
    # 控制键
    0x1B: 0x01,  # ESC
    0x09: 0x0F,  # TAB
    0x14: 0x3A,  # CAPS LOCK
    0x10: 0x2A,  # SHIFT (左)
    0x11: 0x1D,  # CTRL (左)
    0x12: 0x38,  # ALT (左)
    0x20: 0x39,  # SPACE
    0x0D: 0x1C,  # ENTER
    0x08: 0x0E,  # BACKSPACE
    # 方向键 (扩展键)
    0x25: 0xE04B,  # LEFT
    0x26: 0xE048,  # UP
    0x27: 0xE04D,  # RIGHT
    0x28: 0xE050,  # DOWN
    # 编辑键 (扩展键)
    0x2D: 0xE052,  # INSERT
    0x2E: 0xE053,  # DELETE
    0x24: 0xE047,  # HOME
    0x23: 0xE04F,  # END
    0x21: 0xE049,  # PAGE UP
    0x22: 0xE051,  # PAGE DOWN
}

# 字符 → VK Code 映射（用于 type_text）
CHAR_TO_VK = {}
for c in 'abcdefghijklmnopqrstuvwxyz':
    CHAR_TO_VK[c] = (ord(c.upper()), False)
    CHAR_TO_VK[c.upper()] = (ord(c.upper()), True)
for c in '0123456789':
    CHAR_TO_VK[c] = (ord(c), False)
CHAR_TO_VK[' '] = (0x20, False)
CHAR_TO_VK['\n'] = (0x0D, False)
CHAR_TO_VK['\t'] = (0x09, False)


# ============================================================
# Win32 SendInput 回退实现所需的结构体
# ============================================================
INPUT_MOUSE = 0
INPUT_KEYBOARD = 1

MOUSEEVENTF_MOVE = 0x0001
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
MOUSEEVENTF_RIGHTDOWN = 0x0008
MOUSEEVENTF_RIGHTUP = 0x0010
MOUSEEVENTF_MIDDLEDOWN = 0x0020
MOUSEEVENTF_MIDDLEUP = 0x0040
MOUSEEVENTF_WHEEL = 0x0800
MOUSEEVENTF_XDOWN = 0x0080
MOUSEEVENTF_XUP = 0x0100
MOUSEEVENTF_ABSOLUTE = 0x8000
XBUTTON1 = 0x0001
XBUTTON2 = 0x0002

KEYEVENTF_SCANCODE = 0x0008
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_EXTENDEDKEY = 0x0001


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", ctypes.wintypes.LONG),
        ("dy", ctypes.wintypes.LONG),
        ("mouseData", ctypes.wintypes.DWORD),
        ("dwFlags", ctypes.wintypes.DWORD),
        ("time", ctypes.wintypes.DWORD),
        ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
    ]


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", ctypes.wintypes.WORD),
        ("wScan", ctypes.wintypes.WORD),
        ("dwFlags", ctypes.wintypes.DWORD),
        ("time", ctypes.wintypes.DWORD),
        ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
    ]


class INPUT_UNION(ctypes.Union):
    _fields_ = [
        ("mi", MOUSEINPUT),
        ("ki", KEYBDINPUT),
    ]


class INPUT(ctypes.Structure):
    _fields_ = [
        ("type", ctypes.wintypes.DWORD),
        ("union", INPUT_UNION),
    ]


def _send_input(*inputs):
    """调用 Win32 SendInput"""
    n = len(inputs)
    arr = (INPUT * n)(*inputs)
    ctypes.windll.user32.SendInput(n, arr, ctypes.sizeof(INPUT))


# ============================================================
# InterceptionManager
# ============================================================
class InterceptionManager(QObject):
    """Interception 驱动封装，提供硬件级键鼠模拟"""

    driver_status_changed = pyqtSignal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)

        self._lock = threading.Lock()
        self._available = False
        self._driver_installed = False
        self._interception = None       # interception 模块引用
        self._keyboard_device = 0       # 键盘设备号
        self._mouse_device = 0          # 鼠标设备号
        self._cursor_lock_mode = False
        self._input_delay_ms = 0        # 操作间最小延迟（毫秒）

        # 屏幕尺寸缓存
        self._screen_w = 0
        self._screen_h = 0
        self._update_screen_size()

        # 尝试初始化 Interception
        self._init_interception()

    # ----------------------------------------------------------
    # 内部：屏幕尺寸
    # ----------------------------------------------------------
    def _update_screen_size(self):
        """获取主屏幕分辨率"""
        try:
            import win32api
            self._screen_w = win32api.GetSystemMetrics(0)
            self._screen_h = win32api.GetSystemMetrics(1)
        except Exception:
            # 回退到 ctypes
            self._screen_w = ctypes.windll.user32.GetSystemMetrics(0)
            self._screen_h = ctypes.windll.user32.GetSystemMetrics(1)
        if self._screen_w == 0 or self._screen_h == 0:
            self._screen_w, self._screen_h = 1920, 1080

    # ----------------------------------------------------------
    # 内部：Interception 初始化
    # ----------------------------------------------------------
    def _init_interception(self):
        """尝试导入并初始化 interception-python"""
        try:
            import interception
            self._interception = interception
            self._driver_installed = True
            print("[InterceptionManager] Interception 库已导入")

            # 尝试自动捕获设备
            try:
                interception.auto_capture_devices(keyboard=True, mouse=True)
                self._keyboard_device = interception.get_keyboard()
                self._mouse_device = interception.get_mouse()
                if self._keyboard_device or self._mouse_device:
                    self._available = True
                    print(f"[InterceptionManager] 设备捕获成功 "
                          f"(keyboard={self._keyboard_device}, mouse={self._mouse_device})")
                else:
                    print("[InterceptionManager] 设备号为 0，需手动重新捕获")
                    self._available = False
            except Exception as e:
                print(f"[InterceptionManager] 首次自动捕获未成功: {e}")
                self._available = False

            self.driver_status_changed.emit(self._available)

        except ImportError:
            print("[InterceptionManager] interception-python 未安装，使用 SendInput 回退")
            self._available = False
            self._interception = None
            self.driver_status_changed.emit(False)
        except Exception as e:
            print(f"[InterceptionManager] Interception 初始化失败: {e}，使用 SendInput 回退")
            self._available = False
            self._interception = None
            self.driver_status_changed.emit(False)

    # ----------------------------------------------------------
    # 内部：操作延迟
    # ----------------------------------------------------------
    def _apply_delay(self):
        """在操作之间应用最小延迟"""
        if self._input_delay_ms > 0:
            time.sleep(self._input_delay_ms / 1000.0)

    # ----------------------------------------------------------
    # 内部：坐标转换
    # ----------------------------------------------------------
    def _to_normalized(self, x, y):
        """将屏幕像素坐标转换为 SendInput 归一化坐标 (0-65535)"""
        nx = int(x * 65535 / self._screen_w)
        ny = int(y * 65535 / self._screen_h)
        return max(0, min(65535, nx)), max(0, min(65535, ny))

    # ----------------------------------------------------------
    # 内部：获取当前光标位置
    # ----------------------------------------------------------
    def _get_cursor_pos(self):
        """获取当前光标位置"""
        try:
            import win32api
            return win32api.GetCursorPos()
        except Exception:
            point = ctypes.wintypes.POINT()
            ctypes.windll.user32.GetCursorPos(ctypes.byref(point))
            return (point.x, point.y)

    # ----------------------------------------------------------
    # 内部：SendInput 回退方法
    # ----------------------------------------------------------
    def _fallback_mouse_move_abs(self, x, y):
        """SendInput 回退：绝对移动"""
        nx, ny = self._to_normalized(x, y)
        inp = INPUT()
        inp.type = INPUT_MOUSE
        inp.union.mi.dx = nx
        inp.union.mi.dy = ny
        inp.union.mi.dwFlags = MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE
        _send_input(inp)

    def _fallback_mouse_move_rel(self, dx, dy):
        """SendInput 回退：相对移动"""
        inp = INPUT()
        inp.type = INPUT_MOUSE
        inp.union.mi.dx = dx
        inp.union.mi.dy = dy
        inp.union.mi.dwFlags = MOUSEEVENTF_MOVE
        _send_input(inp)

    def _fallback_mouse_button(self, button, down):
        """SendInput 回退：鼠标按钮"""
        flags_map = {
            "left":   (MOUSEEVENTF_LEFTDOWN,   MOUSEEVENTF_LEFTUP),
            "right":  (MOUSEEVENTF_RIGHTDOWN,  MOUSEEVENTF_RIGHTUP),
            "middle": (MOUSEEVENTF_MIDDLEDOWN, MOUSEEVENTF_MIDDLEUP),
        }
        # XBUTTON 需要特殊处理（通过 mouseData 指定按钮编号）
        if button in ("mouse4", "x1"):
            inp = INPUT()
            inp.type = INPUT_MOUSE
            inp.union.mi.dwFlags = MOUSEEVENTF_XDOWN if down else MOUSEEVENTF_XUP
            inp.union.mi.mouseData = ctypes.wintypes.DWORD(XBUTTON1)
            _send_input(inp)
            return
        elif button in ("mouse5", "x2"):
            inp = INPUT()
            inp.type = INPUT_MOUSE
            inp.union.mi.dwFlags = MOUSEEVENTF_XDOWN if down else MOUSEEVENTF_XUP
            inp.union.mi.mouseData = ctypes.wintypes.DWORD(XBUTTON2)
            _send_input(inp)
            return

        down_flag, up_flag = flags_map.get(button, flags_map["left"])
        inp = INPUT()
        inp.type = INPUT_MOUSE
        inp.union.mi.dwFlags = down_flag if down else up_flag
        _send_input(inp)

    def _fallback_mouse_scroll(self, delta):
        """SendInput 回退：滚轮"""
        inp = INPUT()
        inp.type = INPUT_MOUSE
        inp.union.mi.mouseData = ctypes.wintypes.DWORD(delta)
        inp.union.mi.dwFlags = MOUSEEVENTF_WHEEL
        _send_input(inp)

    def _fallback_key_action(self, scan_code, down):
        """SendInput 回退：键盘"""
        inp = INPUT()
        inp.type = INPUT_KEYBOARD
        # 处理扩展键
        extended = scan_code > 0xFF
        actual_scan = scan_code & 0xFF if extended else scan_code
        inp.union.ki.wScan = actual_scan
        flags = KEYEVENTF_SCANCODE
        if extended:
            flags |= KEYEVENTF_EXTENDEDKEY
        if not down:
            flags |= KEYEVENTF_KEYUP
        inp.union.ki.dwFlags = flags
        _send_input(inp)

    # ==========================================================
    # 1. 驱动管理
    # ==========================================================
    def is_driver_installed(self):
        """检测 Interception 驱动是否已安装"""
        return self._driver_installed

    def capture_devices(self, timeout_sec=10):
        """自动捕获鼠标和键盘设备

        Args:
            timeout_sec: 超时时间（秒，本库版本不支持 timeout，参数保留兼容）

        Returns:
            bool: 是否成功捕获
        """
        if not self._interception:
            try:
                import interception
                self._interception = interception
                self._driver_installed = True
            except ImportError:
                print("[InterceptionManager] interception-python 未安装")
                return False

        try:
            self._interception.auto_capture_devices(keyboard=True, mouse=True)
            self._keyboard_device = self._interception.get_keyboard()
            self._mouse_device = self._interception.get_mouse()

            if self._keyboard_device or self._mouse_device:
                self._available = True
                print(f"[InterceptionManager] 设备捕获成功 "
                      f"(keyboard={self._keyboard_device}, mouse={self._mouse_device})")
                self.driver_status_changed.emit(True)
                return True
            else:
                print("[InterceptionManager] 设备捕获失败：设备号为 0")
                self._available = False
                self.driver_status_changed.emit(False)
                return False
        except Exception as e:
            print(f"[InterceptionManager] 设备捕获失败: {e}")
            self._available = False
            self.driver_status_changed.emit(False)
            return False

    def get_status(self):
        """返回驱动状态和已捕获设备信息"""
        return {
            "driver_installed": self._driver_installed,
            "available": self._available,
            "context_active": self._available and (self._keyboard_device or self._mouse_device),
            "keyboard_device": self._keyboard_device,
            "mouse_device": self._mouse_device,
            "screen_size": (self._screen_w, self._screen_h),
            "cursor_lock_mode": self._cursor_lock_mode,
            "input_delay_ms": self._input_delay_ms,
            "backend": "interception" if self._available else "SendInput",
        }

    # ==========================================================
    # 2. 鼠标操作
    # ==========================================================
    def mouse_move_to(self, x, y):
        """移动鼠标到绝对屏幕坐标"""
        with self._lock:
            if self._available and self._interception:
                try:
                    self._interception.move_to(x, y)
                except Exception as e:
                    print(f"[InterceptionManager] move_to 失败: {e}，回退 SendInput")
                    self._fallback_mouse_move_abs(x, y)
            else:
                self._fallback_mouse_move_abs(x, y)
            self._apply_delay()

    def mouse_move_relative(self, dx, dy):
        """相对移动鼠标"""
        with self._lock:
            if self._available and self._interception:
                try:
                    self._interception.move_relative(dx, dy)
                except Exception as e:
                    print(f"[InterceptionManager] move_relative 失败: {e}")
                    self._fallback_mouse_move_rel(dx, dy)
            else:
                self._fallback_mouse_move_rel(dx, dy)
            self._apply_delay()

    def mouse_click(self, x, y, button="left"):
        """移动到指定坐标并点击"""
        self.mouse_move_to(x, y)
        time.sleep(0.01)
        self.mouse_down(button)
        time.sleep(0.01)
        self.mouse_up(button)

    def mouse_down(self, button="left"):
        """按下鼠标按钮"""
        with self._lock:
            if self._available and self._interception:
                try:
                    self._interception.mouse_down(button)
                except Exception as e:
                    print(f"[InterceptionManager] mouse_down 失败: {e}")
                    self._fallback_mouse_button(button, down=True)
            else:
                self._fallback_mouse_button(button, down=True)
            self._apply_delay()

    def mouse_up(self, button="left"):
        """释放鼠标按钮"""
        with self._lock:
            if self._available and self._interception:
                try:
                    self._interception.mouse_up(button)
                except Exception as e:
                    print(f"[InterceptionManager] mouse_up 失败: {e}")
                    self._fallback_mouse_button(button, down=False)
            else:
                self._fallback_mouse_button(button, down=False)
            self._apply_delay()

    def mouse_scroll(self, delta):
        """滚轮操作

        Args:
            delta: 滚动量，正值向上，负值向下
        """
        with self._lock:
            if self._available and self._interception:
                try:
                    # interception-python scroll 接受 "up"/"down" 字符串
                    direction = "up" if delta > 0 else "down"
                    count = max(1, abs(delta) // 120)
                    for _ in range(count):
                        self._interception.scroll(direction)
                except Exception as e:
                    print(f"[InterceptionManager] scroll 失败: {e}")
                    self._fallback_mouse_scroll(delta)
            else:
                self._fallback_mouse_scroll(delta)
            self._apply_delay()

    # ==========================================================
    # 3. 光标锁定模式（核心特性）
    # ==========================================================
    def set_cursor_lock_mode(self, enabled):
        """启用/禁用光标锁定模式"""
        self._cursor_lock_mode = enabled
        print(f"[InterceptionManager] 光标锁定模式: {'启用' if enabled else '禁用'}")

    def click_with_restore(self, x, y, button="left"):
        """快速移动到目标 → 点击 → 移回原位"""
        original_pos = self._get_cursor_pos()
        try:
            self.mouse_click(x, y, button)
        finally:
            if self._cursor_lock_mode:
                time.sleep(0.005)
                self.mouse_move_to(original_pos[0], original_pos[1])

    def swipe_with_restore(self, x1, y1, x2, y2, duration_ms, points=None):
        """滑动后恢复光标位置"""
        original_pos = self._get_cursor_pos()
        try:
            self._perform_swipe(x1, y1, x2, y2, duration_ms, points)
        finally:
            if self._cursor_lock_mode:
                time.sleep(0.005)
                self.mouse_move_to(original_pos[0], original_pos[1])

    def _perform_swipe(self, x1, y1, x2, y2, duration_ms, points=None):
        """执行滑动操作"""
        # 构建完整路径
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

        self.mouse_move_to(path[0][0], path[0][1])
        time.sleep(0.005)
        self.mouse_down("left")

        for i in range(1, len(path)):
            time.sleep(interval)
            self.mouse_move_to(path[i][0], path[i][1])

        time.sleep(0.005)
        self.mouse_up("left")

    # ==========================================================
    # 4. 键盘操作
    # ==========================================================
    def key_down(self, scan_code):
        """按下键

        Args:
            scan_code: 键盘扫描码
        """
        with self._lock:
            # interception-python 的 key_down 接受字符串键名，
            # 但我们的接口统一用 scan_code，所以键盘操作始终走 SendInput 回退
            self._fallback_key_action(scan_code, down=True)
            self._apply_delay()

    def key_up(self, scan_code):
        """释放键

        Args:
            scan_code: 键盘扫描码
        """
        with self._lock:
            self._fallback_key_action(scan_code, down=False)
            self._apply_delay()

    def key_press(self, scan_code, duration_ms=50):
        """按下并释放键"""
        self.key_down(scan_code)
        time.sleep(duration_ms / 1000.0)
        self.key_up(scan_code)

    def type_text(self, text, interval_ms=30):
        """逐字符输入文本"""
        if self._available and self._interception:
            try:
                # interception-python 有原生 write() 函数
                self._interception.write(text, interval=interval_ms / 1000.0)
                return
            except Exception as e:
                print(f"[InterceptionManager] write() 失败: {e}，回退手动输入")

        # 回退：逐字符通过 scan code 发送
        for ch in text:
            vk_info = CHAR_TO_VK.get(ch)
            if vk_info is None:
                try:
                    import win32api
                    vk = win32api.VkKeyScan(ch)
                    if vk == -1:
                        print(f"[InterceptionManager] 无法映射字符: '{ch}'")
                        continue
                    vk_code = vk & 0xFF
                    need_shift = bool(vk & 0x100)
                except Exception:
                    print(f"[InterceptionManager] 无法映射字符: '{ch}'")
                    continue
            else:
                vk_code, need_shift = vk_info

            scan = VK_TO_SCANCODE.get(vk_code)
            if scan is None:
                try:
                    scan = ctypes.windll.user32.MapVirtualKeyW(vk_code, 0)
                except Exception:
                    print(f"[InterceptionManager] 无法获取扫描码: VK=0x{vk_code:02X}")
                    continue
            if scan == 0:
                continue

            if need_shift:
                self.key_down(VK_TO_SCANCODE.get(0x10, 0x2A))
                time.sleep(0.005)

            self.key_press(scan, duration_ms=20)

            if need_shift:
                time.sleep(0.005)
                self.key_up(VK_TO_SCANCODE.get(0x10, 0x2A))

            time.sleep(interval_ms / 1000.0)

    # ==========================================================
    # 5. 配置
    # ==========================================================
    def set_input_delay(self, delay_ms):
        """设置操作间最小延迟"""
        self._input_delay_ms = max(0, delay_ms)
        print(f"[InterceptionManager] 输入延迟设置为: {self._input_delay_ms}ms")
