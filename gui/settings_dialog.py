"""设置对话框"""

from PyQt6.QtWidgets import *
from PyQt6.QtCore import *
import json
import os


class SettingsDialog(QDialog):
    """设置对话框"""

    settings_changed = pyqtSignal(dict)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.parent_window = parent
        self.settings_file = "settings.json"
        self.settings = self.load_settings()
        self.initUI()
        self.load_current_settings()

    def initUI(self):
        """初始化UI"""
        self.setWindowTitle("设置")
        self.setModal(True)
        self.setMinimumSize(450, 380)

        layout = QVBoxLayout(self)

        tab_widget = QTabWidget()
        tab_widget.addTab(self._create_interception_tab(), "Interception")
        tab_widget.addTab(self._create_hotkeys_tab(), "快捷键")
        tab_widget.addTab(self._create_recording_tab(), "录制设置")
        tab_widget.addTab(self._create_performance_tab(), "性能设置")
        tab_widget.addTab(self._create_ui_tab(), "界面 / 日志")
        layout.addWidget(tab_widget)

        # 按钮
        btn_layout = QHBoxLayout()
        self.reset_btn = QPushButton("恢复默认")
        self.reset_btn.clicked.connect(self.reset_defaults)
        self.apply_btn = QPushButton("应用")
        self.apply_btn.clicked.connect(self.apply_settings)
        self.ok_btn = QPushButton("确定")
        self.ok_btn.clicked.connect(self.accept_settings)
        self.cancel_btn = QPushButton("取消")
        self.cancel_btn.clicked.connect(self.reject)

        btn_layout.addWidget(self.reset_btn)
        btn_layout.addStretch()
        btn_layout.addWidget(self.apply_btn)
        btn_layout.addWidget(self.ok_btn)
        btn_layout.addWidget(self.cancel_btn)
        layout.addLayout(btn_layout)

    # ── Tab 创建 ──────────────────────────────────────────────

    def _create_interception_tab(self):
        widget = QWidget()
        layout = QVBoxLayout(widget)

        # Interception 驱动设置
        group = QGroupBox("Interception 驱动设置")
        form = QFormLayout()

        self.cursor_lock_check = QCheckBox("启用光标锁定模式")
        self.cursor_lock_check.setToolTip("录制/回放时将光标锁定在窗口内")
        form.addRow(self.cursor_lock_check)

        self.input_delay_spin = QSpinBox()
        self.input_delay_spin.setRange(0, 100)
        self.input_delay_spin.setValue(10)
        self.input_delay_spin.setSuffix(" ms")
        self.input_delay_spin.setToolTip("输入事件之间的延迟，0 为无延迟")
        form.addRow("输入延迟:", self.input_delay_spin)

        self.filter_syskeys_check = QCheckBox("录制时过滤系统键")
        self.filter_syskeys_check.setToolTip("录制时忽略 Win / Alt+Tab 等系统组合键")
        form.addRow(self.filter_syskeys_check)

        group.setLayout(form)
        layout.addWidget(group)
        layout.addStretch()
        return widget

    def _create_hotkeys_tab(self):
        """创建快捷键设置 Tab"""
        widget = QWidget()
        layout = QVBoxLayout(widget)

        group = QGroupBox("全局快捷键")
        form = QFormLayout()

        fkeys = [f"F{i}" for i in range(1, 13)]

        self.hotkey_record_combo = QComboBox()
        self.hotkey_record_combo.addItems(fkeys)
        self.hotkey_record_combo.setToolTip("开始/停止录制的快捷键")
        form.addRow("录制 开始/停止:", self.hotkey_record_combo)

        self.hotkey_play_combo = QComboBox()
        self.hotkey_play_combo.addItems(fkeys)
        self.hotkey_play_combo.setToolTip("播放/停止播放的快捷键")
        form.addRow("播放 开始/停止:", self.hotkey_play_combo)

        self.hotkey_monitor_combo = QComboBox()
        self.hotkey_monitor_combo.addItems(fkeys)
        self.hotkey_monitor_combo.setToolTip("开始/停止监控的快捷键")
        form.addRow("监控 开始/停止:", self.hotkey_monitor_combo)

        group.setLayout(form)
        layout.addWidget(group)

        # 冲突提示
        self._hotkey_conflict_label = QLabel("")
        self._hotkey_conflict_label.setStyleSheet("color: #F44336; font-size: 12px; padding: 4px;")
        self._hotkey_conflict_label.setWordWrap(True)
        layout.addWidget(self._hotkey_conflict_label)

        # 连接冲突检测
        for combo in [self.hotkey_record_combo, self.hotkey_play_combo, self.hotkey_monitor_combo]:
            combo.currentTextChanged.connect(self._check_hotkey_conflict)

        hint = QLabel("提示: 快捷键修改后点击「应用」或「确定」即可生效。\n请避免使用系统常用快捷键（如 F1=帮助, F5=刷新, F11=全屏）。")
        hint.setStyleSheet("color: #888; font-size: 11px; padding: 8px;")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        layout.addStretch()
        return widget

    def _check_hotkey_conflict(self):
        """检查快捷键是否冲突"""
        keys = [
            self.hotkey_record_combo.currentText(),
            self.hotkey_play_combo.currentText(),
            self.hotkey_monitor_combo.currentText(),
        ]
        if len(keys) != len(set(keys)):
            self._hotkey_conflict_label.setText("⚠️ 存在重复的快捷键，请修改！")
            return False
        self._hotkey_conflict_label.setText("")
        return True

    def _create_recording_tab(self):
        widget = QWidget()
        layout = QVBoxLayout(widget)

        group = QGroupBox("录制选项")
        form = QFormLayout()

        self.default_mode_combo = QComboBox()
        self.default_mode_combo.addItem("仅鼠标", "mouse")
        self.default_mode_combo.addItem("仅键盘", "keyboard")
        self.default_mode_combo.addItem("键鼠同时", "both")
        self.default_mode_combo.setToolTip("新建录制时的默认录制模式")
        form.addRow("默认录制模式:", self.default_mode_combo)

        group.setLayout(form)
        layout.addWidget(group)
        layout.addStretch()
        return widget

    def _create_performance_tab(self):
        widget = QWidget()
        layout = QVBoxLayout(widget)

        group = QGroupBox("坐标追踪")
        form = QFormLayout()

        self.coord_update_interval = QSpinBox()
        self.coord_update_interval.setRange(10, 500)
        self.coord_update_interval.setValue(50)
        self.coord_update_interval.setSingleStep(10)
        self.coord_update_interval.setSuffix(" ms")
        self.coord_update_interval.setToolTip("鼠标坐标更新频率")
        form.addRow("更新间隔:", self.coord_update_interval)

        group.setLayout(form)
        layout.addWidget(group)
        layout.addStretch()
        return widget

    def _create_ui_tab(self):
        widget = QWidget()
        layout = QVBoxLayout(widget)

        # 界面设置
        ui_group = QGroupBox("界面设置")
        ui_form = QFormLayout()

        self.max_log_lines = QSpinBox()
        self.max_log_lines.setRange(100, 10000)
        self.max_log_lines.setValue(500)
        self.max_log_lines.setSingleStep(100)
        self.max_log_lines.setSuffix(" 行")
        ui_form.addRow("最大日志行数:", self.max_log_lines)

        self.confirm_exit_check = QCheckBox("退出时确认")
        self.confirm_exit_check.setChecked(True)
        ui_form.addRow(self.confirm_exit_check)

        self.auto_refresh_check = QCheckBox("启动时自动刷新设备")
        ui_form.addRow(self.auto_refresh_check)

        ui_group.setLayout(ui_form)
        layout.addWidget(ui_group)

        # 截图调试
        cap_group = QGroupBox("截图设置")
        cap_form = QVBoxLayout()

        self.capture_debug_check = QCheckBox("启用调试日志")
        self.capture_debug_check.setToolTip("在控制台输出详细的截图捕获日志")
        cap_form.addWidget(self.capture_debug_check)

        cap_group.setLayout(cap_form)
        layout.addWidget(cap_group)

        layout.addStretch()
        return widget

    # ── 设置读写 ──────────────────────────────────────────────

    @staticmethod
    def get_default_settings():
        """获取默认设置"""
        return {
            "performance": {
                "coord_update_interval": 50
            },
            "ui": {
                "max_log_lines": 500,
                "confirm_exit": True,
                "auto_refresh_devices": False
            },
            "capture": {
                "debug_log": False
            },
            "interception": {
                "cursor_lock_mode": False,
                "input_delay_ms": 10,
                "filter_system_keys": True
            },
            "recording": {
                "default_mode": "both"
            },
            "hotkeys": {
                "record": "F9",
                "play": "F10",
                "monitor": "F8"
            }
        }

    def load_settings(self):
        """加载设置"""
        if os.path.exists(self.settings_file):
            try:
                with open(self.settings_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception:
                pass
        return self.get_default_settings()

    def save_settings(self):
        """保存设置"""
        try:
            with open(self.settings_file, 'w', encoding='utf-8') as f:
                json.dump(self.settings, f, indent=4, ensure_ascii=False)
            return True
        except Exception as e:
            QMessageBox.critical(self, "错误", f"保存设置失败: {e}")
            return False

    def load_current_settings(self):
        """加载当前设置到 UI"""
        s = self.settings

        # interception
        icp = s.get("interception", {})
        self.cursor_lock_check.setChecked(icp.get("cursor_lock_mode", False))
        self.input_delay_spin.setValue(icp.get("input_delay_ms", 10))
        self.filter_syskeys_check.setChecked(icp.get("filter_system_keys", True))

        # hotkeys
        hk = s.get("hotkeys", {})
        self.hotkey_record_combo.setCurrentText(hk.get("record", "F9"))
        self.hotkey_play_combo.setCurrentText(hk.get("play", "F10"))
        self.hotkey_monitor_combo.setCurrentText(hk.get("monitor", "F8"))

        # recording
        rec = s.get("recording", {})
        idx = self.default_mode_combo.findData(rec.get("default_mode", "both"))
        if idx >= 0:
            self.default_mode_combo.setCurrentIndex(idx)

        # performance
        perf = s.get("performance", {})
        self.coord_update_interval.setValue(perf.get("coord_update_interval", 50))

        # ui
        ui = s.get("ui", {})
        self.max_log_lines.setValue(ui.get("max_log_lines", 500))
        self.confirm_exit_check.setChecked(ui.get("confirm_exit", True))
        self.auto_refresh_check.setChecked(ui.get("auto_refresh_devices", False))

        # capture
        cap = s.get("capture", {})
        self.capture_debug_check.setChecked(cap.get("debug_log", False))

    def get_current_settings(self):
        """从 UI 收集当前设置"""
        return {
            "performance": {
                "coord_update_interval": self.coord_update_interval.value()
            },
            "ui": {
                "max_log_lines": self.max_log_lines.value(),
                "confirm_exit": self.confirm_exit_check.isChecked(),
                "auto_refresh_devices": self.auto_refresh_check.isChecked()
            },
            "capture": {
                "debug_log": self.capture_debug_check.isChecked()
            },
            "interception": {
                "cursor_lock_mode": self.cursor_lock_check.isChecked(),
                "input_delay_ms": self.input_delay_spin.value(),
                "filter_system_keys": self.filter_syskeys_check.isChecked()
            },
            "recording": {
                "default_mode": self.default_mode_combo.currentData()
            },
            "hotkeys": {
                "record": self.hotkey_record_combo.currentText(),
                "play": self.hotkey_play_combo.currentText(),
                "monitor": self.hotkey_monitor_combo.currentText()
            }
        }

    # ── 按钮动作 ──────────────────────────────────────────────

    def apply_settings(self):
        """应用设置"""
        if not self._check_hotkey_conflict():
            QMessageBox.warning(self, "警告", "快捷键存在冲突，请修改后再应用")
            return
        self.settings = self.get_current_settings()
        self.save_settings()
        self.settings_changed.emit(self.settings)
        QMessageBox.information(self, "提示", "设置已应用")

    def accept_settings(self):
        """确定并关闭"""
        if not self._check_hotkey_conflict():
            QMessageBox.warning(self, "警告", "快捷键存在冲突，请修改后再应用")
            return
        self.settings = self.get_current_settings()
        self.save_settings()
        self.settings_changed.emit(self.settings)
        self.accept()

    def reset_defaults(self):
        """恢复默认设置"""
        reply = QMessageBox.question(
            self, "确认", "确定要恢复默认设置吗？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if reply == QMessageBox.StandardButton.Yes:
            self.settings = self.get_default_settings()
            self.load_current_settings()
            QMessageBox.information(self, "提示", "已恢复默认设置")
