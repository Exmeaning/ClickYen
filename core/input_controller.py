"""
InputController - 核心输入控制器
从 DeviceController 重构而来，将所有 ADB 依赖替换为 InterceptionManager + WindowManager。
提供录制、回放、截图、坐标转换等功能。
"""

import time
import math
import random
import json
from datetime import datetime
from PyQt6.QtCore import QObject, pyqtSignal


class InputController(QObject):
    """基于 Interception + WindowManager 的输入控制器

    支持两种输入模式：
    - "interception": 硬件级注入（Interception/SendInput），会移动系统光标
    - "postmessage":  后台消息注入（PostMessage），完全不影响用户鼠标
    """

    # 信号
    action_recorded = pyqtSignal(dict)

    def __init__(self, interception_mgr, window_mgr):
        super().__init__()
        self.interception = interception_mgr  # InterceptionManager 实例
        self.window_mgr = window_mgr          # WindowManager 实例
        self.monitor = None                    # MouseMonitor（延迟初始化）
        self.keyboard_monitor = None           # KeyboardMonitor（延迟初始化）
        self.recording = False
        self.recorded_actions = []
        self.recording_mode = 'both'  # 'mouse', 'keyboard', 'both'

        # 输入模式
        self._input_mode = "interception"  # "interception" | "postmessage"
        self._postmsg_input = None         # PostMessageInput（延迟初始化）

        # 随机化设置
        self.enable_randomization = False
        self.position_random_range = 0.01      # 1% 坐标随机偏移
        self.delay_random_range = 0.001        # 延迟随机
        self.long_press_random_range = 0.01    # 长按时间随机
        self.playing = False
        self.stop_playing_flag = False

    # ==========================================================
    # 输入模式管理
    # ==========================================================

    def set_input_mode(self, mode):
        """切换输入模式

        Args:
            mode: "interception" — 硬件级注入（会移动光标）
                  "postmessage" — 后台消息注入（不影响光标）
        """
        if mode not in ("interception", "postmessage"):
            print(f"[InputController] 未知输入模式: {mode}，忽略")
            return
        self._input_mode = mode
        if mode == "postmessage":
            self._ensure_postmsg()
        print(f"[InputController] 输入模式切换为: {mode}")

    def get_input_mode(self):
        """获取当前输入模式"""
        return self._input_mode

    def _ensure_postmsg(self):
        """确保 PostMessageInput 已初始化"""
        if self._postmsg_input is None:
            from core.postmessage_input import PostMessageInput
            self._postmsg_input = PostMessageInput()
            # 同步延迟设置
            self._postmsg_input.set_input_delay(
                self.interception._input_delay_ms
            )
        # 同步目标窗口
        hwnd, _ = self.window_mgr.get_target()
        if hwnd:
            self._postmsg_input.set_target_hwnd(hwnd)

    def _sync_postmsg_target(self):
        """同步 PostMessage 的目标窗口"""
        if self._postmsg_input:
            hwnd, _ = self.window_mgr.get_target()
            if hwnd:
                self._postmsg_input.set_target_hwnd(hwnd)

    @property
    def _use_postmsg(self):
        """是否使用 PostMessage 模式"""
        return self._input_mode == "postmessage"

    # ==========================================================
    # 录制模式
    # ==========================================================

    def set_recording_mode(self, mode):
        """设置录制模式: 'mouse', 'keyboard', 'both'"""
        if mode in ('mouse', 'keyboard', 'both'):
            self.recording_mode = mode
            print(f"[InputController] 录制模式设置为: {mode}")
            return True
        return False

    # ==========================================================
    # 转发 / 代理方法
    # ==========================================================

    def set_cursor_lock_mode(self, enabled):
        """转发到 InterceptionManager"""
        self.interception.set_cursor_lock_mode(enabled)

    def get_target_size(self):
        """转发到 WindowManager"""
        return self.window_mgr.get_target_size()

    def press_key(self, scan_code):
        """按键（按下 + 释放）"""
        if self._use_postmsg:
            self._ensure_postmsg()
            self._sync_postmsg_target()
            self._postmsg_input.key_press(scan_code)
        else:
            self.interception.key_press(scan_code)

    # ==========================================================
    # 随机化工具
    # ==========================================================

    def add_random_offset(self, value, range_percent):
        """添加随机偏移"""
        if self.enable_randomization:
            offset = value * random.uniform(-range_percent, range_percent)
            return int(value + offset)
        return value

    def add_random_delay(self, delay):
        """添加随机延迟"""
        if self.enable_randomization:
            random_factor = random.uniform(
                1 - self.delay_random_range,
                1 + self.delay_random_range,
            )
            return delay * random_factor
        return delay

    def set_randomization(self, enabled, position_range=0.01,
                          delay_range=0.2, long_press_range=0.15):
        """设置随机化参数"""
        self.enable_randomization = enabled
        self.position_random_range = position_range
        self.delay_random_range = delay_range
        self.long_press_random_range = long_press_range
        print(
            f"[InputController] 随机化设置: 启用={enabled}, "
            f"位置={position_range * 100}%, 延迟={delay_range * 100}%, "
            f"长按={long_press_range * 100}%"
        )

    # ==========================================================
    # 基本输入操作
    # ==========================================================

    def click(self, x, y, use_random=True):
        """点击指定窗口坐标"""
        if use_random and self.enable_randomization:
            x = self.add_random_offset(x, self.position_random_range)
            y = self.add_random_offset(y, self.position_random_range)

        if self._use_postmsg:
            self._ensure_postmsg()
            self._sync_postmsg_target()
            # PostMessage 使用窗口客户区坐标（考虑裁剪偏移）
            abs_x, abs_y = self.window_mgr.get_postmessage_coords(x, y)
            self._postmsg_input.mouse_click(abs_x, abs_y)
        else:
            screen_x, screen_y = self.window_mgr.window_to_screen(x, y)
            if self.interception._cursor_lock_mode:
                self.interception.click_with_restore(screen_x, screen_y)
            else:
                self.interception.mouse_click(screen_x, screen_y)

        if self.recording:
            self.recorded_actions.append({
                'type': 'click',
                'x': x, 'y': y,
                'time': time.time(),
            })

    def long_click(self, x, y, duration=1000, use_random=True):
        """长按"""
        if use_random and self.enable_randomization:
            x = self.add_random_offset(x, self.position_random_range)
            y = self.add_random_offset(y, self.position_random_range)
            duration = self.add_random_offset(duration, self.long_press_random_range)

        if self._use_postmsg:
            self._ensure_postmsg()
            self._sync_postmsg_target()
            abs_x, abs_y = self.window_mgr.get_postmessage_coords(x, y)
            self._postmsg_input.mouse_move_to(abs_x, abs_y)
            time.sleep(0.01)
            self._postmsg_input.mouse_down(abs_x, abs_y)
            time.sleep(duration / 1000.0)
            self._postmsg_input.mouse_up(abs_x, abs_y)
        else:
            screen_x, screen_y = self.window_mgr.window_to_screen(x, y)
            cursor_lock = self.interception._cursor_lock_mode
            original_pos = self.interception._get_cursor_pos() if cursor_lock else None

            self.interception.mouse_move_to(screen_x, screen_y)
            time.sleep(0.01)
            self.interception.mouse_down()
            time.sleep(duration / 1000.0)
            self.interception.mouse_up()

            if cursor_lock and original_pos:
                time.sleep(0.005)
                self.interception.mouse_move_to(*original_pos)

        if self.recording:
            self.recorded_actions.append({
                'type': 'long_click',
                'x': x, 'y': y,
                'duration': duration,
                'time': time.time(),
            })

    def swipe(self, x1, y1, x2, y2, duration=300, use_random=True):
        """滑动"""
        if use_random and self.enable_randomization:
            x1 = self.add_random_offset(x1, self.position_random_range)
            y1 = self.add_random_offset(y1, self.position_random_range)
            x2 = self.add_random_offset(x2, self.position_random_range)
            y2 = self.add_random_offset(y2, self.position_random_range)
            duration = self.add_random_offset(duration, 0.1)

        if self._use_postmsg:
            self._ensure_postmsg()
            self._sync_postmsg_target()
            ax1, ay1 = self.window_mgr.get_postmessage_coords(x1, y1)
            ax2, ay2 = self.window_mgr.get_postmessage_coords(x2, y2)
            self._postmsg_input.perform_swipe(ax1, ay1, ax2, ay2, duration)
        else:
            sx1, sy1 = self.window_mgr.window_to_screen(x1, y1)
            sx2, sy2 = self.window_mgr.window_to_screen(x2, y2)

            cursor_lock = self.interception._cursor_lock_mode
            if cursor_lock:
                self.interception.swipe_with_restore(sx1, sy1, sx2, sy2, duration)
            else:
                self.interception._perform_swipe(sx1, sy1, sx2, sy2, duration)

        if self.recording:
            self.recorded_actions.append({
                'type': 'swipe',
                'x1': x1, 'y1': y1,
                'x2': x2, 'y2': y2,
                'duration': duration,
                'time': time.time(),
            })

    def input_text(self, text):
        """输入文本"""
        if self._use_postmsg:
            self._ensure_postmsg()
            self._sync_postmsg_target()
            self._postmsg_input.type_text(text)
        else:
            self.interception.type_text(text)

        if self.recording:
            self.recorded_actions.append({
                'type': 'text',
                'text': text,
                'time': time.time(),
            })

    def screenshot(self):
        """截取目标窗口"""
        try:
            return self.window_mgr.capture_target()
        except Exception as e:
            print(f"[InputController] 截图失败: {e}")
            return None

    # ==========================================================
    # 播放控制
    # ==========================================================

    def stop_playing(self):
        """停止播放"""
        if self.playing:
            self.stop_playing_flag = True
            return True
        return False

    def play_recording(self, actions, speed=1.0, use_random=True):
        """播放录制 - 基于动作开始时间的精确控制"""
        if not actions or self.playing:
            return False

        self.playing = True
        self.stop_playing_flag = False

        try:
            print(f"[InputController] 开始播放 {len(actions)} 个操作")
            print(f"  播放速度: {speed}x")
            print(f"  随机化: {'开启' if use_random and self.enable_randomization else '关闭'}")

            # 获取第一个动作的开始时间作为基准
            base_time_ms = actions[0].get('start_time_ms', 0)

            # 记录播放开始的实际时间
            play_start_time = time.perf_counter()

            for i, action in enumerate(actions):
                if self.stop_playing_flag:
                    print("[InputController] 播放已中断")
                    break

                # 获取动作的开始时间（相对于第一个动作）
                action_start_ms = action.get('start_time_ms', 0)
                relative_start_ms = action_start_ms - base_time_ms

                # 计算应该执行的时间点
                target_time = relative_start_ms / 1000.0 / speed

                # 计算实际需要等待的时间
                elapsed_time = time.perf_counter() - play_start_time
                wait_time = target_time - elapsed_time

                # 执行等待
                if wait_time > 0.01:
                    print(f"  等待 {wait_time:.3f} 秒")
                    time.sleep(wait_time)
                elif wait_time < -0.5 and i > 0:
                    print(f"  ⚠️ 延迟 {-wait_time:.3f} 秒")

                # 执行动作
                self._execute_action(action, i, len(actions), use_random, speed)

            return not self.stop_playing_flag

        finally:
            self.playing = False
            self.stop_playing_flag = False
            print("[InputController] 播放完成")

    # ==========================================================
    # 动作执行
    # ==========================================================

    # 录制按钮名 → interception 库按钮名映射
    _BUTTON_MAP_INTERCEPTION = {
        "left": "left", "right": "right", "middle": "middle",
        "x1": "mouse4", "x2": "mouse5",
    }

    def _execute_action(self, action, index, total, use_random, speed):
        """执行单个动作"""
        print(f"  执行操作 {index + 1}/{total}: {action['type']}")

        try:
            action_type = action['type']
            use_postmsg = self._use_postmsg

            if use_postmsg:
                self._ensure_postmsg()
                self._sync_postmsg_target()

            if action_type == 'click':
                x, y = action['x'], action['y']
                button = action.get('button', 'left')
                if use_random and self.enable_randomization:
                    x = self.add_random_offset(x, self.position_random_range)
                    y = self.add_random_offset(y, self.position_random_range)
                print(f"    点击: ({x}, {y}) button={button}")
                if use_postmsg:
                    abs_x, abs_y = self.window_mgr.get_postmessage_coords(x, y)
                    self._postmsg_input.mouse_click(abs_x, abs_y, button=button)
                else:
                    icp_btn = self._BUTTON_MAP_INTERCEPTION.get(button, button)
                    screen_x, screen_y = self.window_mgr.window_to_screen(x, y)
                    cursor_lock = self.interception._cursor_lock_mode
                    if cursor_lock:
                        self.interception.click_with_restore(screen_x, screen_y, button=icp_btn)
                    else:
                        self.interception.mouse_click(screen_x, screen_y, button=icp_btn)

            elif action_type == 'long_click':
                x, y = action['x'], action['y']
                duration = action.get('duration', 1000)
                if use_random and self.enable_randomization:
                    x = self.add_random_offset(x, self.position_random_range)
                    y = self.add_random_offset(y, self.position_random_range)
                    duration = int(duration * random.uniform(0.85, 1.15))
                actual_duration = max(50, int(duration / speed))
                print(f"    长按: ({x}, {y}) 持续 {actual_duration}ms")
                if use_postmsg:
                    abs_x, abs_y = self.window_mgr.get_postmessage_coords(x, y)
                    self._postmsg_input.mouse_move_to(abs_x, abs_y)
                    time.sleep(0.01)
                    self._postmsg_input.mouse_down(abs_x, abs_y)
                    time.sleep(actual_duration / 1000.0)
                    self._postmsg_input.mouse_up(abs_x, abs_y)
                else:
                    screen_x, screen_y = self.window_mgr.window_to_screen(x, y)
                    cursor_lock = self.interception._cursor_lock_mode
                    original_pos = self.interception._get_cursor_pos() if cursor_lock else None
                    self.interception.mouse_move_to(screen_x, screen_y)
                    time.sleep(0.01)
                    self.interception.mouse_down()
                    time.sleep(actual_duration / 1000.0)
                    self.interception.mouse_up()
                    if cursor_lock and original_pos:
                        time.sleep(0.005)
                        self.interception.mouse_move_to(*original_pos)

            elif action_type == 'swipe':
                x1, y1 = action['x1'], action['y1']
                x2, y2 = action['x2'], action['y2']
                duration = action.get('duration', 300)
                trajectory = action.get('trajectory', None)

                if use_random and self.enable_randomization:
                    x1 = self.add_random_offset(x1, self.position_random_range)
                    y1 = self.add_random_offset(y1, self.position_random_range)
                    x2 = self.add_random_offset(x2, self.position_random_range)
                    y2 = self.add_random_offset(y2, self.position_random_range)
                    duration = int(duration * random.uniform(0.9, 1.1))

                actual_duration = max(50, int(duration / speed))

                if trajectory and len(trajectory) > 2:
                    print(f"    滑动（带轨迹）: {len(trajectory)}个轨迹点, 持续 {actual_duration}ms")
                    self._play_swipe_with_trajectory(trajectory, actual_duration, use_random)
                else:
                    print(f"    滑动（直线）: ({x1}, {y1}) -> ({x2}, {y2}) 持续 {actual_duration}ms")
                    if use_postmsg:
                        ax1, ay1 = self.window_mgr.get_postmessage_coords(x1, y1)
                        ax2, ay2 = self.window_mgr.get_postmessage_coords(x2, y2)
                        self._postmsg_input.perform_swipe(
                            ax1, ay1, ax2, ay2, actual_duration
                        )
                    else:
                        sx1, sy1 = self.window_mgr.window_to_screen(x1, y1)
                        sx2, sy2 = self.window_mgr.window_to_screen(x2, y2)
                        cursor_lock = self.interception._cursor_lock_mode
                        if cursor_lock:
                            self.interception.swipe_with_restore(
                                sx1, sy1, sx2, sy2, actual_duration
                            )
                        else:
                            self.interception._perform_swipe(
                                sx1, sy1, sx2, sy2, actual_duration
                            )

            elif action_type == 'key_press':
                print(f"    按键: scan_code=0x{action['scan_code']:04X}")
                if use_postmsg:
                    self._postmsg_input.key_press(action['scan_code'])
                else:
                    self.interception.key_press(action['scan_code'])

            elif action_type == 'key_down':
                print(f"    键按下: {action.get('key_name', '')} scan_code=0x{action['scan_code']:04X}")
                if use_postmsg:
                    self._postmsg_input.key_down(action['scan_code'])
                else:
                    self.interception.key_down(action['scan_code'])

            elif action_type == 'key_up':
                print(f"    键释放: {action.get('key_name', '')} scan_code=0x{action['scan_code']:04X}")
                if use_postmsg:
                    self._postmsg_input.key_up(action['scan_code'])
                else:
                    self.interception.key_up(action['scan_code'])

            elif action_type == 'text':
                print(f"    输入文本: {action['text']}")
                if use_postmsg:
                    self._postmsg_input.type_text(action['text'])
                else:
                    self.interception.type_text(action['text'])

            elif action_type == 'scroll':
                x, y = action.get('x', 0), action.get('y', 0)
                delta = action.get('delta', 120)
                horizontal = action.get('horizontal', False)
                print(f"    滚轮: ({x}, {y}) delta={delta} horizontal={horizontal}")
                if not horizontal:
                    # 垂直滚轮
                    screen_x, screen_y = self.window_mgr.window_to_screen(x, y)
                    if not use_postmsg:
                        # 先移动到目标位置再滚动
                        cursor_lock = self.interception._cursor_lock_mode
                        original_pos = self.interception._get_cursor_pos() if cursor_lock else None
                        self.interception.mouse_move_to(screen_x, screen_y)
                        time.sleep(0.005)
                        self.interception.mouse_scroll(delta)
                        if cursor_lock and original_pos:
                            time.sleep(0.005)
                            self.interception.mouse_move_to(*original_pos)
                    else:
                        abs_x, abs_y = self.window_mgr.get_postmessage_coords(x, y)
                        self._postmsg_input.mouse_scroll(abs_x, abs_y, delta)

            elif action_type == 'wait':
                wait_ms = action.get('duration', 0)
                print(f"    等待: {wait_ms}ms")
                time.sleep(wait_ms / 1000.0)

            elif action_type == 'key':
                # 兼容旧格式的 Android keyevent（忽略或映射）
                print(f"    旧格式按键: {action.get('key_name', action.get('keycode', ''))}")

        except Exception as e:
            print(f"    ❌ 执行失败: {e}")

    # ==========================================================
    # 轨迹滑动（Interception 逐点移动）
    # ==========================================================

    def _play_swipe_with_trajectory(self, trajectory, duration_ms, use_random):
        """使用轨迹数据播放滑动

        Args:
            trajectory: [(x, y, time_ms), ...] 轨迹点列表
            duration_ms: 播放持续时间（毫秒）
            use_random: 是否添加随机偏移
        """
        if len(trajectory) < 2:
            return

        use_postmsg = self._use_postmsg

        if use_postmsg:
            self._ensure_postmsg()
            self._sync_postmsg_target()
            # 转换为窗口客户区绝对坐标
            abs_points = []
            for point in trajectory:
                x, y = point[0], point[1]
                if use_random and self.enable_randomization:
                    x = self.add_random_offset(x, self.position_random_range * 0.3)
                    y = self.add_random_offset(y, self.position_random_range * 0.3)
                ax, ay = self.window_mgr.get_postmessage_coords(x, y)
                abs_points.append((ax, ay))

            # 计算时间间隔
            interval = duration_ms / (len(abs_points) - 1) / 1000.0

            # 移动到起点并按下
            self._postmsg_input.mouse_move_to(*abs_points[0])
            time.sleep(0.005)
            self._postmsg_input.mouse_down(abs_points[0][0], abs_points[0][1])

            # 逐点移动
            for i in range(1, len(abs_points)):
                time.sleep(interval)
                self._postmsg_input.mouse_move_to(*abs_points[i])

            # 释放
            time.sleep(0.005)
            self._postmsg_input.mouse_up(abs_points[-1][0], abs_points[-1][1])
        else:
            # 原有 Interception 逻辑
            # 转换所有轨迹点为屏幕坐标
            screen_points = []
            for point in trajectory:
                x, y = point[0], point[1]
                if use_random and self.enable_randomization:
                    x = self.add_random_offset(x, self.position_random_range * 0.3)
                    y = self.add_random_offset(y, self.position_random_range * 0.3)
                sx, sy = self.window_mgr.window_to_screen(x, y)
                screen_points.append((sx, sy))

            cursor_lock = self.interception._cursor_lock_mode
            original_pos = self.interception._get_cursor_pos() if cursor_lock else None

            # 移动到起点并按下
            self.interception.mouse_move_to(*screen_points[0])
            time.sleep(0.005)
            self.interception.mouse_down()

            # 计算时间间隔
            interval = duration_ms / (len(screen_points) - 1) / 1000.0

            # 逐点移动
            for i in range(1, len(screen_points)):
                time.sleep(interval)
                self.interception.mouse_move_to(*screen_points[i])

            # 释放
            time.sleep(0.005)
            self.interception.mouse_up()

            # 恢复光标
            if cursor_lock and original_pos:
                time.sleep(0.005)
                self.interception.mouse_move_to(*original_pos)

    def _play_bezier_swipe(self, trajectory, duration_ms, use_random):
        """使用贝塞尔曲线播放复杂轨迹"""

        # 提取关键控制点（简化轨迹）
        if len(trajectory) > 6:
            indices = [0, len(trajectory) // 4, len(trajectory) // 2,
                       3 * len(trajectory) // 4, -1]
            control_points = [trajectory[i] for i in indices]
        else:
            control_points = trajectory

        # 计算贝塞尔曲线点
        bezier_points = self._calculate_bezier_points(control_points, 10)

        use_postmsg = self._use_postmsg

        if use_postmsg:
            self._ensure_postmsg()
            self._sync_postmsg_target()
            # 转换为窗口客户区绝对坐标
            abs_points = []
            for bx, by in bezier_points:
                if use_random and self.enable_randomization:
                    bx = self.add_random_offset(bx, self.position_random_range * 0.2)
                    by = self.add_random_offset(by, self.position_random_range * 0.2)
                ax, ay = self.window_mgr.get_postmessage_coords(bx, by)
                abs_points.append((ax, ay))

            if len(abs_points) < 2:
                return

            interval = duration_ms / (len(abs_points) - 1) / 1000.0

            self._postmsg_input.mouse_move_to(*abs_points[0])
            time.sleep(0.005)
            self._postmsg_input.mouse_down(abs_points[0][0], abs_points[0][1])

            for i in range(1, len(abs_points)):
                time.sleep(interval)
                self._postmsg_input.mouse_move_to(*abs_points[i])

            time.sleep(0.005)
            self._postmsg_input.mouse_up(abs_points[-1][0], abs_points[-1][1])
        else:
            # 原有 Interception 逻辑
            screen_points = []
            for bx, by in bezier_points:
                if use_random and self.enable_randomization:
                    bx = self.add_random_offset(bx, self.position_random_range * 0.2)
                    by = self.add_random_offset(by, self.position_random_range * 0.2)
                sx, sy = self.window_mgr.window_to_screen(bx, by)
                screen_points.append((sx, sy))

            if len(screen_points) < 2:
                return

            cursor_lock = self.interception._cursor_lock_mode
            original_pos = self.interception._get_cursor_pos() if cursor_lock else None

            interval = duration_ms / (len(screen_points) - 1) / 1000.0

            self.interception.mouse_move_to(*screen_points[0])
            time.sleep(0.005)
            self.interception.mouse_down()

            for i in range(1, len(screen_points)):
                time.sleep(interval)
                self.interception.mouse_move_to(*screen_points[i])

            time.sleep(0.005)
            self.interception.mouse_up()

            if cursor_lock and original_pos:
                time.sleep(0.005)
                self.interception.mouse_move_to(*original_pos)

    # ==========================================================
    # 贝塞尔曲线（纯数学）
    # ==========================================================

    def _calculate_bezier_points(self, control_points, num_points):
        """计算贝塞尔曲线上的点

        Args:
            control_points: 控制点列表 [(x, y, t), ...]
            num_points: 生成的曲线点数量

        Returns:
            贝塞尔曲线上的点列表 [(x, y), ...]
        """
        def bezier_point(t, points):
            n = len(points) - 1
            x = 0
            y = 0
            for i, (px, py, _) in enumerate(points):
                coeff = self._binomial_coeff(n, i) * ((1 - t) ** (n - i)) * (t ** i)
                x += coeff * px
                y += coeff * py
            return int(x), int(y)

        curve_points = []
        for i in range(num_points):
            t = i / (num_points - 1) if num_points > 1 else 0
            point = bezier_point(t, control_points)
            curve_points.append(point)
        return curve_points

    @staticmethod
    def _binomial_coeff(n, k):
        """计算二项式系数 C(n, k)"""
        return math.factorial(n) // (math.factorial(k) * math.factorial(n - k))

    # ==========================================================
    # 录制
    # ==========================================================

    def on_action_captured(self, action):
        """处理捕获的操作"""
        if self.recording:
            self.recorded_actions.append(action)
            self.action_recorded.emit(action)
            print(f"[InputController] 记录操作 #{len(self.recorded_actions)}: {action['type']}")

    def start_recording(self):
        """开始录制操作"""
        print(f"[InputController] 准备开始录制... 模式: {self.recording_mode}")
        self.recording = True
        self.recorded_actions = []

        if self.recording_mode in ('mouse', 'both'):
            from core.mouse_monitor import MouseMonitor
            self.monitor = MouseMonitor(self.window_mgr)
            self.monitor.action_captured.connect(self.on_action_captured)
            if not self.monitor.start_monitoring():
                if self.recording_mode == 'mouse':
                    self.recording = False
                    print("[InputController] 启动鼠标监控失败")
                    return False

        if self.recording_mode in ('keyboard', 'both'):
            from core.keyboard_monitor import KeyboardMonitor
            self.keyboard_monitor = KeyboardMonitor()
            # 过滤录制快捷键 F9 (VK_F9 = 0x78)，避免被录制捕获
            self.keyboard_monitor.set_filter_vk_codes({0x78})
            self.keyboard_monitor.action_captured.connect(self.on_action_captured)
            if not self.keyboard_monitor.start_monitoring():
                if self.recording_mode == 'keyboard':
                    self.recording = False
                    print("[InputController] 启动键盘监控失败")
                    return False

        print(f"[InputController] 录制已开始")
        return True

    def stop_recording(self):
        """停止录制"""
        print("[InputController] 停止录制...")
        self.recording = False

        if self.monitor:
            try:
                self.monitor.stop_monitoring()
            except Exception as e:
                print(f"[InputController] 停止鼠标监控异常: {e}")

        if self.keyboard_monitor:
            try:
                self.keyboard_monitor.stop_monitoring()
            except Exception as e:
                print(f"[InputController] 停止键盘监控异常: {e}")

        print(f"[InputController] 录制停止，共记录 {len(self.recorded_actions)} 个操作")

        for i, action in enumerate(self.recorded_actions):
            print(f"  操作{i + 1}: {action}")

        return self.recorded_actions

    # ==========================================================
    # 录制文件 I/O
    # ==========================================================

    def save_recording(self, filename, actions=None):
        """保存录制（新格式：带元数据）"""
        if actions is None:
            actions = self.recorded_actions

        # 确保兼容性：补全 start_time_ms 字段
        for action in actions:
            if 'start_time_ms' not in action and 'timestamp_ms' in action:
                if action['type'] in ('long_click', 'swipe'):
                    action['start_time_ms'] = action['timestamp_ms'] - action.get('duration', 0)
                    action['end_time_ms'] = action['timestamp_ms']
                else:
                    action['start_time_ms'] = action['timestamp_ms']
                    action['end_time_ms'] = action['timestamp_ms']

        # 新格式：带元数据
        data = {
            "version": "1.0",
            "app": "ClickYen",
            "target_window": None,
            "created_at": datetime.now().isoformat(),
            "actions": actions,
        }

        # 尝试获取目标窗口信息
        info = self.window_mgr.get_window_info()
        if info:
            data["target_window"] = {
                "title": info.get("title", ""),
                "class": info.get("class_name", ""),
                "size": list(info.get("target_size", (0, 0))),
            }

        with open(filename, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        print(f"[InputController] 录制已保存到: {filename}")

    def load_recording(self, filename):
        """加载录制（兼容新旧格式）"""
        with open(filename, 'r', encoding='utf-8') as f:
            data = json.load(f)

        # 检测格式
        if isinstance(data, list):
            actions = data  # 旧格式：直接是动作数组
        elif isinstance(data, dict) and 'actions' in data:
            actions = data['actions']  # 新格式：带元数据
        else:
            actions = data

        # 兼容性处理：转换旧格式时间戳到 start_time_ms
        for action in actions:
            if 'start_time_ms' not in action:
                if 'timestamp_ms' in action:
                    if action['type'] in ('long_click', 'swipe'):
                        action['start_time_ms'] = action['timestamp_ms'] - action.get('duration', 0)
                        action['end_time_ms'] = action['timestamp_ms']
                    else:
                        action['start_time_ms'] = action['timestamp_ms']
                        action['end_time_ms'] = action['timestamp_ms']
                elif 'time' in action:
                    # 更旧的格式（秒级浮点时间戳）
                    timestamp_ms = int(action['time'] * 1000)
                    if action['type'] in ('long_click', 'swipe'):
                        action['start_time_ms'] = timestamp_ms - action.get('duration', 0)
                        action['end_time_ms'] = timestamp_ms
                    else:
                        action['start_time_ms'] = timestamp_ms
                        action['end_time_ms'] = timestamp_ms

        print(f"[InputController] 从文件加载 {len(actions)} 个操作")
        return actions
