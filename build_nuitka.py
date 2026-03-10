#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Nuitka打包脚本 - ClickYen（多核优化版）
"""
import datetime
import os
import sys
import shutil
import subprocess
from pathlib import Path

# 项目信息
PROJECT_NAME = "ClickYen"
VERSION = "1.0.0"
MAIN_SCRIPT = "main.py"
ICON_FILE = "resources/icon.ico"


def clean_build():
    """清理之前的构建"""
    dirs_to_remove = [
        "build", "dist",
        f"{PROJECT_NAME}.build",
        f"{PROJECT_NAME}.dist",
    ]
    for dir_name in dirs_to_remove:
        path = Path(dir_name)
        if path.exists():
            shutil.rmtree(path)
            print(f"已清理: {dir_name}")


def build_with_nuitka():
    """使用 Nuitka 构建"""
    cpu_cores = os.cpu_count() or 4
    print(f"检测到 CPU 核心数: {cpu_cores}，将启用并行编译。")

    nuitka_args = [
        sys.executable, "-m", "nuitka",
        "--standalone",
        "--onefile",
        f"--output-filename={PROJECT_NAME}.exe",
        "--windows-console-mode=force",
        "--assume-yes-for-downloads",
        f"--jobs={cpu_cores}",
        "--prefer-source-code",
        "--no-deployment-flag=self-execution",

        # 包含模块
        "--include-qt-plugins=all",
        "--include-qt-plugins=platforms",
        "--include-qt-plugins=styles",
        "--include-qt-plugins=iconengines",
        "--include-package=PyQt6",
        "--include-package=PIL",
        "--include-package=cv2",
        "--include-package-data=cv2",
        "--include-package=numpy",
        "--include-package=win32gui",
        "--include-package=win32api",
        "--include-package=win32con",
        "--include-package=win32ui",
        "--include-package=win32timezone",
        "--include-package=mss",

        # 插件
        "--enable-plugin=pyqt6",
        "--enable-plugin=numpy",

        # 错误日志
        "--force-stderr-spec={TEMP}\\clickyen_error_%TIME%.log".replace(
            "%TIME%", datetime.datetime.now().strftime("%H%M%S")
        ),

        MAIN_SCRIPT
    ]

    # 可选图标
    if Path(ICON_FILE).exists():
        nuitka_args.insert(3, f"--windows-icon-from-ico={ICON_FILE}")

    # 可选资源目录
    if Path("resources").exists() and any(Path("resources").iterdir()):
        nuitka_args.insert(5, "--include-data-dir=resources=resources")

    print("\n开始构建Nuitka项目...")
    print("命令：", " ".join(nuitka_args), "\n")

    result = subprocess.run(nuitka_args)

    if result.returncode == 0:
        print(f"\n✅ 构建成功！输出文件：{PROJECT_NAME}.exe")
    else:
        print("\n❌ 构建失败！")
        sys.exit(1)


def main():
    """主函数"""
    print(f"=== {PROJECT_NAME} Nuitka 构建脚本 ===\n")

    try:
        subprocess.run([sys.executable, "-m", "nuitka", "--version"],
                       capture_output=True, check=True)
    except:
        print("❌ 错误: Nuitka 未安装！请运行: pip install nuitka")
        sys.exit(1)

    clean_build()
    build_with_nuitka()

    print(f"\n=== 构建完成 ===")
    print(f"可执行文件: {PROJECT_NAME}.exe")
    print(f"崩溃报告将保存至: %USERPROFILE%\\.clickyen\\crash_reports\\")


if __name__ == "__main__":
    main()
