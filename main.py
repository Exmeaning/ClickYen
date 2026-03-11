
import sys
import os
import traceback
import shutil
from PyQt6.QtWidgets import (
    QApplication, QMessageBox, QDialog, QVBoxLayout,
    QLabel, QCheckBox, QDialogButtonBox, QScrollArea, QWidget
)
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QFont

# 添加项目路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from utils.config import config, VERSION
from core.interception_manager import InterceptionManager
from core.window_manager import WindowManager
from core.input_controller import InputController
from gui.main_window import MainWindow


# ==============================================================
# 免责声明对话框
# ==============================================================
class DisclaimerDialog(QDialog):
    """首次启动免责声明"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("ClickYen - 免责声明与使用须知")
        self.setMinimumSize(560, 520)
        self.setMaximumSize(700, 700)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowType.WindowContextHelpButtonHint)

        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(20, 16, 20, 16)

        # 标题
        title = QLabel(f"ClickYen v{VERSION}")
        title.setFont(QFont("", 18, QFont.Weight.Bold))
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)

        subtitle = QLabel("请在使用前仔细阅读以下内容")
        subtitle.setStyleSheet("color: #666; font-size: 12px;")
        subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(subtitle)

        # 滚动区域
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(scroll.Shape.StyledPanel)

        content_widget = QWidget()
        content_layout = QVBoxLayout(content_widget)
        content_layout.setContentsMargins(16, 12, 16, 12)

        disclaimer_text = (
            "<h3>⚠️ 免责声明</h3>"
            "<p>本软件 <b>ClickYen</b> 是一款 Windows 桌面自动化辅助工具，"
            "通过模拟键盘和鼠标输入来实现操作录制与回放。</p>"

            "<hr>"
            "<h3>🚫 禁止用途</h3>"
            "<p>本软件 <b>严禁</b> 用于以下场景：</p>"
            "<ul>"
            "<li><b>游戏作弊 / 外挂</b> — 禁止在任何网络游戏、竞技游戏中使用本软件"
            "获取不正当优势。大多数游戏的反作弊系统（如 EAC、BattlEye、Vanguard 等）"
            "能够检测到硬件级输入模拟，<b>使用本软件可能导致游戏账号被永久封禁</b>。</li>"
            "<li><b>绕过安全机制</b> — 禁止用于绕过任何软件的验证、授权、"
            "反自动化保护或安全限制。</li>"
            "<li><b>恶意自动化</b> — 禁止用于刷量、薅羊毛、批量注册、"
            "自动抢购、爬虫等违反服务条款的行为。</li>"
            "<li><b>侵犯他人权益</b> — 禁止用于未经授权操控他人计算机、"
            "窃取信息或任何侵犯他人合法权益的行为。</li>"
            "<li><b>违反法律法规</b> — 禁止用于任何违反当地法律法规的活动。</li>"
            "</ul>"

            "<hr>"
            "<h3>⚡ 风险提示</h3>"
            "<ul>"
            "<li>本软件使用 <b>Interception 驱动</b> 进行硬件级输入模拟，"
            "该驱动为内核级驱动，安装和使用需要管理员权限。</li>"
            "<li>部分反作弊软件会将 Interception 驱动标记为可疑程序，"
            "即使你没有在游戏中使用本软件，<b>仅安装驱动也可能触发检测</b>。</li>"
            "<li>使用本软件造成的任何后果（包括但不限于账号封禁、数据丢失、"
            "系统故障）均由用户自行承担。</li>"
            "</ul>"

            "<hr>"
            "<h3>✅ 推荐用途</h3>"
            "<ul>"
            "<li>桌面应用的 UI 自动化测试</li>"
            "<li>重复性办公操作的自动化（如批量数据录入）</li>"
            "<li>软件功能的自动化演示与录制</li>"
            "<li>个人效率工具与工作流自动化</li>"
            "</ul>"

            "<hr>"
            "<h3>📜 用户协议</h3>"
            "<p>继续使用本软件即表示你已阅读、理解并同意以上全部条款。"
            "开发者不对因违规使用本软件而产生的任何后果承担责任。</p>"
        )

        content_label = QLabel(disclaimer_text)
        content_label.setWordWrap(True)
        content_label.setTextFormat(Qt.TextFormat.RichText)
        content_label.setStyleSheet("font-size: 13px; line-height: 1.5;")
        content_layout.addWidget(content_label)

        scroll.setWidget(content_widget)
        layout.addWidget(scroll)

        # 滚动到底部检测
        self._scrolled_to_bottom = False
        self._scroll_bar = scroll.verticalScrollBar()
        self._scroll_bar.valueChanged.connect(self._on_scroll)

        # 10 秒倒计时
        self._countdown = 10
        self._timer_done = False

        # 勾选框（初始禁用 + 提示文字）
        self.agree_check = QCheckBox(f"请先阅读完整内容并等待 {self._countdown} 秒...")
        self.agree_check.setEnabled(False)
        self.agree_check.setStyleSheet("font-size: 13px; font-weight: bold; padding: 6px 0; color: #999;")
        self.agree_check.toggled.connect(self._on_check_toggled)
        layout.addWidget(self.agree_check)

        # 按钮
        self.button_box = QDialogButtonBox()
        self.accept_btn = self.button_box.addButton("同意并继续", QDialogButtonBox.ButtonRole.AcceptRole)
        self.reject_btn = self.button_box.addButton("不同意，退出", QDialogButtonBox.ButtonRole.RejectRole)
        self.accept_btn.setEnabled(False)
        self.accept_btn.setMinimumHeight(36)
        self.reject_btn.setMinimumHeight(36)
        self.button_box.accepted.connect(self.accept)
        self.button_box.rejected.connect(self.reject)
        layout.addWidget(self.button_box)

        # 启动倒计时
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._on_tick)
        self._timer.start(1000)

    # ── 滚动检测 ──
    def _on_scroll(self, value):
        if value >= self._scroll_bar.maximum():
            self._scrolled_to_bottom = True
            self._try_unlock_checkbox()

    # ── 倒计时 ──
    def _on_tick(self):
        self._countdown -= 1
        if self._countdown > 0:
            self.agree_check.setText(f"请先阅读完整内容并等待 {self._countdown} 秒...")
        else:
            self._timer.stop()
            self._timer_done = True
            self._try_unlock_checkbox()

    # ── 两个条件都满足才解锁勾选框 ──
    def _try_unlock_checkbox(self):
        if self._scrolled_to_bottom and self._timer_done:
            self.agree_check.setEnabled(True)
            self.agree_check.setText("我已阅读并同意以上免责声明，自愿承担使用风险")
            self.agree_check.setStyleSheet("font-size: 13px; font-weight: bold; padding: 6px 0; color: #000;")

    # ── 勾选 → 解锁按钮 ──
    def _on_check_toggled(self, checked):
        self.accept_btn.setEnabled(checked)


# ==============================================================
# 环境检测
# ==============================================================
def check_prerequisites(interception_available: bool) -> str:
    """检测运行环境，返回需要展示的提示信息（空字符串表示全部就绪）"""
    issues = []

    # 1. Interception 驱动
    if not interception_available:
        issues.append(
            "❌  <b>Interception 驱动未安装</b><br>"
            "&nbsp;&nbsp;&nbsp;&nbsp;程序将回退到 SendInput 模式，功能受限。<br>"
            "&nbsp;&nbsp;&nbsp;&nbsp;安装方法：<br>"
            "&nbsp;&nbsp;&nbsp;&nbsp;① 下载 "
            '<a href="https://github.com/oblitum/Interception">Interception</a> '
            "最新 Release<br>"
            "&nbsp;&nbsp;&nbsp;&nbsp;② 以管理员身份运行 "
            "<code>install-interception.exe /install</code><br>"
            "&nbsp;&nbsp;&nbsp;&nbsp;③ <b>重启电脑</b>（必须）"
        )

    # 2. interception-python 包
    try:
        import interception  # noqa: F401
    except ImportError:
        issues.append(
            "❌  <b>interception-python 包未安装</b><br>"
            "&nbsp;&nbsp;&nbsp;&nbsp;运行 <code>pip install interception-python</code>"
        )

    # 3. pywin32
    try:
        import win32gui  # noqa: F401
        import win32api  # noqa: F401
    except ImportError:
        issues.append(
            "❌  <b>pywin32 未安装</b><br>"
            "&nbsp;&nbsp;&nbsp;&nbsp;运行 <code>pip install pywin32</code>"
        )

    # 4. OpenCV
    try:
        import cv2  # noqa: F401
    except ImportError:
        issues.append(
            "⚠️  <b>opencv-python 未安装</b>（图像监控功能不可用）<br>"
            "&nbsp;&nbsp;&nbsp;&nbsp;运行 <code>pip install opencv-python</code>"
        )

    # 5. Pillow
    try:
        from PIL import Image  # noqa: F401
    except ImportError:
        issues.append(
            "⚠️  <b>Pillow 未安装</b>（截图功能不可用）<br>"
            "&nbsp;&nbsp;&nbsp;&nbsp;运行 <code>pip install pillow</code>"
        )

    # 6. mss
    try:
        import mss  # noqa: F401
    except ImportError:
        issues.append(
            "⚠️  <b>mss 未安装</b>（备用截图方案不可用）<br>"
            "&nbsp;&nbsp;&nbsp;&nbsp;运行 <code>pip install mss</code>"
        )

    if not issues:
        return ""

    header = (
        "<h3>🔧 运行环境检测</h3>"
        "<p>检测到以下组件缺失或未就绪：</p>"
    )
    body = "<br><br>".join(issues)
    footer = (
        "<br><br><hr>"
        "<p style='color:#666;'>你仍然可以继续启动，但缺失的功能将不可用。<br>"
        "完整依赖列表见项目根目录 <code>requirements.txt</code></p>"
    )
    return header + body + footer


# ==============================================================
# 应用主类
# ==============================================================
class ClickYenApp:
    def __init__(self):
        QApplication.setHighDpiScaleFactorRoundingPolicy(
            Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
        )
        self.app = QApplication(sys.argv)
        self.app.setStyle('Fusion')
        self.app.setApplicationName("ClickYen")
        self.app.setOrganizationName("ClickYen")

    def run(self):
        """运行应用"""
        try:
            # ── 1. 免责声明（首次启动） ──
            if not config.get("disclaimer_accepted", False):
                dlg = DisclaimerDialog()
                if dlg.exec() != QDialog.DialogCode.Accepted:
                    return 0  # 用户拒绝，正常退出
                config.set("disclaimer_accepted", True)

            # ── 2. 初始化 Interception ──
            interception_mgr = InterceptionManager()
            status = interception_mgr.get_status()

            # ── 3. 环境检测 ──
            env_msg = check_prerequisites(status['available'])
            if env_msg:
                msg_box = QMessageBox()
                msg_box.setWindowTitle("ClickYen - 环境检测")
                msg_box.setIcon(QMessageBox.Icon.Information)
                msg_box.setTextFormat(Qt.TextFormat.RichText)
                msg_box.setText(env_msg)
                msg_box.setStandardButtons(
                    QMessageBox.StandardButton.Ok | QMessageBox.StandardButton.Cancel
                )
                msg_box.button(QMessageBox.StandardButton.Ok).setText("继续启动")
                msg_box.button(QMessageBox.StandardButton.Cancel).setText("退出")
                if msg_box.exec() == QMessageBox.StandardButton.Cancel:
                    return 0

            # ── 4. 初始化核心组件 ──
            window_mgr = WindowManager()
            controller = InputController(interception_mgr, window_mgr)

            controller.set_cursor_lock_mode(config.get("cursor_lock_mode", False))
            interception_mgr.set_input_delay(config.get("input_delay_ms", 10))
            controller.set_input_mode(config.get("input_mode", "interception"))

            # ── 5. 启动主窗口 ──
            window = MainWindow(config, interception_mgr, window_mgr, controller)
            window.show()

            return self.app.exec()

        except Exception as e:
            QMessageBox.critical(None, "错误", f"程序启动失败:\n{str(e)}")
            return 1


# ==============================================================
# 全局异常钩子
# ==============================================================
def exception_hook(exctype, value, tb):
    """全局异常处理"""
    import datetime
    from pathlib import Path

    error_msg = ''.join(traceback.format_exception(exctype, value, tb))
    print(f"未捕获的异常:\n{error_msg}")

    try:
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        error_dir = Path.home() / ".clickyen" / "crash_reports"
        error_dir.mkdir(parents=True, exist_ok=True)

        error_file = error_dir / f"crash_{timestamp}.txt"

        with open(error_file, 'w', encoding='utf-8') as f:
            f.write(f"=== ClickYen Crash Report ===\n")
            f.write(f"Time: {datetime.datetime.now()}\n")
            f.write(f"Version: {VERSION}\n")
            f.write(f"Python: {sys.version}\n")
            f.write(f"OS: {os.name} {sys.platform}\n")
            f.write(f"\n=== Error Details ===\n")
            f.write(error_msg)
            f.write(f"\n=== System Info ===\n")
            f.write(f"Working Directory: {os.getcwd()}\n")
            f.write(f"Executable: {sys.executable}\n")

        try:
            QMessageBox.critical(None, "程序错误",
                                f"发生了一个错误:\n{exctype.__name__}: {value}\n\n"
                                f"错误报告已保存到:\n{error_file}\n\n"
                                "请查看错误报告获取详细信息")
        except:
            print(f"错误报告已保存到: {error_file}")

    except Exception as e:
        print(f"无法生成错误报告: {e}")


sys.excepthook = exception_hook


def main():
    """主函数"""
    app = ClickYenApp()
    sys.exit(app.run())


if __name__ == "__main__":
    main()
