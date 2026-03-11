# ClickYen - Windows 桌面自动化控制工具

<p align="center">
  <img src="https://img.shields.io/badge/python-3.8+-blue.svg" alt="Python Version">
  <img src="https://img.shields.io/badge/platform-Windows%2010%2F11-lightgrey.svg" alt="Platform">
  <img src="https://img.shields.io/badge/version-1.0.0-orange.svg" alt="Version">
</p>

---

## 📋 项目主页

- [ClickYen GitHub](https://github.com/Exmeaning/ClickYen)

---

## 📋 项目简介

ClickYen 是一款 Windows 桌面自动化辅助工具，基于 Interception 驱动实现硬件级键鼠模拟，支持操作录制回放、图像识别自动化监控、后台窗口操作等功能。适用于 UI 自动化测试、重复性办公操作、工作流自动化等场景。

由同作者的 Android 自动化项目 [ClickZen](https://github.com/Exmeaning/ClickZen) 演化而来，目标平台从 Android/ADB 转向 Windows 原生窗口。

---

## ⚠️ 重要声明

1. **AI 代码风险提示**：本项目部分代码由 AI 辅助生成，可能存在潜在的 bug 或安全问题。使用前请仔细审查代码，风险自负。
2. **作者能力有限**：本人编程水平有限，代码质量可能不高。欢迎 PR 帮忙改进。
3. **使用责任**：请合理使用本工具，遵守相关法律法规。因使用本工具产生的任何问题，作者不承担责任。

---

## ✨ 主要功能

### 🎮 双模式输入注入

| 模式 | 说明 |
|------|------|
| **Interception** | 硬件级驱动模拟，兼容性最好，适用于绝大多数应用和游戏。不可用时自动回退到 Win32 SendInput |
| **PostMessage** | 通过窗口消息注入，完全后台运行，不占用鼠标，可正常操作电脑 |

### 🎬 操作录制与回放

- 三种录制模式：鼠标 / 键盘 / 键鼠同时录制
- 鼠标支持：左键/右键/中键/侧键点击、长按、滑动轨迹、滚轮（含水平滚轮）
- 键盘支持：完整按键事件录制，自动过滤系统键
- 滑动轨迹使用 Douglas-Peucker 算法简化 + 贝塞尔曲线平滑回放
- 回放支持速度倍率调节，全局热键 F9 控制录制
- 录制文件格式：JSON

### 🤖 图像识别自动化监控

- 基于 OpenCV 模板匹配（支持 CCOEFF / CCORR / SQDIFF 三种方法）
- 三种任务模式：
  - **传统模式**：条件满足 → 执行动作序列
  - **IF 模式**：多组条件-动作对，独立判断
  - **RANDOM 模式**：条件满足后随机选择动作执行
- 条件类型：变量条件 + 图像条件（支持存在/不存在判断）
- 条件逻辑：AND / OR / NOT
- 冷却时间、检查间隔可调
- 监控方案保存/加载（模板图片 base64 编码存入 JSON）

### 📊 变量系统与网络同步

- 全局变量存储，支持 set / add / subtract / multiply / divide 等运算
- TCP Socket 变量服务器（默认端口 9527），支持多实例间变量共享
- 发布-订阅模式的变量广播，可选 Token 认证

### 🪟 窗口管理

- 选择任意窗口或整个桌面作为操作目标
- 窗口裁剪区域：指定窗口内子区域作为操作范围
- 屏幕坐标 ↔ 窗口坐标 ↔ 裁剪区域坐标三层转换
- 基于 PrintWindow API 的后台窗口截图，窗口被遮挡也能正常工作

### 🎲 防检测机制

- 坐标随机偏移（可配置百分比）
- 延迟时间随机化
- 长按时间随机化
- 滑动轨迹点微扰

### 🔒 光标锁定模式

- 操作前记录光标位置，操作完成后自动恢复，用户无感知

---

## 🚀 快速上手

### 普通用户

1. 前往 [Releases 发布页面](https://github.com/Exmeaning/ClickYen/releases) 下载最新版本
2. 双击 `ClickYen.exe` 启动程序
3. 在左侧面板选择目标窗口（或使用鼠标拾取功能）
4. 开始录制或配置自动化监控任务

### 从源码运行

```bash
git clone https://github.com/Exmeaning/ClickYen.git
cd ClickYen
pip install -r requirements.txt
python main.py
```

> 需要安装 [Interception 驱动](https://github.com/oblitum/Interception) 以使用硬件级输入模拟。未安装时程序会自动回退到 Win32 SendInput。

---

## 📖 功能指南

### 🎬 录制脚本

1. 在左侧面板选择目标窗口
2. 在中间面板选择录制模式（鼠标/键盘/键鼠同时）
3. 点击"开始录制"或按 F9
4. 在目标窗口中执行操作
5. 再次按 F9 停止录制
6. 保存录制文件（Ctrl+S）

### 🤖 自动化监控

1. 在中间面板点击"添加任务"
2. 设置监控条件（图像匹配 / 变量条件）
3. 配置触发后执行的动作（点击、滑动、等待、执行脚本、Shell 命令等）
4. 设置匹配阈值与冷却时间
5. 点击"开始监控"

---

## 🔧 技术栈

| 组件 | 技术 |
|------|------|
| GUI | PyQt6 |
| 硬件级输入 | interception-python |
| 后台输入 | Win32 PostMessage / SendMessage (pywin32) |
| 回退输入 | Win32 SendInput (ctypes) |
| 图像识别 | OpenCV + NumPy |
| 截图 | PrintWindow API / mss / Pillow |
| 钩子监控 | WH_MOUSE_LL / WH_KEYBOARD_LL (ctypes) |
| 网络通信 | TCP Socket + JSON |

---

## 📁 项目结构

```
ClickYen/
├── main.py                  # 程序入口
├── crash_handler.py         # 崩溃报告系统
├── requirements.txt         # 依赖列表
├── core/                    # 核心功能模块
│   ├── input_controller.py      # 输入控制器（录制/回放）
│   ├── interception_manager.py  # Interception 驱动管理
│   ├── postmessage_input.py     # PostMessage 后台输入
│   ├── window_manager.py        # 窗口管理与坐标转换
│   ├── window_capture.py        # 窗口截图（PrintWindow）
│   ├── screenshot_helper.py     # 多方案截图辅助
│   ├── image_matcher.py         # OpenCV 图像匹配
│   ├── auto_monitor.py          # 自动化监控引擎
│   ├── mouse_monitor.py         # 鼠标低级钩子
│   ├── keyboard_monitor.py      # 键盘低级钩子
│   ├── variable_server.py       # 变量系统与网络同步
│   ├── trajectory_utils.py      # 轨迹简化与贝塞尔曲线
│   └── eyedropper.py            # 取色器
├── gui/                     # GUI 界面
│   ├── main_window.py           # 主窗口
│   ├── left_panel.py            # 左侧面板（窗口选择/输入设置）
│   ├── center_panel.py          # 中间面板（录制/监控/随机化）
│   ├── right_panel.py           # 右侧面板（坐标/日志）
│   ├── monitor_dialog.py        # 监控任务配置对话框
│   ├── advanced_monitor_dialog.py # 高级监控功能
│   ├── crop_dialog.py           # 裁剪区域设置
│   ├── settings_dialog.py       # 设置对话框
│   ├── coordinate_picker_dialog.py # 坐标拾取工具
│   └── window_selector_dialog.py   # 窗口选择器
└── utils/                   # 工具模块
    ├── config.py                # 配置管理
    └── network_protocol.py      # 网络协议定义
```

---

## 🤝 贡献指南

欢迎贡献！

1. Fork 本项目
2. 创建功能分支 (`git checkout -b feature/AmazingFeature`)
3. 提交更改 (`git commit -m 'Add some AmazingFeature'`)
4. 推送到分支 (`git push origin feature/AmazingFeature`)
5. 提交 Pull Request

---

## 📄 开源协议

本项目采用 agplv3 协议开源

## 🙏 致谢

- [Interception](https://github.com/oblitum/Interception) - Windows 输入设备驱动
- [interception-python](https://github.com/cobrce/interception-python) - Interception Python 绑定
- [OpenCV](https://opencv.org/) - 图像识别
- [PyQt6](https://www.riverbankcomputing.com/software/pyqt/) - GUI 框架
- [ClickZen](https://github.com/Exmeaning/ClickZen) - 前身项目
- [Klick'r](https://github.com/Nain57/Smart-AutoClicker) - 自动化监控功能灵感来源

## 📞 联系方式

- GitHub Issues: [提交问题](https://github.com/Exmeaning/ClickYen/issues)
- Pull Requests: [贡献代码](https://github.com/Exmeaning/ClickYen/pulls)
- 个人邮箱：[exmeaning@foxmail.com](mailto:exmeaning@foxmail.com)

---

**免责声明**：本软件不提供任何形式的保证。作者不对使用本软件导致的任何损失负责。
