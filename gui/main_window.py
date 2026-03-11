from PyQt6.QtWidgets import *
from PyQt6.QtCore import *
from PyQt6.QtGui import *
import sys
import json
import ctypes
import ctypes.wintypes
from datetime import datetime
import time
import urllib.request
from core.auto_monitor import AutoMonitor
from gui.monitor_dialog import MonitorTaskDialog
from gui.settings_dialog import SettingsDialog
from utils.config import VERSION
from gui.left_panel import LeftPanel
from gui.center_panel import CenterPanel
from gui.right_panel import RightPanel


class HotkeyFilter(QAbstractNativeEventFilter):
    """原生事件过滤器 - 安全处理多个 WM_HOTKEY"""

    def __init__(self):
        super().__init__()
        self._callbacks = {}  # {hotkey_id: callback}

    def register_hotkey(self, hotkey_id, callback):
        """注册热键回调"""
        self._callbacks[hotkey_id] = callback

    def nativeEventFilter(self, eventType, message):
        WM_HOTKEY = 0x0312
        if eventType == b"windows_generic_MSG" or eventType == b"windows_dispatcher_MSG":
            try:
                addr = int(message)
                if addr:
                    # MSG 结构 (64-bit): HWND(8) + UINT message(4)
                    msg_id = ctypes.c_uint.from_address(
                        addr + ctypes.sizeof(ctypes.c_void_p)
                    ).value
                    if msg_id == WM_HOTKEY:
                        # wParam 在 MSG 结构中偏移: HWND(8) + UINT(4) + padding(4) + WPARAM(8)
                        wparam_offset = ctypes.sizeof(ctypes.c_void_p) + 8
                        wparam = ctypes.c_ulonglong.from_address(
                            addr + wparam_offset
                        ).value
                        callback = self._callbacks.get(wparam)
                        if callback:
                            QTimer.singleShot(0, callback)
                            return True, 0
            except Exception:
                pass
        return False, 0


# F键名 → VK Code 映射
FKEY_TO_VK = {f"F{i}": 0x70 + i - 1 for i in range(1, 13)}
# VK Code → F键名 反向映射
VK_TO_FKEY = {v: k for k, v in FKEY_TO_VK.items()}


