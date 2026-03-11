"""左侧面板 - Windows 窗口目标选择"""
from PyQt6.QtWidgets import *
from PyQt6.QtCore import *
from PyQt6.QtGui import *
from utils.config import VERSION


class LeftPanel(QWidget):
    """左侧面板：窗口选择、区域裁剪、输入设置、驱动状态"""

    # 信号定义
    target_window_selected = pyqtSignal(int, object, str)  # hwnd, crop_rect (None=全窗口), title
    cursor_lock_mode_changed = pyqtSignal(bool)
    input_delay_changed = pyqtSignal(int)
    input_mode_changed = pyqtSignal(str)  # "interception" | "postmessage"

    def __init__(self, parent=None):
        super().__init__(parent)
        self._window_mgr = None
        self._interception_mgr = None
        self._selected_hwnd = None
        self._crop_rect = None
        self._pick_timer = None
        self._window_data_list = []  # 缓存窗口列表数据
        self.init_ui()

    # ── UI 构建 ───────────────────────────────────────────

    def init_ui(self):
        outer_layout = QVBoxLayout(self)
        outer_layout.setContentsMargins(0, 0, 0, 0)

        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setFrameShape(QFrame.Shape.NoFrame)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        scroll_content = QWidget()
        layout = QVBoxLayout(scroll_content)
        layout.setSpacing(8)
        layout.setContentsMargins(10, 6, 10, 6)

        layout.addWidget(self._build_title())
        layout.addWidget(self._build_target_window_group())
        layout.addWidget(self._build_crop_group())
        layout.addWidget(self._build_input_group())
        layout.addWidget(self._build_driver_group())
        layout.addStretch()

        scroll_area.setWidget(scroll_content)
        outer_layout.addWidget(scroll_area)

        self.setStyleSheet("""
            QGroupBox {
                font-size: 12px;
                font-weight: bold;
                border: 1px solid #e0e0e0;
                border-radius: 6px;
                margin-top: 8px;
                padding-top: 8px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 8px;
                padding: 0 6px 0 6px;
            }
            QComboBox {
                min-width: 0px;
            }
        """)

    # ── 标题 ──────────────────────────────────────────────

    def _build_title(self):
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setSpacing(2)
        layout.setContentsMargins(0, 0, 0, 0)

        title = QLabel("ClickYen")
        title.setStyleSheet("font-size: 26px; font-weight: bold; color: #424242; padding: 4px 0;")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)

        ver = QLabel(f"v{VERSION}")
        ver.setStyleSheet("color: #666; font-size: 11px;")
        ver.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.version_check_label = QLabel("检查更新中...")
        self.version_check_label.setStyleSheet("color: #FF9800; font-size: 10px;")
        self.version_check_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        layout.addWidget(title)
        layout.addWidget(ver)
        layout.addWidget(self.version_check_label)

        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setFixedHeight(1)
        line.setStyleSheet("background-color: #e0e0e0;")
        layout.addWidget(line)

        return widget

    # ── 目标窗口 ──────────────────────────────────────────

    def _build_target_window_group(self):
        group = QGroupBox("🎯 目标窗口")
        layout = QVBoxLayout()
        layout.setSpacing(6)
        layout.setContentsMargins(8, 12, 8, 8)

        # 窗口下拉框
        self.window_combo = QComboBox()
        self.window_combo.setMinimumHeight(30)
        self.window_combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.window_combo.setMinimumContentsLength(10)
        self.window_combo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.window_combo.setStyleSheet("""
            QComboBox {
                font-size: 12px; padding: 4px 6px;
                border: 1px solid #9E9E9E; border-radius: 4px;
            }
            QComboBox:hover { border-color: #757575; }
        """)
        self.window_combo.currentIndexChanged.connect(self._on_window_selected)

        # 搜索过滤
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("🔍 搜索窗口标题/类名...")
        self.search_input.setMinimumHeight(28)
        self.search_input.textChanged.connect(self._on_search_changed)

        # 按钮行
        btn_row = QHBoxLayout()
        btn_row.setSpacing(6)
        self.pick_btn = QPushButton("🎯 鼠标拾取")
        self.pick_btn.setMinimumHeight(30)
        self.pick_btn.clicked.connect(self.start_pick_mode)
        self.refresh_windows_btn = QPushButton("🔄 刷新")
        self.refresh_windows_btn.setMinimumHeight(30)
        self.refresh_windows_btn.clicked.connect(self.refresh_window_list)
        btn_row.addWidget(self.pick_btn)
        btn_row.addWidget(self.refresh_windows_btn)

        # 窗口信息
        self.window_info_label = QLabel("默认: 整个桌面\n选择窗口可限定操作范围")
        self.window_info_label.setStyleSheet("""
            QLabel {
                color: #666; font-size: 11px; padding: 6px;
                background-color: #f5f5f5; border-radius: 4px;
            }
        """)
        self.window_info_label.setWordWrap(True)
        self.window_info_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)

        layout.addWidget(QLabel("选择窗口:"))
        layout.addWidget(self.window_combo)
        layout.addWidget(self.search_input)
        layout.addLayout(btn_row)
        layout.addWidget(self.window_info_label)
        group.setLayout(layout)
        return group

    # ── 区域设置 ──────────────────────────────────────────

    def _build_crop_group(self):
        group = QGroupBox("✂ 区域设置")
        layout = QVBoxLayout()
        layout.setSpacing(6)
        layout.setContentsMargins(8, 12, 8, 8)

        self.crop_btn = QPushButton("✂ 设置裁剪区域")
        self.crop_btn.setMinimumHeight(32)
        self.crop_btn.clicked.connect(self._open_crop_dialog)

        self.crop_info_label = QLabel("裁剪: 未设置（默认使用全窗口）")
        self.crop_info_label.setStyleSheet("color: #666; font-size: 11px;")
        self.crop_info_label.setWordWrap(True)

        self.clear_crop_btn = QPushButton("清除裁剪")
        self.clear_crop_btn.setMinimumHeight(28)
        self.clear_crop_btn.clicked.connect(self._clear_crop)
        self.clear_crop_btn.setEnabled(False)

        layout.addWidget(self.crop_btn)
        layout.addWidget(self.crop_info_label)
        layout.addWidget(self.clear_crop_btn)
        group.setLayout(layout)
        return group

    # ── 输入设置 ──────────────────────────────────────────

    def _build_input_group(self):
        group = QGroupBox("⌨ 输入设置")
        layout = QVBoxLayout()
        layout.setSpacing(6)
        layout.setContentsMargins(8, 12, 8, 8)

        # 注入方式
        mode_row = QHBoxLayout()
        mode_label = QLabel("注入方式:")
        mode_label.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        mode_row.addWidget(mode_label)
        self.input_mode_combo = QComboBox()
        self.input_mode_combo.addItem("Interception", "interception")
        self.input_mode_combo.addItem("PostMessage", "postmessage")
        self.input_mode_combo.setCurrentIndex(0)  # 默认 Interception
        self.input_mode_combo.setMinimumHeight(28)
        self.input_mode_combo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.input_mode_combo.setToolTip(
            "选择回放时使用的输入注入方式：\n\n"
            "Interception（推荐）\n"
            "  · 硬件级驱动模拟，兼容性最好\n"
            "  · 回放时会占用系统光标\n"
            "  · 适用于绝大多数应用和游戏\n\n"
            "PostMessage\n"
            "  · 通过窗口消息注入，完全后台运行\n"
            "  · 回放时不影响鼠标，可正常操作电脑\n"
            "  · 部分应用/游戏可能不响应此方式"
        )
        self.input_mode_combo.currentIndexChanged.connect(
            lambda: self.input_mode_changed.emit(self.input_mode_combo.currentData())
        )
        mode_row.addWidget(self.input_mode_combo)
        layout.addLayout(mode_row)

        # 光标模式
        layout.addWidget(QLabel("光标模式:"))
        self.cursor_free_radio = QRadioButton("自由模式（光标跟随操作）")
        self.cursor_lock_radio = QRadioButton("锁定模式（操作后恢复位置）")
        self.cursor_free_radio.setChecked(True)
        self.cursor_free_radio.toggled.connect(
            lambda checked: self.cursor_lock_mode_changed.emit(not checked) if checked else None
        )
        self.cursor_lock_radio.toggled.connect(
            lambda checked: self.cursor_lock_mode_changed.emit(checked) if checked else None
        )
        layout.addWidget(self.cursor_free_radio)
        layout.addWidget(self.cursor_lock_radio)

        # 输入延迟
        delay_row = QHBoxLayout()
        delay_label = QLabel("输入延迟:")
        delay_label.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        delay_row.addWidget(delay_label)
        self.input_delay_spin = QSpinBox()
        self.input_delay_spin.setRange(0, 100)
        self.input_delay_spin.setValue(10)
        self.input_delay_spin.setSuffix(" ms")
        self.input_delay_spin.setMinimumHeight(28)
        self.input_delay_spin.valueChanged.connect(self.input_delay_changed.emit)
        delay_row.addWidget(self.input_delay_spin)
        delay_row.addStretch()
        layout.addLayout(delay_row)

        group.setLayout(layout)
        return group

    # ── 驱动状态 ──────────────────────────────────────────

    def _build_driver_group(self):
        group = QGroupBox("🔌 驱动状态")
        layout = QVBoxLayout()
        layout.setSpacing(4)
        layout.setContentsMargins(8, 12, 8, 8)

        self.driver_status_label = QLabel("Interception: ⏳ 检测中...")
        self.driver_status_label.setStyleSheet("font-size: 11px;")
        self.driver_status_label.setWordWrap(True)
        self.mouse_device_label = QLabel("鼠标设备: ⏳")
        self.mouse_device_label.setStyleSheet("font-size: 11px;")
        self.mouse_device_label.setWordWrap(True)
        self.keyboard_device_label = QLabel("键盘设备: ⏳")
        self.keyboard_device_label.setStyleSheet("font-size: 11px;")
        self.keyboard_device_label.setWordWrap(True)

        self.recapture_btn = QPushButton("重新捕获设备")
        self.recapture_btn.setMinimumHeight(28)
        self.recapture_btn.clicked.connect(self._on_recapture_clicked)

        layout.addWidget(self.driver_status_label)
        layout.addWidget(self.mouse_device_label)
        layout.addWidget(self.keyboard_device_label)
        layout.addWidget(self.recapture_btn)
        group.setLayout(layout)
        return group

    # ── 公共方法 ──────────────────────────────────────────

    def set_window_manager(self, window_mgr):
        """设置 WindowManager 引用"""
        self._window_mgr = window_mgr
        self.refresh_window_list()

    def set_interception_manager(self, interception_mgr):
        """设置 InterceptionManager 引用"""
        self._interception_mgr = interception_mgr
        self._refresh_driver_status()

    def get_selected_hwnd(self):
        """获取当前选中的窗口句柄"""
        return self._selected_hwnd

    def refresh_window_list(self):
        """刷新窗口列表"""
        if not self._window_mgr:
            return

        self.window_combo.blockSignals(True)
        self.window_combo.clear()
        self._window_data_list.clear()

        windows = self._window_mgr.list_windows(visible_only=True)
        search_text = self.search_input.text().strip().lower()

        self.window_combo.addItem("-- 请选择窗口 --", None)

        for w in windows:
            title = w["title"]
            cls = w["class_name"]
            exe = w["exe_name"]
            # 跳过自身窗口
            if "ClickYen" in title:
                continue
            # 搜索过滤
            if search_text:
                haystack = f"{title} {cls} {exe}".lower()
                if search_text not in haystack:
                    continue
            display = f"{title}  [{exe}]" if exe else title
            self.window_combo.addItem(display, w["hwnd"])
            self._window_data_list.append(w)

        self.window_combo.blockSignals(False)

        # 如果之前有选中的窗口，尝试恢复选中
        if self._selected_hwnd is not None:
            for i in range(1, self.window_combo.count()):
                if self.window_combo.itemData(i) == self._selected_hwnd:
                    self.window_combo.setCurrentIndex(i)
                    return

    def update_driver_status(self, status_dict):
        """更新驱动状态显示

        Args:
            status_dict: InterceptionManager.get_status() 返回的字典
        """
        installed = status_dict.get("driver_installed", False)
        available = status_dict.get("available", False)
        kb_dev = status_dict.get("keyboard_device", 0)
        ms_dev = status_dict.get("mouse_device", 0)
        backend = status_dict.get("backend", "unknown")

        if installed:
            self.driver_status_label.setText("Interception: ✅ 已安装")
            self.driver_status_label.setStyleSheet("font-size: 11px; color: #2E7D32;")
        else:
            self.driver_status_label.setText(f"Interception: ❌ 未安装 (回退: {backend})")
            self.driver_status_label.setStyleSheet("font-size: 11px; color: #C62828;")

        if available and ms_dev:
            self.mouse_device_label.setText(f"鼠标设备: ✅ 已捕获 (#{ms_dev})")
            self.mouse_device_label.setStyleSheet("font-size: 11px; color: #2E7D32;")
        elif installed:
            self.mouse_device_label.setText("鼠标设备: ⚠ 未捕获（点击下方按钮）")
            self.mouse_device_label.setStyleSheet("font-size: 11px; color: #E65100;")
        else:
            self.mouse_device_label.setText("鼠标设备: ❌ 未捕获")
            self.mouse_device_label.setStyleSheet("font-size: 11px; color: #C62828;")

        if available and kb_dev:
            self.keyboard_device_label.setText(f"键盘设备: ✅ 已捕获 (#{kb_dev})")
            self.keyboard_device_label.setStyleSheet("font-size: 11px; color: #2E7D32;")
        elif installed:
            self.keyboard_device_label.setText("键盘设备: ⚠ 未捕获（点击下方按钮）")
            self.keyboard_device_label.setStyleSheet("font-size: 11px; color: #E65100;")
        else:
            self.keyboard_device_label.setText("键盘设备: ❌ 未捕获")
            self.keyboard_device_label.setStyleSheet("font-size: 11px; color: #C62828;")

    # ── 内部槽 ────────────────────────────────────────────

    def _on_window_selected(self, index):
        """下拉框选择窗口"""
        hwnd = self.window_combo.itemData(index)
        if hwnd is None:
            self._selected_hwnd = None
            self._crop_rect = None
            self.window_info_label.setText("默认: 整个桌面\n选择窗口可限定操作范围")
            self.window_info_label.setStyleSheet(
                "color: #666; font-size: 11px; padding: 6px; background-color: #f5f5f5; border-radius: 4px;"
            )
            self.crop_info_label.setText("裁剪: 未设置（默认使用全窗口）")
            self.crop_info_label.setStyleSheet("color: #666; font-size: 11px;")
            self.clear_crop_btn.setEnabled(False)
            return

        self._selected_hwnd = hwnd
        self._crop_rect = None  # 重置裁剪区域
        self._update_window_info(hwnd)

        # 立即发射信号，crop_rect=None 表示使用全窗口
        title = self.window_combo.currentText()
        self.target_window_selected.emit(hwnd, None, title)

        # 更新裁剪信息标签
        self.crop_info_label.setText("裁剪: 未设置（默认使用全窗口）")
        self.crop_info_label.setStyleSheet("color: #2196F3; font-size: 11px;")
        self.clear_crop_btn.setEnabled(False)

    def _on_search_changed(self, _text):
        """搜索框文本变化时重新过滤"""
        self.refresh_window_list()

    def _update_window_info(self, hwnd):
        """更新窗口信息标签"""
        if not self._window_mgr:
            return
        # 从缓存中查找
        info = None
        for w in self._window_data_list:
            if w["hwnd"] == hwnd:
                info = w
                break
        if not info:
            self.window_info_label.setText("窗口信息获取失败")
            return

        rect = info.get("rect", (0, 0, 0, 0))
        w = rect[2] - rect[0]
        h = rect[3] - rect[1]
        lines = [
            f"句柄: 0x{hwnd:08X}",
            f"类名: {info.get('class_name', '')}",
            f"尺寸: {w}x{h}",
            f"进程: {info.get('exe_name', '?')} (PID {info.get('pid', '?')})",
        ]
        self.window_info_label.setText("\n".join(lines))
        self.window_info_label.setStyleSheet(
            "color: #2E7D32; font-size: 11px; padding: 6px;"
            "background-color: #E8F5E9; border: 1px solid #4CAF50; border-radius: 4px;"
        )

    # ── 鼠标拾取 ──────────────────────────────────────────

    def start_pick_mode(self):
        """进入鼠标拾取模式：用户点击任意窗口后自动选中"""
        self.pick_btn.setText("🎯 点击目标窗口...")
        self.pick_btn.setEnabled(False)
        self.setCursor(Qt.CursorShape.CrossCursor)

        self._pick_timer = QTimer(self)
        self._pick_timer.setInterval(50)
        self._pick_timer.timeout.connect(self._poll_pick)
        self._pick_timer.start()

        # 5 秒超时自动取消
        QTimer.singleShot(5000, self._cancel_pick_mode)

    def _poll_pick(self):
        """轮询检测鼠标左键是否按下"""
        import ctypes
        # GetAsyncKeyState: 如果最高位为 1 则按键当前被按下
        if ctypes.windll.user32.GetAsyncKeyState(0x01) & 0x8000:
            self._finish_pick()

    def _finish_pick(self):
        """拾取完成"""
        if self._pick_timer:
            self._pick_timer.stop()
            self._pick_timer = None
        self.pick_btn.setText("🎯 鼠标拾取")
        self.pick_btn.setEnabled(True)
        self.setCursor(Qt.CursorShape.ArrowCursor)

        if not self._window_mgr:
            return

        info = self._window_mgr.get_window_at_cursor()
        if info and info["hwnd"]:
            hwnd = info["hwnd"]
            # 尝试在下拉框中定位
            found = False
            for i in range(1, self.window_combo.count()):
                if self.window_combo.itemData(i) == hwnd:
                    self.window_combo.setCurrentIndex(i)
                    found = True
                    break
            if not found:
                # 窗口不在列表中，刷新后再试
                self.refresh_window_list()
                for i in range(1, self.window_combo.count()):
                    if self.window_combo.itemData(i) == hwnd:
                        self.window_combo.setCurrentIndex(i)
                        break

    def _cancel_pick_mode(self):
        """超时取消拾取"""
        if self._pick_timer and self._pick_timer.isActive():
            self._pick_timer.stop()
            self._pick_timer = None
            self.pick_btn.setText("🎯 鼠标拾取")
            self.pick_btn.setEnabled(True)
            self.setCursor(Qt.CursorShape.ArrowCursor)

    # ── 裁剪 ─────────────────────────────────────────────

    def _open_crop_dialog(self):
        """打开裁剪对话框"""
        if self._selected_hwnd is None:
            QMessageBox.information(self, "提示", "请先选择目标窗口")
            return

        from gui.crop_dialog import CropDialog
        title = self.window_combo.currentText()
        dialog = CropDialog(self._selected_hwnd, title, self)
        if dialog.exec():
            rect = dialog.get_crop_rect()
            if rect:
                self._crop_rect = rect
                x, y, w, h = rect
                self.crop_info_label.setText(f"裁剪: ({x}, {y}, {w}, {h})")
                self.crop_info_label.setStyleSheet("color: #2E7D32; font-size: 11px;")
                self.clear_crop_btn.setEnabled(True)
                # 发射信号
                self.target_window_selected.emit(self._selected_hwnd, rect, title)

    def _clear_crop(self):
        """清除裁剪区域"""
        self._crop_rect = None
        self.crop_info_label.setText("裁剪: 未设置（默认使用全窗口）")
        self.crop_info_label.setStyleSheet("color: #2196F3; font-size: 11px;")
        self.clear_crop_btn.setEnabled(False)

        # 如果有选中窗口，用 None 重新发射信号（表示全窗口）
        if self._selected_hwnd is not None:
            title = self.window_combo.currentText()
            self.target_window_selected.emit(self._selected_hwnd, None, title)

    # ── 驱动 ─────────────────────────────────────────────

    def _refresh_driver_status(self):
        """从 InterceptionManager 刷新驱动状态"""
        if self._interception_mgr:
            status = self._interception_mgr.get_status()
            self.update_driver_status(status)

    def _on_recapture_clicked(self):
        """重新捕获设备"""
        if not self._interception_mgr:
            return

        QMessageBox.information(
            self, "捕获设备",
            "点击确定后，请在 10 秒内：\n\n"
            "  1. 按下键盘任意键\n"
            "  2. 移动或点击鼠标\n\n"
            "这样程序才能识别到你的键盘和鼠标设备。"
        )

        self.recapture_btn.setEnabled(False)
        self.recapture_btn.setText("捕获中...请按键盘并移动鼠标")
        QApplication.processEvents()

        try:
            self._interception_mgr.capture_devices(timeout_sec=10)
        except Exception:
            pass
        self._refresh_driver_status()
        self.recapture_btn.setEnabled(True)
        self.recapture_btn.setText("重新捕获设备")
