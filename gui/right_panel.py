"""右侧面板 - 坐标显示和操作日志"""
from PyQt6.QtWidgets import *
from PyQt6.QtCore import *
from PyQt6.QtGui import *
import subprocess
import threading


class RightPanel(QWidget):
    """右侧面板：坐标显示、操作日志"""
    
    # 信号定义
    copy_coords_clicked = pyqtSignal()
    shell_output_signal = pyqtSignal(str, str)  # message, level
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.parent = parent
        self.shell_history = []
        self.shell_history_index = -1
        self.shell_output_signal.connect(self.log)
        self.init_ui()
        
    def init_ui(self):
        """初始化UI"""
        layout = QVBoxLayout(self)
        layout.setSpacing(15)
        
        # 1. 坐标显示区域
        coord_widget = self.create_coord_widget()
        layout.addWidget(coord_widget)
        
        # 2. 日志区域（占主要空间）
        log_widget = self.create_log_widget()
        layout.addWidget(log_widget, 1)
        
        # 设置样式
        self.setStyleSheet("""
            QGroupBox {
                font-size: 13px;
                font-weight: bold;
                border: 2px solid #e0e0e0;
                border-radius: 8px;
                margin-top: 10px;
                padding-top: 10px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 10px 0 10px;
            }
        """)
        
    def create_coord_widget(self):
        """创建坐标显示区域"""
        group = QGroupBox("📍 当前坐标")
        layout = QVBoxLayout()
        layout.setSpacing(10)
        
        # 屏幕坐标
        self.screen_coord_label = QLabel("屏幕: (0, 0)")
        self.screen_coord_label.setStyleSheet("""
            QLabel {
                font-family: 'Consolas', 'Monaco', monospace;
                font-size: 18px;
                color: #333;
                padding: 5px;
            }
        """)
        
        # 窗口坐标（保留 device_coord_label 名称，含义变为窗口坐标）
        self.device_coord_label = QLabel("窗口: (0, 0)")
        self.device_coord_label.setStyleSheet("""
            QLabel {
                font-family: 'Consolas', 'Monaco', monospace;
                font-size: 20px;
                font-weight: bold;
                color: #424242;
                padding: 5px;
            }
        """)
        
        # 窗口状态
        self.window_status_label = QLabel("目标窗口: 未检测")
        self.window_status_label.setStyleSheet("""
            QLabel {
                font-size: 14px;
                color: #666;
                padding: 5px;
            }
        """)
        
        # 复制坐标按钮
        self.copy_btn = QPushButton("📋 复制窗口坐标")
        self.copy_btn.setMinimumHeight(40)
        self.copy_btn.clicked.connect(self.copy_coords_clicked.emit)
        
        layout.addWidget(self.screen_coord_label)
        layout.addWidget(self.device_coord_label)
        layout.addWidget(self.window_status_label)
        layout.addWidget(self.copy_btn)
        
        group.setLayout(layout)
        return group
        
    def create_log_widget(self):
        """创建日志显示区域"""
        group = QGroupBox("📝 操作日志")
        layout = QVBoxLayout()
        
        # 日志文本框
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setStyleSheet("""
            QTextEdit {
                font-family: 'Consolas', 'Monaco', monospace;
                font-size: 12px;
                background-color: #1e1e1e;
                color: #d4d4d4;
                border: 1px solid #3c3c3c;
                border-radius: 6px;
                padding: 10px;
            }
        """)
        
        # 设置高亮样式
        self.setup_log_highlighting()
        
        # 清空按钮
        clear_btn_layout = QHBoxLayout()
        clear_btn_layout.addStretch()
        
        self.clear_log_btn = QPushButton("🗑 清空日志")
        self.clear_log_btn.setMinimumHeight(35)
        clear_btn_layout.addWidget(self.clear_log_btn)
        
        layout.addWidget(self.log_text)
        layout.addLayout(clear_btn_layout)
        
        # Shell 命令快捷输入框
        shell_layout = QHBoxLayout()
        shell_label = QLabel("PS>")
        shell_label.setStyleSheet("color: #4ec9b0; font-family: Consolas; font-weight: bold;")
        self.shell_input = QLineEdit()
        self.shell_input.setPlaceholderText("输入 PowerShell 命令后按 Enter 执行...")
        self.shell_input.setStyleSheet("""
            QLineEdit {
                font-family: 'Consolas', 'Monaco', monospace;
                font-size: 12px;
                background-color: #1e1e1e;
                color: #d4d4d4;
                border: 1px solid #3c3c3c;
                border-radius: 4px;
                padding: 4px 8px;
            }
        """)
        self.shell_input.returnPressed.connect(self.execute_shell_command)
        self.shell_input.installEventFilter(self)
        
        self.shell_run_btn = QPushButton("▶")
        self.shell_run_btn.setFixedWidth(32)
        self.shell_run_btn.setMinimumHeight(28)
        self.shell_run_btn.setToolTip("执行命令")
        self.shell_run_btn.clicked.connect(self.execute_shell_command)
        
        shell_layout.addWidget(shell_label)
        shell_layout.addWidget(self.shell_input, 1)
        shell_layout.addWidget(self.shell_run_btn)
        
        layout.addLayout(shell_layout)
        
        group.setLayout(layout)
        return group
    
    def eventFilter(self, obj, event):
        """处理 Shell 输入框的上下键历史记录"""
        if obj == self.shell_input and event.type() == QEvent.Type.KeyPress:
            if event.key() == Qt.Key.Key_Up:
                if self.shell_history and self.shell_history_index < len(self.shell_history) - 1:
                    self.shell_history_index += 1
                    self.shell_input.setText(self.shell_history[self.shell_history_index])
                return True
            elif event.key() == Qt.Key.Key_Down:
                if self.shell_history_index > 0:
                    self.shell_history_index -= 1
                    self.shell_input.setText(self.shell_history[self.shell_history_index])
                elif self.shell_history_index == 0:
                    self.shell_history_index = -1
                    self.shell_input.clear()
                return True
        return super().eventFilter(obj, event)
    
    def execute_shell_command(self):
        """执行 PowerShell 命令"""
        command = self.shell_input.text().strip()
        if not command:
            return
        
        # 记录历史
        self.shell_history.insert(0, command)
        if len(self.shell_history) > 50:
            self.shell_history = self.shell_history[:50]
        self.shell_history_index = -1
        
        self.shell_input.clear()
        self.log(f"PS> {command}", "info")
        
        # 在后台线程执行，避免阻塞 UI
        def run():
            try:
                # 使用 PowerShell 执行，通过 UTF-8 BOM 强制输出编码
                ps_command = f'[Console]::OutputEncoding = [System.Text.Encoding]::UTF8; {command}'
                result = subprocess.run(
                    ['powershell', '-NoProfile', '-Command', ps_command],
                    capture_output=True, timeout=30,
                    encoding='utf-8', errors='replace'
                )
                if result.stdout.strip():
                    for line in result.stdout.strip().split('\n'):
                        self.shell_output_signal.emit(line.rstrip('\r'), "success")
                if result.stderr.strip():
                    for line in result.stderr.strip().split('\n'):
                        self.shell_output_signal.emit(line.rstrip('\r'), "warning")
                if result.returncode != 0:
                    self.shell_output_signal.emit(f"退出码: {result.returncode}", "error")
            except subprocess.TimeoutExpired:
                self.shell_output_signal.emit("命令执行超时 (30秒)", "error")
            except Exception as e:
                self.shell_output_signal.emit(f"执行失败: {e}", "error")
        
        threading.Thread(target=run, daemon=True).start()
        
    def setup_log_highlighting(self):
        """设置日志高亮"""
        pass
        
    def log(self, message, level="info"):
        """添加日志"""
        from datetime import datetime
        timestamp = datetime.now().strftime("%H:%M:%S")
        
        # 根据级别设置颜色
        color_map = {
            "info": "#d4d4d4",
            "success": "#4ec9b0",
            "warning": "#ce9178",
            "error": "#f48771"
        }
        
        color = color_map.get(level, "#d4d4d4")
        
        # 添加HTML格式的日志
        html = f'<span style="color: #808080">[{timestamp}]</span> '
        html += f'<span style="color: {color}">{message}</span>'
        
        cursor = self.log_text.textCursor()
        cursor.movePosition(cursor.MoveOperation.End)
        self.log_text.setTextCursor(cursor)
        self.log_text.insertHtml(html + "<br>")
        self.log_text.ensureCursorVisible()
