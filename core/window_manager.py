"""Windows 窗口管理器 - 统一管理窗口枚举、选择、截图、坐标映射"""

import re
import logging

import win32gui
import win32process
import win32api
import win32con

from PyQt6.QtCore import QObject, pyqtSignal

try:
    import psutil
    _HAS_PSUTIL = True
except ImportError:
    _HAS_PSUTIL = False

from core.window_capture import WindowCapture

logger = logging.getLogger(__name__)


class WindowManager(QObject):
    """Windows 窗口管理器"""

    target_window_changed = pyqtSignal(int, str)  # hwnd, title
    window_lost = pyqtSignal()  # 目标窗口关闭/不可见

    def __init__(self, parent=None):
        super().__init__(parent)
        self._target_hwnd = None
        self._crop_rect = None  # (x, y, w, h)

    # ── 窗口枚举 ──────────────────────────────────────────

    @staticmethod
    def _get_exe_name(pid: int) -> str:
        """通过 PID 获取进程名，失败时返回空字符串"""
        if pid == 0:
            return ""
        try:
            if _HAS_PSUTIL:
                return psutil.Process(pid).name()
            # fallback: win32process
            import ctypes
            h = ctypes.windll.kernel32.OpenProcess(0x0400 | 0x0010, False, pid)
            if h:
                import ctypes.wintypes
                buf = ctypes.create_unicode_buffer(260)
                ctypes.windll.psapi.GetModuleBaseNameW(h, None, buf, 260)
                ctypes.windll.kernel32.CloseHandle(h)
                return buf.value
        except Exception:
            pass
        return ""

    def list_windows(self, visible_only: bool = True) -> list:
        """枚举所有窗口

        Returns:
            [{hwnd, title, class_name, rect, pid, exe_name}, ...]
        """
        results = []

        def _callback(hwnd, _):
            if visible_only and not win32gui.IsWindowVisible(hwnd):
                return True
            title = win32gui.GetWindowText(hwnd)
            if not title:
                return True
            try:
                class_name = win32gui.GetClassName(hwnd)
                rect = win32gui.GetWindowRect(hwnd)
                tid, pid = win32process.GetWindowThreadProcessId(hwnd)
                exe_name = self._get_exe_name(pid)
                results.append({
                    "hwnd": hwnd,
                    "title": title,
                    "class_name": class_name,
                    "rect": rect,  # (left, top, right, bottom)
                    "pid": pid,
                    "exe_name": exe_name,
                })
            except Exception:
                pass
            return True

        win32gui.EnumWindows(_callback, None)
        return results

    def find_window_by_title(self, title_pattern: str) -> list:
        """按标题模糊搜索窗口"""
        pattern = re.compile(title_pattern, re.IGNORECASE)
        return [w for w in self.list_windows() if pattern.search(w["title"])]

    def get_window_at_cursor(self) -> dict | None:
        """获取鼠标光标下的窗口信息"""
        try:
            pt = win32api.GetCursorPos()
            hwnd = win32gui.WindowFromPoint(pt)
            if not hwnd:
                return None
            title = win32gui.GetWindowText(hwnd)
            class_name = win32gui.GetClassName(hwnd)
            rect = win32gui.GetWindowRect(hwnd)
            tid, pid = win32process.GetWindowThreadProcessId(hwnd)
            exe_name = self._get_exe_name(pid)
            return {
                "hwnd": hwnd,
                "title": title,
                "class_name": class_name,
                "rect": rect,
                "pid": pid,
                "exe_name": exe_name,
            }
        except Exception as e:
            logger.warning("get_window_at_cursor 失败: %s", e)
            return None

    # ── 目标窗口管理 ─────────────────────────────────────

    def set_target(self, hwnd: int, crop_rect: tuple = None):
        """设置目标窗口

        Args:
            hwnd: 窗口句柄
            crop_rect: 裁剪区域 (x, y, w, h)，相对于窗口客户区。None 表示使用全窗口。
        """
        self._target_hwnd = hwnd
        self._crop_rect = crop_rect
        title = ""
        try:
            title = win32gui.GetWindowText(hwnd)
        except Exception:
            pass
        logger.info("目标窗口已设置: hwnd=%s title='%s' crop=%s", hwnd, title, crop_rect)
        self.target_window_changed.emit(hwnd, title)

    def set_desktop_as_target(self):
        """将整个桌面设置为目标（默认模式）"""
        desktop_hwnd = win32gui.GetDesktopWindow()
        self.set_target(desktop_hwnd, None)
        logger.info("已设置桌面为默认目标窗口")

    def clear_target(self):
        """清除目标窗口"""
        self._target_hwnd = None
        self._crop_rect = None
        logger.info("目标窗口已清除")

    def get_target(self) -> tuple:
        """返回 (hwnd, crop_rect)"""
        return self._target_hwnd, self._crop_rect

    def is_target_valid(self) -> bool:
        """窗口是否仍然存在且可见"""
        if self._target_hwnd is None:
            return False
        try:
            return (win32gui.IsWindow(self._target_hwnd)
                    and win32gui.IsWindowVisible(self._target_hwnd))
        except Exception:
            return False

    # ── 坐标转换 ─────────────────────────────────────────

    def screen_to_window(self, screen_x: int, screen_y: int) -> tuple:
        """屏幕坐标 → 窗口客户区坐标（考虑裁剪区域偏移）"""
        if self._target_hwnd is None:
            return screen_x, screen_y
        client_x, client_y = win32gui.ScreenToClient(self._target_hwnd, (screen_x, screen_y))
        if self._crop_rect:
            crop_x, crop_y = self._crop_rect[0], self._crop_rect[1]
            client_x -= crop_x
            client_y -= crop_y
        return client_x, client_y

    def window_to_screen(self, win_x: int, win_y: int) -> tuple:
        """窗口客户区坐标 → 屏幕坐标（考虑裁剪区域偏移）"""
        if self._target_hwnd is None:
            return win_x, win_y
        client_x, client_y = win_x, win_y
        if self._crop_rect:
            crop_x, crop_y = self._crop_rect[0], self._crop_rect[1]
            client_x += crop_x
            client_y += crop_y
        screen_x, screen_y = win32gui.ClientToScreen(self._target_hwnd, (client_x, client_y))
        return screen_x, screen_y

    def is_point_in_target(self, screen_x: int, screen_y: int) -> bool:
        """判断屏幕坐标是否在目标窗口/裁剪区域内"""
        if not self.is_target_valid():
            return False
        wx, wy = self.screen_to_window(screen_x, screen_y)
        tw, th = self.get_target_size()
        return 0 <= wx < tw and 0 <= wy < th

    def get_target_size(self) -> tuple:
        """获取目标区域尺寸（裁剪后的宽高）"""
        if self._target_hwnd is None:
            return 0, 0
        if self._crop_rect:
            return self._crop_rect[2], self._crop_rect[3]
        try:
            rect = win32gui.GetClientRect(self._target_hwnd)
            return rect[2] - rect[0], rect[3] - rect[1]
        except Exception:
            return 0, 0

    # ── 截图 ─────────────────────────────────────────────

    def capture_target(self):
        """截取目标窗口/裁剪区域的图像

        Returns:
            PIL.Image or None
        """
        if not self.is_target_valid():
            self.window_lost.emit()
            return None
        return WindowCapture.capture_window_by_hwnd(self._target_hwnd, self._crop_rect)

    def capture_target_region(self, x: int, y: int, w: int, h: int):
        """截取目标窗口内指定区域（相对于裁剪后的坐标系）

        Args:
            x, y, w, h: 相对于目标区域（裁剪后）的子区域

        Returns:
            PIL.Image or None
        """
        if not self.is_target_valid():
            self.window_lost.emit()
            return None
        # 将子区域坐标转换为相对于窗口客户区的绝对坐标
        abs_x, abs_y = x, y
        if self._crop_rect:
            abs_x += self._crop_rect[0]
            abs_y += self._crop_rect[1]
        region_rect = (abs_x, abs_y, w, h)
        return WindowCapture.capture_window_by_hwnd(self._target_hwnd, region_rect)

    # ── 窗口操作 ─────────────────────────────────────────

    def bring_to_front(self):
        """将目标窗口置前"""
        if not self.is_target_valid():
            self.window_lost.emit()
            return
        try:
            # 如果窗口最小化，先恢复
            if win32gui.IsIconic(self._target_hwnd):
                win32gui.ShowWindow(self._target_hwnd, win32con.SW_RESTORE)
            win32gui.SetForegroundWindow(self._target_hwnd)
        except Exception as e:
            logger.warning("bring_to_front 失败: %s", e)

    def get_child_at_point(self, client_x: int, client_y: int) -> tuple:
        """获取目标窗口中指定客户区坐标处的最深层子窗口

        PostMessage 需要发送到正确的子窗口才能生效。

        Args:
            client_x, client_y: 相对于目标区域（裁剪后）的坐标

        Returns:
            (child_hwnd, child_x, child_y) — 子窗口句柄及相对坐标
            如果没有子窗口，返回 (target_hwnd, adjusted_x, adjusted_y)
        """
        if self._target_hwnd is None:
            return None, client_x, client_y

        # 考虑裁剪偏移
        abs_x, abs_y = client_x, client_y
        if self._crop_rect:
            abs_x += self._crop_rect[0]
            abs_y += self._crop_rect[1]

        # 转为屏幕坐标
        try:
            screen_x, screen_y = win32gui.ClientToScreen(
                self._target_hwnd, (abs_x, abs_y)
            )
        except Exception:
            return self._target_hwnd, abs_x, abs_y

        # 递归查找最深层子窗口
        import ctypes
        import ctypes.wintypes
        child = self._target_hwnd
        while True:
            found = ctypes.windll.user32.RealChildWindowFromPoint(
                child, ctypes.wintypes.POINT(screen_x, screen_y)
            )
            if not found or found == child:
                break
            child = found

        # 计算相对于子窗口的客户区坐标
        if child != self._target_hwnd:
            try:
                child_x, child_y = win32gui.ScreenToClient(
                    child, (screen_x, screen_y)
                )
                return child, child_x, child_y
            except Exception:
                pass

        return self._target_hwnd, abs_x, abs_y

    def get_postmessage_coords(self, win_x: int, win_y: int) -> tuple:
        """将目标区域坐标转换为 PostMessage 所需的坐标

        考虑裁剪偏移，返回相对于目标窗口客户区的绝对坐标。

        Args:
            win_x, win_y: 相对于目标区域（裁剪后）的坐标

        Returns:
            (abs_x, abs_y) — 相对于窗口客户区的坐标
        """
        abs_x, abs_y = win_x, win_y
        if self._crop_rect:
            abs_x += self._crop_rect[0]
            abs_y += self._crop_rect[1]
        return abs_x, abs_y

    def get_window_info(self) -> dict | None:
        """获取目标窗口的详细信息"""
        if self._target_hwnd is None:
            return None
        hwnd = self._target_hwnd
        try:
            title = win32gui.GetWindowText(hwnd)
            class_name = win32gui.GetClassName(hwnd)
            rect = win32gui.GetWindowRect(hwnd)
            client_rect = win32gui.GetClientRect(hwnd)
            tid, pid = win32process.GetWindowThreadProcessId(hwnd)
            exe_name = self._get_exe_name(pid)
            visible = win32gui.IsWindowVisible(hwnd)
            iconic = win32gui.IsIconic(hwnd)
            return {
                "hwnd": hwnd,
                "title": title,
                "class_name": class_name,
                "rect": rect,
                "client_rect": client_rect,
                "pid": pid,
                "exe_name": exe_name,
                "visible": bool(visible),
                "iconic": bool(iconic),
                "crop_rect": self._crop_rect,
                "target_size": self.get_target_size(),
            }
        except Exception as e:
            logger.warning("get_window_info 失败: %s", e)
            return None