class MainWindow(QMainWindow):
    version_fetched = pyqtSignal(str)
    playback_finished = pyqtSignal(bool)

    def __init__(self, config, interception_mgr, window_mgr, controller):
        super().__init__()
        self.config = config
        self.interception = interception_mgr
        self.window_mgr = window_mgr
        self.controller = controller
        self.is_recording = False

        self.auto_monitor = AutoMonitor(controller)
        self.auto_monitor.match_found.connect(self.on_auto_match_found)
        self.auto_monitor.status_update.connect(self.on_monitor_status_update)
        self.auto_monitor.log_message.connect(self.log)

        self.version_fetched.connect(self.update_version_label)
        self.playback_finished.connect(self._on_playback_finished)

        self.current_device_coords = (0, 0)

        self.initUI()
        self.setup_coordinate_tracker()
        self.setup_shortcuts()
        self.on_randomization_changed()

    # ── UI 初始化 ─────────────────────────────────────────

    def initUI(self):
        self.setWindowTitle(f"ClickYen - 智能点击助手 v{VERSION}")

        screen = QApplication.primaryScreen()
        screen_rect = screen.availableGeometry()
        width = 1280
        height = 900
        self.setGeometry(
            int((screen_rect.width() - width) / 2),
            int((screen_rect.height() - height) / 2),
            width, height
        )
        self.setMinimumSize(1280, 720)
        self.setWindowIcon(QIcon())

        self.setStyleSheet("""
            QMainWindow { background-color: #f5f5f5; }
            QStatusBar {
                background-color: #37474F; color: white; font-size: 13px;
            }
            QStatusBar::item { border: none; }
        """)

        self.create_menu_bar()

        central_widget = QWidget()
        central_widget.setStyleSheet("background-color: #f5f5f5;")
        self.setCentralWidget(central_widget)

        main_layout = QHBoxLayout(central_widget)
        main_layout.setContentsMargins(10, 10, 10, 10)
        main_layout.setSpacing(10)

        # 三栏面板
        self.left_panel = LeftPanel(self)
        self.left_panel.setMinimumWidth(280)

        self.center_panel = CenterPanel(self)
        self.center_panel.setMinimumWidth(400)

        self.right_panel = RightPanel(self)
        self.right_panel.setMinimumWidth(400)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(self.left_panel)
        splitter.addWidget(self.center_panel)
        splitter.addWidget(self.right_panel)
        splitter.setStretchFactor(0, 2)
        splitter.setStretchFactor(1, 3)
        splitter.setStretchFactor(2, 3)
        splitter.setSizes([320, 480, 480])
        main_layout.addWidget(splitter)

        self.statusBar().showMessage("就绪")

        # 注入依赖
        self.left_panel.set_window_manager(self.window_mgr)
        self.left_panel.set_interception_manager(self.interception)

        # 连接面板信号
        self.connect_panel_signals()

        # 连接控制器信号
        self.controller.action_recorded.connect(self.on_action_recorded)

        # 初始化面板引用
        self.setup_widget_references()

        # 加载设置
        self.load_and_apply_settings()

        # 延迟检查版本
        QTimer.singleShot(1000, self.check_latest_version)

        # 默认使用桌面作为捕获目标
        self.window_mgr.set_desktop_as_target()
        self.log("默认捕获目标: 整个桌面（可在左侧面板选择特定窗口）", "info")

    # ── 菜单栏 ────────────────────────────────────────────

    def create_menu_bar(self):
        menubar = self.menuBar()

        # 文件
        file_menu = menubar.addMenu("文件")
        load_action = QAction("加载录制", self)
        load_action.setShortcut("Ctrl+O")
        load_action.triggered.connect(self.load_recording)
        file_menu.addAction(load_action)

        save_action = QAction("保存录制", self)
        save_action.setShortcut("Ctrl+S")
        save_action.triggered.connect(self.save_recording)
        file_menu.addAction(save_action)

        file_menu.addSeparator()
        exit_action = QAction("退出", self)
        exit_action.setShortcut("Ctrl+Q")
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)

        # 工具
        tools_menu = menubar.addMenu("工具")
        settings_action = QAction("设置", self)
        settings_action.setShortcut("Ctrl+,")
        settings_action.triggered.connect(self.open_settings)
        tools_menu.addAction(settings_action)

        tools_menu.addSeparator()
        advanced_monitor_action = QAction("🌐 高级监控功能", self)
        advanced_monitor_action.triggered.connect(self.open_advanced_monitor)
        tools_menu.addAction(advanced_monitor_action)

        tools_menu.addSeparator()
        screenshot_action = QAction("截图", self)
        screenshot_action.setShortcut("Ctrl+P")
        screenshot_action.triggered.connect(self.take_screenshot)
        tools_menu.addAction(screenshot_action)

        # 帮助
        help_menu = menubar.addMenu("帮助")
        about_action = QAction("关于", self)
        about_action.triggered.connect(self.show_about)
        help_menu.addAction(about_action)

    # ── 信号连接 & 控件引用 ─────────────────────────────────

    def connect_panel_signals(self):
        """连接各面板的信号"""
        # 左侧面板 - 窗口选择 & 输入设置
        self.left_panel.target_window_selected.connect(self.on_target_window_selected)
        self.left_panel.cursor_lock_mode_changed.connect(self.on_cursor_lock_changed)
        self.left_panel.input_delay_changed.connect(self.on_input_delay_changed)

        # 中间面板 - 录制/播放
        self.center_panel.recording_toggled.connect(self.toggle_recording)
        self.center_panel.play_btn.clicked.connect(self.play_recording)
        self.center_panel.stop_btn.clicked.connect(self.stop_playing)
        self.center_panel.monitor_toggled.connect(self.toggle_monitoring)

        # 文件操作
        self.center_panel.save_btn.clicked.connect(self.save_recording)
        self.center_panel.load_btn.clicked.connect(self.load_recording)

        # 监控任务管理
        self.center_panel.add_task_btn.clicked.connect(self.add_monitor_task)
        self.center_panel.edit_task_btn.clicked.connect(self.edit_monitor_task)
        self.center_panel.copy_task_btn.clicked.connect(self.copy_monitor_task)
        self.center_panel.remove_task_btn.clicked.connect(self.remove_monitor_task)
        self.center_panel.save_scheme_btn.clicked.connect(self.save_monitor_scheme)
        self.center_panel.load_scheme_btn.clicked.connect(self.load_monitor_scheme)

        # 随机化设置
        self.center_panel.random_check.toggled.connect(self.on_randomization_changed)
        self.center_panel.position_spin.valueChanged.connect(self.on_randomization_changed)
        self.center_panel.delay_spin.valueChanged.connect(self.on_randomization_changed)
        self.center_panel.longpress_spin.valueChanged.connect(self.on_randomization_changed)

        # 输入模式切换
        self.left_panel.input_mode_changed.connect(self.on_input_mode_changed)

        # 监控间隔
        self.center_panel.interval_spin.valueChanged.connect(self.on_interval_changed)

        # 右侧面板
        self.right_panel.copy_coords_clicked.connect(self.copy_device_coordinates)
        self.right_panel.clear_log_btn.clicked.connect(self.clear_log)

    def setup_widget_references(self):
        """设置控件引用"""
        # 中间面板控件
        self.record_mode_combo = self.center_panel.record_mode_combo
        self.record_btn = self.center_panel.record_btn
        self.play_btn = self.center_panel.play_btn
        self.stop_play_btn = self.center_panel.stop_btn
        self.speed_spin = self.center_panel.speed_spin
        self.record_info_label = self.center_panel.record_info_label
        self.action_list = self.center_panel.action_list

        self.monitor_task_list = self.center_panel.monitor_task_list
        self.monitor_start_btn = self.center_panel.monitor_btn
        self.monitor_status_label = self.center_panel.monitor_status_label
        self.interval_spin = self.center_panel.interval_spin

        self.random_enabled_check = self.center_panel.random_check
        self.position_random_spin = self.center_panel.position_spin
        self.delay_random_spin = self.center_panel.delay_spin
        self.longpress_random_spin = self.center_panel.longpress_spin

        # 右侧面板控件
        self.screen_coord_label = self.right_panel.screen_coord_label
        self.device_coord_label = self.right_panel.device_coord_label
        self.window_status_label = self.right_panel.window_status_label
        self.log_text = self.right_panel.log_text

    # ── 坐标追踪 ───────────────────────────────────────────

    def setup_coordinate_tracker(self):
        """设置坐标追踪器"""
        self.coord_timer = QTimer(self)
        self.coord_timer.timeout.connect(self.update_mouse_coordinates)
        self.coord_timer.start(50)

    def update_mouse_coordinates(self):
        """更新鼠标坐标显示"""
        try:
            if not hasattr(self, 'screen_coord_label') or not hasattr(self, 'device_coord_label'):
                return

            import win32gui
            cursor_pos = win32gui.GetCursorPos()
            self.screen_coord_label.setText(f"屏幕: ({cursor_pos[0]}, {cursor_pos[1]})")

            if self.window_mgr.is_point_in_target(*cursor_pos):
                win_x, win_y = self.window_mgr.screen_to_window(*cursor_pos)
                self.current_device_coords = (win_x, win_y)
                self.device_coord_label.setText(f"窗口: ({win_x}, {win_y})")

                size = self.window_mgr.get_target_size()
                self.window_status_label.setText(f"目标窗口: {size[0]}x{size[1]}")
            else:
                self.device_coord_label.setText("窗口: (-, -)")
                if self.window_mgr.is_target_valid():
                    self.window_status_label.setText("目标窗口: 鼠标在窗口外")
                else:
                    self.window_status_label.setText("目标窗口: 未选择")
        except Exception as e:
            self.device_coord_label.setText("窗口: (-, -)")
            self.window_status_label.setText(f"错误: {str(e)[:30]}")

    def copy_device_coordinates(self):
        """复制设备坐标到剪贴板"""
        clipboard = QApplication.clipboard()
        clipboard.setText(f"{self.current_device_coords[0]}, {self.current_device_coords[1]}")
        self.statusBar().showMessage(
            f"已复制坐标: {self.current_device_coords[0]}, {self.current_device_coords[1]}", 2000
        )

    # ── 目标窗口 & 输入设置 ──────────────────────────────────

    def on_target_window_selected(self, hwnd, crop_rect, title):
        """目标窗口选择完成"""
        self.window_mgr.set_target(hwnd, crop_rect)
        self.log(f"目标窗口已设置: {title[:40]}", "success")
        if crop_rect:
            x, y, w, h = crop_rect
            self.log(f"裁剪区域: ({x}, {y}) - {w}x{h}", "info")
        else:
            self.log(f"使用全窗口（未裁剪）", "info")

    def on_cursor_lock_changed(self, enabled):
        """光标锁定模式变更"""
        self.controller.set_cursor_lock_mode(enabled)
        self.log(f"光标锁定模式: {'启用' if enabled else '禁用'}", "info")

    def on_input_delay_changed(self, delay_ms):
        """输入延迟变更"""
        self.interception.set_input_delay(delay_ms)

    # ── 录制 ──────────────────────────────────────────────

    def setup_shortcuts(self):
        """设置全局热键（延迟注册，避免 winId() 在初始化阶段阻塞）"""
        self._hotkey_filter = HotkeyFilter()
        QApplication.instance().installNativeEventFilter(self._hotkey_filter)
        self._hotkey_ids = []
        self._current_hotkey_vks = {}  # {"record": vk, "play": vk, "monitor": vk}
        QTimer.singleShot(200, self._register_global_hotkeys)

    def _load_hotkey_settings(self):
        """从 settings.json 读取快捷键配置"""
        defaults = {"record": "F9", "play": "F10", "monitor": "F8"}
        try:
            import os
            if os.path.exists("settings.json"):
                with open("settings.json", 'r', encoding='utf-8') as f:
                    settings = json.load(f)
                hk = settings.get("hotkeys", {})
                return {
                    "record": hk.get("record", defaults["record"]),
                    "play": hk.get("play", defaults["play"]),
                    "monitor": hk.get("monitor", defaults["monitor"]),
                }
        except Exception:
            pass
        return defaults

    def _register_global_hotkeys(self):
        """注册全局热键（从设置读取键位）"""
        hk = self._load_hotkey_settings()
        self._apply_hotkeys(hk)

    def _apply_hotkeys(self, hk_config):
        """应用快捷键配置: 注销旧热键 → 注册新热键 → 更新 UI

        Args:
            hk_config: {"record": "F9", "play": "F10", "monitor": "F8"}
        """
        hwnd = int(self.winId())

        # 注销旧热键
        for hid in self._hotkey_ids:
            ctypes.windll.user32.UnregisterHotKey(hwnd, hid)
        self._hotkey_ids.clear()
        self._hotkey_filter._callbacks.clear()

        # 解析键名 → VK Code
        record_key = hk_config.get("record", "F9")
        play_key = hk_config.get("play", "F10")
        monitor_key = hk_config.get("monitor", "F8")

        record_vk = FKEY_TO_VK.get(record_key, 0x78)
        play_vk = FKEY_TO_VK.get(play_key, 0x79)
        monitor_vk = FKEY_TO_VK.get(monitor_key, 0x77)

        self._current_hotkey_vks = {
            "record": record_vk, "play": play_vk, "monitor": monitor_vk
        }

        HOTKEY_ID_RECORD = 1
        HOTKEY_ID_PLAY = 2
        HOTKEY_ID_MONITOR = 3

        # 注册回调
        self._hotkey_filter.register_hotkey(HOTKEY_ID_RECORD, lambda: self.toggle_recording())
        self._hotkey_filter.register_hotkey(HOTKEY_ID_PLAY, lambda: self.toggle_play())
        self._hotkey_filter.register_hotkey(HOTKEY_ID_MONITOR, lambda: self.toggle_monitoring_hotkey())

        hotkeys = [
            (HOTKEY_ID_RECORD, record_vk, record_key),
            (HOTKEY_ID_PLAY, play_vk, play_key),
            (HOTKEY_ID_MONITOR, monitor_vk, monitor_key),
        ]

        for hid, vk, name in hotkeys:
            result = ctypes.windll.user32.RegisterHotKey(hwnd, hid, 0x4000, vk)
            if result:
                print(f"[MainWindow] 全局热键 {name} 注册成功")
                self._hotkey_ids.append(hid)
            else:
                print(f"[MainWindow] 全局热键 {name} 注册失败")

        # 更新按钮文本
        self.center_panel.update_hotkey_labels(record_key, play_key, monitor_key)

        # 更新录制按钮文本
        if self.is_recording:
            self.record_btn.setText(f"停止录制 ({record_key})")
        else:
            self.record_btn.setText(f"开始录制 ({record_key})")

        # 更新 KeyboardMonitor 过滤列表
        self.controller.set_hotkey_vk_filter(
            {record_vk, play_vk, monitor_vk}
        )

    def toggle_recording(self, checked=None):
        """切换录制状态"""
        if checked is None:
            checked = not self.is_recording

        if checked:
            mode_text = self.record_mode_combo.currentText()
            mode_map = {"鼠标录制": "mouse", "键盘录制": "keyboard", "键鼠同时录制": "both"}
            mode = mode_map.get(mode_text, "mouse")

            self.controller.set_recording_mode(mode)

            if self.controller.start_recording():
                self.is_recording = True
                self.record_btn.blockSignals(True)
                self.record_btn.setChecked(True)
                self.record_btn.blockSignals(False)
                record_key = VK_TO_FKEY.get(self._current_hotkey_vks.get("record", 0x78), "F9")
                self.record_btn.setText(f"停止录制 ({record_key})")
                self.record_mode_combo.setEnabled(False)
                self.log(f"开始{mode_text}...")
                self.statusBar().showMessage(f"🔴 正在录制 ({mode_text})...")
                self.action_list.clear()
            else:
                QMessageBox.warning(self, "警告", "无法启动录制，请检查目标窗口是否已选择")
                self.record_btn.blockSignals(True)
                self.record_btn.setChecked(False)
                self.record_btn.blockSignals(False)
        else:
            actions = self.controller.stop_recording()
            self.is_recording = False
            self.record_btn.blockSignals(True)
            self.record_btn.setChecked(False)
            self.record_btn.blockSignals(False)
            record_key = VK_TO_FKEY.get(self._current_hotkey_vks.get("record", 0x78), "F9")
            self.record_btn.setText(f"开始录制 ({record_key})")
            self.record_mode_combo.setEnabled(True)
            self.log(f"录制完成，共 {len(actions)} 个操作")
            self.play_btn.setEnabled(len(actions) > 0)
            self.statusBar().showMessage("就绪")

    def on_action_recorded(self, action):
        """处理录制的操作"""
        action_text = ""
        action_type = action['type']
        button = action.get('button', 'left')
        button_label = {'left': '左键', 'right': '右键', 'middle': '中键', 'x1': '侧键1', 'x2': '侧键2'}.get(button, button)

        if action_type == 'click':
            if button == 'left':
                action_text = f"🖱️ 点击 ({action['x']}, {action['y']})"
            else:
                action_text = f"🖱️ {button_label}点击 ({action['x']}, {action['y']})"
        elif action_type == 'long_click':
            action_text = f"🖱️ 长按 ({action['x']}, {action['y']}) {action.get('duration', 0)}ms"
        elif action_type == 'swipe':
            action_text = f"🖱️ 滑动 ({action['x1']}, {action['y1']}) → ({action['x2']}, {action['y2']})"
        elif action_type == 'scroll':
            delta = action.get('delta', 0)
            horizontal = action.get('horizontal', False)
            if horizontal:
                direction = "←" if delta < 0 else "→"
            else:
                direction = "↑" if delta > 0 else "↓"
            action_text = f"🖱️ 滚轮{direction} ({action.get('x', 0)}, {action.get('y', 0)}) delta={delta}"
        elif action_type == 'key_down':
            action_text = f"⌨️ 按键 ↓{action.get('key_name', '')}"
        elif action_type == 'key_up':
            action_text = f"⌨️ 按键 ↑{action.get('key_name', '')}"
        elif action_type == 'text':
            action_text = f"⌨️ 输入: {action['text']}"

        if action_text:
            time_ms = action.get('start_time_ms', 0)
            action_text += f" +{time_ms / 1000:.1f}s"
            self.action_list.addItem(action_text)
            self.action_list.scrollToBottom()

        count = len(self.controller.recorded_actions)
        self.record_info_label.setText(f"已录制 {count} 个操作")

    def on_randomization_changed(self):
        """随机化设置改变"""
        enabled = self.center_panel.random_check.isChecked()
        position_range = self.center_panel.position_spin.value() / 100.0
        delay_range = self.center_panel.delay_spin.value() / 100.0
        longpress_range = self.center_panel.longpress_spin.value() / 100.0

        self.controller.set_randomization(enabled, position_range, delay_range, longpress_range)

        self.center_panel.position_spin.setEnabled(enabled)
        self.center_panel.delay_spin.setEnabled(enabled)
        self.center_panel.longpress_spin.setEnabled(enabled)

        if enabled:
            self.log(f"随机化已启用: 位置±{position_range * 100:.1f}%, "
                     f"延迟±{delay_range * 100:.1f}%, 长按±{longpress_range * 100:.1f}%", "success")
        else:
            self.log("随机化已禁用", "info")

    def on_input_mode_changed(self, mode):
        """输入模式切换"""
        if mode:
            self.controller.set_input_mode(mode)
            label = "Interception（硬件注入）" if mode == "interception" else "PostMessage（后台注入）"
            self.log(f"输入模式: {label}", "info")

    # ── 播放 ──────────────────────────────────────────────

    def toggle_play(self):
        """快捷键切换播放/停止"""
        if self.controller.playing:
            self.stop_playing()
        else:
            self.play_recording()

    def play_recording(self):
        """播放录制"""
        if not self.controller.recorded_actions:
            QMessageBox.information(self, "提示", "没有可播放的录制")
            return

        self.play_btn.setEnabled(False)
        self.stop_play_btn.setEnabled(True)

        speed = self.speed_spin.value()
        use_random = self.random_enabled_check.isChecked()

        self.log(f"开始播放录制 (速度: {speed}x, 随机化: {'开启' if use_random else '关闭'})...")
        self.statusBar().showMessage("▶ 正在播放...")

        from threading import Thread
        def play_thread():
            result = self.controller.play_recording(
                self.controller.recorded_actions, speed, use_random)
            self.playback_finished.emit(result if result else False)

        Thread(target=play_thread, daemon=True).start()

    @pyqtSlot(bool)
    def _on_playback_finished(self, success):
        """播放完成回调（主线程）"""
        self.play_btn.setEnabled(True)
        self.stop_play_btn.setEnabled(False)
        if success:
            self.statusBar().showMessage("播放完成")
        else:
            self.statusBar().showMessage("播放中断或失败")

    def stop_playing(self):
        """停止播放"""
        if self.controller.stop_playing():
            self.log("播放已停止")
            self.play_btn.setEnabled(True)
            self.stop_play_btn.setEnabled(False)
            self.statusBar().showMessage("播放已停止")

    def save_recording(self):
        """保存录制"""
        if not self.controller.recorded_actions:
            QMessageBox.information(self, "提示", "没有可保存的录制")
            return

        filename, _ = QFileDialog.getSaveFileName(
            self, "保存录制", "", "JSON文件 (*.json)")
        if filename:
            self.controller.save_recording(filename)
            self.log(f"录制已保存到: {filename}")

    def load_recording(self):
        """加载录制"""
        filename, _ = QFileDialog.getOpenFileName(
            self, "加载录制", "", "JSON文件 (*.json)")
        if filename:
            try:
                actions = self.controller.load_recording(filename)
                self.controller.recorded_actions = actions
                self.log(f"已加载录制: {filename} ({len(actions)} 个操作)")
                self.play_btn.setEnabled(len(actions) > 0)
                self.record_info_label.setText(f"已加载 {len(actions)} 个操作")

                self.action_list.clear()
                for action in actions:
                    self.on_action_recorded(action)
            except Exception as e:
                QMessageBox.critical(self, "错误", f"加载失败: {str(e)}")

    # ── 监控 ──────────────────────────────────────────────

    def toggle_monitoring_hotkey(self):
        """快捷键切换监控状态"""
        current = self.center_panel.monitor_btn.isChecked()
        self.center_panel.monitor_btn.setChecked(not current)

    def add_monitor_task(self):
        """添加监控任务"""
        dialog = MonitorTaskDialog(self.controller, self)
        if dialog.exec():
            config = dialog.get_config()
            if config:
                self.auto_monitor.add_monitor_config(config)
                self.refresh_monitor_task_list()
                self.log(f"添加监控任务: {config['name']}")

    def copy_monitor_task(self):
        """复制监控任务"""
        current = self.monitor_task_list.currentRow()
        if current >= 0 and current < len(self.auto_monitor.monitor_configs):
            import copy
            original_config = self.auto_monitor.monitor_configs[current]
            config_copy = copy.deepcopy(original_config)
            original_name = config_copy.get('name', '未命名')
            config_copy['name'] = f"{original_name}_副本"
            if 'last_executed' in config_copy:
                config_copy['last_executed'] = 0
            self.auto_monitor.add_monitor_config(config_copy)
            self.refresh_monitor_task_list()
            self.log(f"复制监控任务: {original_name} → {config_copy['name']}")
        else:
            QMessageBox.information(self, "提示", "请先选择要复制的任务")

    def edit_monitor_task(self):
        """编辑监控任务"""
        current = self.monitor_task_list.currentRow()
        if current >= 0 and current < len(self.auto_monitor.monitor_configs):
            config = self.auto_monitor.monitor_configs[current]
            dialog = MonitorTaskDialog(self.controller, self, config)
            if dialog.exec():
                new_config = dialog.get_config()
                if new_config:
                    self.auto_monitor.update_monitor_config(current, new_config)
                    self.refresh_monitor_task_list()
                    self.log(f"更新监控任务: {new_config['name']}")

    def remove_monitor_task(self):
        """删除监控任务"""
        current = self.monitor_task_list.currentRow()
        if current >= 0:
            reply = QMessageBox.question(
                self, "确认", "确定要删除这个监控任务吗？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            if reply == QMessageBox.StandardButton.Yes:
                self.auto_monitor.remove_monitor_config(current)
                self.refresh_monitor_task_list()

    def refresh_monitor_task_list(self):
        """刷新监控任务列表"""
        self.monitor_task_list.clear()
        for config in self.auto_monitor.monitor_configs:
            status = "✓" if config.get('enabled', True) else "✗"
            self.monitor_task_list.addItem(f"[{status}] {config['name']}")

    def save_monitor_scheme(self):
        """保存监控方案"""
        if not self.auto_monitor.monitor_configs:
            QMessageBox.information(self, "提示", "没有监控任务可保存")
            return
        filename, _ = QFileDialog.getSaveFileName(
            self, "保存监控方案", "", "JSON文件 (*.json)")
        if filename:
            if self.auto_monitor.save_scheme(filename):
                QMessageBox.information(self, "成功", "监控方案已保存")

    def load_monitor_scheme(self):
        """加载监控方案"""
        filename, _ = QFileDialog.getOpenFileName(
            self, "加载监控方案", "", "JSON文件 (*.json)")
        if filename:
            if self.auto_monitor.load_scheme(filename):
                self.refresh_monitor_task_list()
                QMessageBox.information(self, "成功", "监控方案已加载")

    def toggle_monitoring(self, checked):
        """切换自动监控状态"""
        if checked:
            if self.auto_monitor.start_monitoring():
                self.log("开始自动监控", "success")
                self.center_panel.monitor_status_label.setText("状态: 监控中...")
                self.center_panel.monitor_status_label.setStyleSheet("color: #4CAF50;")
            else:
                self.center_panel.monitor_btn.setChecked(False)
                QMessageBox.warning(self, "警告", "无法启动监控，请检查是否有配置任务")
        else:
            self.auto_monitor.stop_monitoring()
            self.log("停止自动监控", "info")
            self.center_panel.monitor_status_label.setText("状态: 已停止")
            self.center_panel.monitor_status_label.setStyleSheet("color: #666;")

    def on_interval_changed(self, value):
        """检查间隔改变"""
        self.auto_monitor.set_check_interval(value)

    def on_auto_match_found(self, match_info):
        """自动匹配找到"""
        config = match_info['config']
        time_str = match_info['time']
        self.log(f"[{time_str}] ✅ 触发任务: {config['name']}")

    def on_monitor_status_update(self, status):
        """监控状态更新"""
        self.monitor_status_label.setText(f"状态: {status}")

    # ── 设置 & 版本 ─────────────────────────────────────────

    def open_settings(self):
        """打开设置对话框"""
        dialog = SettingsDialog(self)
        dialog.settings_changed.connect(self.on_settings_changed)
        dialog.exec()

    def open_advanced_monitor(self):
        """打开高级监控功能对话框"""
        from gui.advanced_monitor_dialog import AdvancedMonitorDialog
        dialog = AdvancedMonitorDialog(self.auto_monitor, self)
        dialog.exec()

    def on_settings_changed(self, settings):
        """设置改变时的处理"""
        interval = settings["performance"]["coord_update_interval"]
        self.coord_timer.setInterval(interval)

        max_lines = settings["ui"]["max_log_lines"]
        doc = self.log_text.document()
        doc.setMaximumBlockCount(max_lines)

        # 快捷键变更
        hk = settings.get("hotkeys", {})
        if hk:
            self._apply_hotkeys(hk)

        self.log("设置已更新")

    def load_and_apply_settings(self):
        """加载并应用设置"""
        try:
            import os
            settings_file = "settings.json"
            if os.path.exists(settings_file):
                with open(settings_file, 'r', encoding='utf-8') as f:
                    settings = json.load(f)

                from core.window_capture import WindowCapture
                WindowCapture.enable_log(settings.get("capture", {}).get("debug_log", False))

                if hasattr(self, 'coord_timer'):
                    self.on_settings_changed(settings)

            # 同步输入模式到左侧面板下拉框
            current_mode = self.controller.get_input_mode()
            idx = self.left_panel.input_mode_combo.findData(current_mode)
            if idx >= 0:
                self.left_panel.input_mode_combo.blockSignals(True)
                self.left_panel.input_mode_combo.setCurrentIndex(idx)
                self.left_panel.input_mode_combo.blockSignals(False)

        except Exception as e:
            self.log(f"加载设置失败: {str(e)}")

    def check_latest_version(self):
        """检查最新版本"""
        from threading import Thread

        def fetch():
            try:
                req = urllib.request.Request(
                    'https://github.com/Exmeaning/ClickYen/releases/latest',
                    headers={'User-Agent': 'Mozilla/5.0'}
                )
                with urllib.request.urlopen(req, timeout=5) as response:
                    final_url = response.geturl()
                    if '/tag/' in final_url:
                        self.version_fetched.emit(final_url.split('/tag/')[-1])
                    else:
                        self.version_fetched.emit('')
            except Exception:
                self.version_fetched.emit('')

        Thread(target=fetch, daemon=True).start()

    def update_version_label(self, version):
        """更新版本标签"""
        if version:
            text = f'<a href="https://github.com/Exmeaning/ClickYen/releases/latest" style="color: #2196F3;">最新版本: v{version}</a>'
            self.log(f"最新版本: v{version}", "info")
        else:
            text = '<span style="color: #999;">版本检测失败</span>'
            self.log("版本检测失败", "warning")
        self.left_panel.version_check_label.setText(text)

    # ── 杂项 ──────────────────────────────────────────────

    def take_screenshot(self):
        """截图"""
        self.log("正在截图...")
        img = self.controller.screenshot()
        if img:
            filename = f"screenshot_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
            img.save(filename)
            self.log(f"截图保存为 {filename}")
        else:
            self.log("截图失败")

    def show_about(self):
        """显示关于对话框"""
        QMessageBox.about(self, "关于 ClickYen",
            f"<h2>ClickYen v{VERSION}</h2>"
            f"<p>智能点击助手 - Windows 窗口自动化控制</p>"
            f"<p>基于 Interception 驱动的硬件级键鼠模拟</p>"
        )

    def select_template(self):
        filename, _ = QFileDialog.getOpenFileName(self, "选择模板", "", "图片 (*.png *.jpg *.jpeg)")
        if filename:
            self.template_input.setText(filename)

    def on_method_changed(self, method):
        self.controller.matcher.set_method(method)

    def search_template(self):
        template = self.template_input.text()
        if not template:
            QMessageBox.warning(self, "提示", "请先选择模板")
            return

        threshold = self.threshold_spin.value()
        self.search_btn.setText("搜索中...")
        self.search_btn.setEnabled(False)

        from threading import Thread
        def search():
            start = time.time()
            result = self.controller.find_template(template, threshold)
            elapsed = time.time() - start
            if result:
                x, y, conf = result
                self.match_result.setText(f"✅ 找到位置: ({x}, {y}) 置信度: {conf:.2%}")
            else:
                self.match_result.setText("❌ 未找到匹配")
            self.search_btn.setText("🔍 搜索")
            self.search_btn.setEnabled(True)
            self.log(f"搜索耗时: {elapsed:.2f}s")

        Thread(target=search, daemon=True).start()

    def log(self, message, level="info"):
        """添加日志"""
        self.right_panel.log(message, level)

    def clear_log(self):
        """清空日志"""
        self.log_text.clear()

    def closeEvent(self, event):
        """关闭事件"""
        # 注销所有全局热键
        if hasattr(self, '_hotkey_ids'):
            for hid in self._hotkey_ids:
                ctypes.windll.user32.UnregisterHotKey(int(self.winId()), hid)
        # 移除原生事件过滤器
        if hasattr(self, '_hotkey_filter'):
            QApplication.instance().removeNativeEventFilter(self._hotkey_filter)

        confirm_exit = True
        try:
            import os
            settings_file = "settings.json"
            if os.path.exists(settings_file):
                with open(settings_file, 'r', encoding='utf-8') as f:
                    settings = json.load(f)
                    confirm_exit = settings.get("ui", {}).get("confirm_exit", True)
        except Exception:
            pass

        if confirm_exit:
            reply = QMessageBox.question(
                self, "退出确认",
                "请在退出前检查方案是否保存！\n\n确定要退出吗？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No
            )
            if reply != QMessageBox.StandardButton.Yes:
                event.ignore()
                return

        # 清理资源
        if self.is_recording:
            self.controller.stop_recording()
        if self.auto_monitor.monitoring:
            self.auto_monitor.stop_monitoring()
        event.accept()
