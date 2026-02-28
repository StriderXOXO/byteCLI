# ByteCLI 开发者产品需求文档 (PRD)

**版本**：1.0
**日期**：2026-02-28
**状态**：已审查，可进入开发
**设计稿**：`byte_design_relive.pen`

---

## 目录

1. [产品概述](#1-产品概述)
2. [系统架构](#2-系统架构)
3. [模块详细规格](#3-模块详细规格)
4. [状态机定义](#4-状态机定义)
5. [UI 规格](#5-ui-规格)
6. [错误处理清单](#6-错误处理清单)
7. [国际化字符串表](#7-国际化字符串表)
8. [端到端测试用例](#8-端到端测试用例)

---

## 1. 产品概述

### 1.1 产品定位

ByteCLI 是一款面向 Ubuntu/Linux 桌面用户的**本地语音转文字工具**。用户通过热键触发录音，ByteCLI 使用本地部署的 Whisper 模型将语音实时转换为文字，并自动输入到当前光标所在位置。

### 1.2 核心价值

- **精确转录**：一字不差地将语音转为文字，无幻觉（hallucination）
- **多语言支持**：中文、英文、中英混合语音均可准确识别
- **完全本地**：所有推理在本地完成，无需联网，保障隐私
- **零学习成本**：安装即用，按热键即录，松开即转

### 1.3 目标平台

| 项目 | 规格 |
|---|---|
| 操作系统 | Ubuntu 22.04 LTS 及以上 |
| 桌面环境 | GNOME（主要）、KDE Plasma（兼容） |
| GPU 支持 | NVIDIA CUDA（可选，无 GPU 时回退 CPU） |
| 音频 | PulseAudio / PipeWire |

### 1.4 技术栈概要

| 层级 | 技术选型 |
|---|---|
| 语音识别 | Whisper (openai/whisper) 本地模型 — tiny / small / medium |
| 后台服务 | Python 守护进程（systemd user service） |
| 设置面板 | GTK 4 + libadwaita（暗色主题） |
| 系统指示器 | AppIndicator3（系统托盘浮动窗口） |
| 进程间通信 | D-Bus (session bus) |
| 热键监听 | 全局键盘钩子（Xlib / libinput） |
| 音频采集 | PyAudio / sounddevice |
| 文字输入 | xdotool / ydotool（Wayland 兼容） |
| 配置持久化 | JSON 文件 |
| 国际化 | gettext / 自定义 JSON i18n |

---

## 2. 系统架构

### 2.1 进程模型

```
┌─────────────────────────────────────────────────┐
│                   用户桌面                        │
│                                                   │
│  ┌──────────────┐    ┌──────────────────────┐    │
│  │  Indicator    │    │   Settings Panel      │    │
│  │  (浮动窗口)   │    │   (GTK 4 窗口)        │    │
│  └──────┬───────┘    └──────────┬───────────┘    │
│         │ D-Bus                  │ D-Bus           │
│  ┌──────┴────────────────────────┴───────────┐   │
│  │         ByteCLI Service Daemon             │   │
│  │                                             │   │
│  │  ┌─────────┐ ┌──────────┐ ┌────────────┐  │   │
│  │  │ Hotkey  │ │ Whisper  │ │ Audio      │  │   │
│  │  │ Manager │ │ Engine   │ │ Capture    │  │   │
│  │  └─────────┘ └──────────┘ └────────────┘  │   │
│  │  ┌─────────┐ ┌──────────┐ ┌────────────┐  │   │
│  │  │ History │ │ i18n     │ │ Config     │  │   │
│  │  │ Manager │ │ Module   │ │ Manager    │  │   │
│  │  └─────────┘ └──────────┘ └────────────┘  │   │
│  └─────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────┘
```

### 2.2 进程职责

| 进程 | 生命周期 | 职责 |
|---|---|---|
| **Service Daemon** | 常驻后台 | 热键监听、音频采集、Whisper 推理、历史管理、配置管理 |
| **Indicator Widget** | 随服务启停 | 显示当前状态（Idle/Recording）、展示 History 面板 |
| **Settings Panel** | 用户按需打开 | 配置项的图形界面、服务控制（启停重启） |

### 2.3 D-Bus 接口定义

**Bus Name**: `com.bytecli.Service`
**Object Path**: `/com/bytecli/Service`
**Interface**: `com.bytecli.ServiceInterface`

| 方法 | 参数 | 返回 | 说明 |
|---|---|---|---|
| `GetStatus()` | — | `s` (状态字符串) | 获取服务当前状态 |
| `Stop()` | — | `b` (成功/失败) | 停止服务 |
| `Restart()` | — | `b` | 重启服务 |
| `RefreshIndicator()` | — | `b` | 刷新指示器 |
| `SwitchModel(model)` | `s` | `b` | 切换模型 ("tiny"/"small"/"medium") |
| `SwitchDevice(device)` | `s` | `b` | 切换设备 ("gpu"/"cpu") |
| `SetHotkey(keys)` | `as` | `(bs)` | 设置热键，返回 (成功, 冲突信息) |
| `GetHistory()` | — | `a(ssx)` | 获取历史记录 [(文本, 时间戳, id)] |
| `GetAudioDevices()` | — | `a(ss)` | 获取音频设备 [(id, name)] |
| `GetConfig()` | — | `s` (JSON) | 获取当前配置 |
| `SaveConfig(json)` | `s` | `b` | 保存配置 |

**信号 (Signals)**:

| 信号 | 参数 | 说明 |
|---|---|---|
| `StatusChanged(status)` | `s` | 服务状态变更 |
| `ModelSwitchProgress(state, msg)` | `ss` | 模型切换进度 ("switching"/"success"/"failed", 消息) |
| `DeviceSwitchProgress(state, msg)` | `ss` | 设备切换进度 |
| `RecordingStarted()` | — | 录音开始 |
| `RecordingStopped(text)` | `s` | 录音结束，附带转录文字 |
| `AudioDeviceChanged(devices)` | `a(ss)` | 音频设备列表变更 |

### 2.4 文件路径

| 用途 | 路径 |
|---|---|
| 配置文件 | `~/.config/bytecli/config.json` |
| 模型文件 | `~/.local/share/bytecli/models/` |
| 历史记录 | `~/.local/share/bytecli/history.json` |
| 运行日志 | `~/.local/share/bytecli/logs/bytecli.log` |
| PID 文件 | `/run/user/$UID/bytecli.pid` |
| systemd 服务 | `~/.config/systemd/user/bytecli.service` |
| 桌面快捷方式 | `~/.local/share/applications/bytecli-settings.desktop` |
| 自启动入口 | `~/.config/autostart/bytecli.desktop` |

### 2.5 配置文件格式

```json
{
  "model": "small",
  "device": "gpu",
  "audio_input": "auto",
  "hotkey": {
    "mode": "double",
    "keys": ["Ctrl", "Alt", "V"]
  },
  "language": "en",
  "auto_start": false,
  "history_max_entries": 50
}
```

| 字段 | 类型 | 默认值 | 约束 |
|---|---|---|---|
| `model` | string | `"small"` | `"tiny"` / `"small"` / `"medium"` |
| `device` | string | `"gpu"` (有 CUDA) 或 `"cpu"` | `"gpu"` / `"cpu"` |
| `audio_input` | string | `"auto"` | 设备 ID 或 `"auto"` |
| `hotkey.mode` | string | `"double"` | `"double"` / `"triple"` |
| `hotkey.keys` | string[] | `["Ctrl", "Alt", "V"]` | 2-3 个键名 |
| `language` | string | `"en"` | `"en"` / `"zh"` |
| `auto_start` | boolean | `false` | — |
| `history_max_entries` | integer | `50` | 1-500 |

---

## 3. 模块详细规格

### 3.1 服务生命周期管理器 (Service Manager)

#### 3.1.1 状态定义

| 状态 | 标识符 | 说明 |
|---|---|---|
| **Stopped** | `STOPPED` | 服务未运行，Indicator 不可见 |
| **Starting** | `STARTING` | 服务正在启动（加载模型等） |
| **Running** | `RUNNING` | 服务正常运行，Indicator 可见 |
| **Stopping** | `STOPPING` | 服务正在停止 |
| **Restarting** | `RESTARTING` | 服务正在重启（先停后启） |
| **Failed** | `FAILED` | 服务启动失败 |

#### 3.1.2 状态转换规则

| 当前状态 | 触发事件 | 目标状态 | 动作 |
|---|---|---|---|
| STOPPED | 用户点击 Start / 系统自启动 | STARTING | 初始化引擎、加载模型、注册热键 |
| STARTING | 初始化成功 | RUNNING | 显示 Indicator、发送 StatusChanged 信号 |
| STARTING | 初始化失败 | FAILED | 记录错误日志、显示错误详情 |
| STARTING | 超时（30 秒） | FAILED | 记录超时日志 |
| RUNNING | 用户点击 Stop | STOPPING | 停止热键监听、释放模型 |
| RUNNING | 服务进程崩溃 | FAILED | 自动检测、记录 coredump 信息 |
| STOPPING | 资源释放完成 | STOPPED | 隐藏 Indicator、发送 StatusChanged |
| STOPPING | 超时（10 秒） | STOPPED | 强制终止子进程、标记为 Stopped |
| FAILED | 用户点击 Restart | RESTARTING | 清理残留资源 |
| RESTARTING | 停止完成 | STARTING | 重新初始化 |
| RUNNING | 用户点击 Restart | RESTARTING | 停止当前服务后重新启动 |

#### 3.1.3 超时策略

| 操作 | 超时时间 | 超时处理 |
|---|---|---|
| 启动 | 30 秒 | 转入 FAILED，日志记录 "Start timeout"，Toast 提示 |
| 停止 | 10 秒 | 强制 SIGKILL，转入 STOPPED |
| 重启 | 40 秒（停止 10 + 启动 30） | 转入 FAILED |
| 模型切换 | 60 秒 | 回退到上一个模型，Toast 提示超时 |

#### 3.1.4 崩溃恢复

- 服务进程意外退出时，由 systemd 的 `Restart=on-failure` 自动重启
- 最大连续重启次数：3 次（`StartLimitBurst=3`）
- 重启间隔：5 秒（`RestartSec=5`）
- 超过重启上限后，转入 FAILED 状态，需用户手动干预

#### 3.1.5 Indicator 唯一性保证

**核心约束**：在任何时刻，系统中有且仅有一个 Indicator 实例。

实现机制：
1. 启动时检查 PID 文件 `/run/user/$UID/bytecli.pid`
2. 若 PID 文件存在且进程存活 → 发送 D-Bus 信号通知已有实例
3. 若 PID 文件存在但进程已死 → 清理 PID 文件后正常启动
4. 正常启动时写入当前 PID
5. Refresh Indicator 操作：销毁当前 Indicator 窗口 → 重新创建 → 写入新 PID

---

### 3.2 语音识别引擎 (Speech Recognition Engine)

#### 3.2.1 模型规格

| 显示名称 | 模型标识 | Whisper 模型 | 模型大小 | 推荐场景 |
|---|---|---|---|---|
| Fast (tiny) | `tiny` | `whisper-tiny` | ~75 MB | 低配设备、追求速度 |
| **Balanced (small)** | `small` | `whisper-small` | ~465 MB | **默认选项**，速度与精度平衡 |
| Accurate (medium) | `medium` | `whisper-medium` | ~1.5 GB | 高配设备、追求精度 |

#### 3.2.2 模型文件管理

- 模型存储路径：`~/.local/share/bytecli/models/{model_name}/`
- 首次使用某模型时自动下载（显示下载进度）
- 下载失败时保留部分文件，下次启动续传
- 模型校验：下载完成后校验 SHA256

#### 3.2.3 模型切换流程

1. 用户在设置面板选择新模型
2. 前端立即显示 "Switching..." 状态（橙色 spinner）
3. 前端禁用其他模型选项（opacity 0.4）
4. 后台发送 `SwitchModel(model)` D-Bus 调用
5. 后台执行：卸载当前模型 → 加载新模型 → 预热推理
6. 成功：发送 `ModelSwitchProgress("success", "")` → 前端显示绿色 ✓ "Switch complete"（持续 2 秒后恢复正常状态）
7. 失败：发送 `ModelSwitchProgress("failed", error_msg)` → 自动回退到上一个模型 → 前端显示红色 ✗ "Switch failed — reverted to [previous]"

**关键约束**：
- 模型切换期间，热键录音功能暂停
- 若切换过程中再次收到切换请求，忽略后续请求（防抖）
- 失败后必须保证服务仍在 RUNNING 状态且上一个模型可用

#### 3.2.4 计算设备管理

| 设备 | 标识 | 检测方式 |
|---|---|---|
| GPU (CUDA) | `gpu` | 检查 `torch.cuda.is_available()` |
| CPU | `cpu` | 始终可用 |

**设备选择逻辑**：
1. 启动时检测 CUDA 是否可用
2. 若 CUDA 可用 → 默认选择 GPU，同时提供 CPU 选项
3. 若 CUDA 不可用 → 自动选择 CPU，GPU 选项标记为禁用并显示 "CUDA not detected"（红色小字）
4. GPU 选项被禁用时，radio button 设为 `disabled`，opacity 0.4

**设备切换流程**（与模型切换同构）：
1. 显示 "Switching..." + spinner
2. 后台重新加载模型到目标设备
3. 成功：显示 ✓ "Switch complete"
4. 失败：回退到上一个设备，显示 ✗ "Switch failed — reverted to [previous]"

#### 3.2.5 音频采集参数

| 参数 | 值 |
|---|---|
| 采样率 | 16000 Hz |
| 声道数 | 1（单声道） |
| 位深 | 16-bit PCM |
| 缓冲区大小 | 1024 frames |
| 静音检测阈值 | -40 dB |

#### 3.2.6 转录行为

- 语言自动检测：由 Whisper 自动判断中文/英文/混合
- 不设置 `language` 参数，允许模型自由识别
- 转录结果直接通过 `xdotool type` / `ydotool type` 输入到当前焦点窗口
- 同时将结果追加到历史记录

---

### 3.3 指示器组件 (Indicator Widget)

#### 3.3.1 显示/隐藏规则

| 服务状态 | Indicator 可见 |
|---|---|
| RUNNING | **是** |
| STOPPING | 是（显示至完全停止） |
| STOPPED | **否** |
| STARTING | 否（启动完成后显示） |
| RESTARTING | 是（保持显示，内容更新为 Idle） |
| FAILED | **否** |

#### 3.3.2 Indicator 状态

| 状态 | 触发条件 | 视觉表现 |
|---|---|---|
| **Idle - Default** | 服务运行中，无录音，光标未悬停 | 灰色圆点 + "Idle"（或 "空闲"） |
| **Idle - Hover** | 光标悬停在 Indicator 上 | 灰色圆点 + "Idle" + 分隔线 + History 按钮 |
| **Recording - Default** | 录音进行中，光标未悬停 | 绿色圆点 + "Recording"（或 "录音中"）+ 计时器 "MM:SS" |
| **Recording - Hover** | 录音进行中，光标悬停 | 绿色圆点 + "Recording" + 计时器 + 分隔线 + History 按钮 |

#### 3.3.3 Indicator 样式规格

- 外形：圆角胶囊（cornerRadius: 20）
- 背景：`--card`（暗色模式 `#1A1A1A`）
- 边框：`--border` 1px inside
- 阴影：blur 12, y-offset 4, `#00000015`
- 内边距：垂直 10px，水平 16px
- 元素间距：10px
- 状态圆点：8×8 圆形
  - Idle: `--muted-foreground`
  - Recording: `--color-success-foreground`
- 文字："JetBrains Mono" 13px, weight 500, `--foreground`
- 计时器："JetBrains Mono" 13px, weight normal, `--muted-foreground`
- History 按钮：圆角 12，背景 `--secondary`，内边距 4×8，图标 history 14×14 + 文字 "Geist" 12px

#### 3.3.4 屏幕定位

- 默认位置：屏幕底部居中，距底边 48px
- 使用 GTK Layer Shell（Wayland）或 `_NET_WM_WINDOW_TYPE_DOCK`（X11）
- 始终置顶（always on top），不接受焦点（no-focus）
- 可被其他全屏应用覆盖

#### 3.3.5 History 面板

**触发方式**：
- 光标悬停到 Indicator 区域 → History 按钮出现
- 点击 History 按钮 → History 面板从 Indicator 上方弹出
- 光标离开 Indicator + History 面板区域 → History 面板收起

**面板规格**（有内容时）：
- 宽度：300px
- 背景：`--card`
- 圆角：12px
- 边框：`--border` 1px inside
- 阴影：blur 16, y-offset -4, `#00000040`
- 头部：左侧 "History"（"Geist" 13px, weight 600）+ 右侧条目计数（"Geist" 12px, `--muted-foreground`）
- 分隔线：`--border` 1px 高
- 每条记录：左侧文字（截断，最多 1 行）+ 右侧时间戳 + 复制图标（clipboard 14×14）
- 内边距：每行 10px × 14px
- 最大显示条目：最近 20 条（可滚动）

**点击条目行为**：
1. 将该条转录文字复制到系统剪贴板
2. 显示 Toast "Copied to clipboard" / "已复制到剪贴板"（Success 类型，2 秒后自动消失）

**空状态**：
- 居中显示图标 `message-square-dashed`（24×24，`--muted-foreground`）
- 下方文字 "No voice input history yet" / "暂无语音输入历史"（"Geist" 13px, `--muted-foreground`）
- 面板高度固定 120px

---

### 3.4 设置面板 (Settings Panel)

#### 3.4.1 窗口规格

| 属性 | 值 |
|---|---|
| 宽度 | 480px（固定） |
| 高度 | 1150px（英文）/ 1180px（中文） |
| 圆角 | `--radius-m` (16px) |
| 背景 | `--card` |
| 边框 | `--border` 1px inside |
| 阴影 | blur 24, y-offset 8, `#00000015` |
| 内边距 | 24px |
| 区段间距 | 20px |
| 主题 | 仅暗色模式（Dark） |

#### 3.4.2 窗口管理

- **单实例**：同一时间只允许一个设置面板窗口存在
- **桌面入口**：安装后在桌面创建 `.desktop` 文件，双击打开设置面板
- **启动方式**：`bytecli-settings` 命令行或双击桌面图标
- 若面板已打开，再次启动时聚焦到已有窗口

#### 3.4.3 区段 1：Server Status（服务状态）

**标签**：`"Server Status"` / `"服务状态"`

**卡片内容**：
- 第一行（serverTopRow）：
  - 左侧：状态点 (8×8 圆形) + 状态文字
  - 右侧：操作按钮
- 第二行（refreshRow）：
  - 左侧：提示文字 `"Floating indicator disappeared?"` / `"浮动指示器消失了？"`
  - 右侧：`Refresh Indicator` / `"刷新指示器"` 按钮

**状态 → UI 映射**：

| 状态 | 圆点颜色 | 状态文字 | 按钮 |
|---|---|---|---|
| Running | `--color-success-foreground` (绿) | "Running ({model})" / "运行中 ({model})" | [Stop] [Restart] — enabled |
| Stopping | `--color-warning-foreground` (橙) | "Stopping..." / "停止中..." | [Stop] 显示 spinner, [Restart] disabled |
| Stopped | `--color-error-foreground` (红) | "Stopped" / "已停止" | [Start] — enabled (橙色主色调) |
| Starting | `--color-warning-foreground` (橙) | "Starting..." / "启动中..." | [Stop] disabled, [Restart] disabled |
| Restarting | `--color-warning-foreground` (橙) | "Restarting..." / "重启中..." | [Stop] disabled, [Restart] disabled |
| Failed | `--color-error-foreground` (红) | "Failed to start" / "启动失败" | [Restart] — enabled |

**Failed 状态额外信息**：
- 在按钮行下方显示错误详情文字
- 字体："Geist" 12px, `--color-error-foreground`
- 示例："Error: Model file not found. Please check installation."

**Refresh Indicator 按钮**：
- 仅在 RUNNING 状态下可点击
- 点击后：销毁当前 Indicator → 重新创建
- 反馈：Toast "Indicator refreshed" / "指示器已刷新"

#### 3.4.4 区段 2：Model Selection（模型选择）

**标签**：`"Model Selection"` / `"模型选择"`

**控件类型**：Radio group（单选）

**选项**：

| 选项 | 描述文字 (EN) | 描述文字 (ZH) |
|---|---|---|
| Fast (tiny) | Fastest response | 响应最快 |
| **Balanced (small)** | **Recommended** | **推荐** |
| Accurate (medium) | Most accurate | 最高精度 |

- 默认选中：Balanced (small)
- "Recommended" / "推荐" 使用 `--primary` 橙色高亮

**切换过渡态**（参见 §4.2 状态机）：
- Switching: 选中项旁显示 spinner（14×14 loader-2），描述变为 "Switching..."（橙色 `--color-warning-foreground`），其他选项 opacity 0.4
- Success: 选中项旁显示 ✓（circle-check），描述变为 "Switch complete"（绿色 `--color-success-foreground`），2 秒后恢复
- Failed: 选中项旁显示 ✗（circle-x），描述变为 "Switch failed"（红色 `--color-error-foreground`），自动回退选择，显示 "Retry" 链接

#### 3.4.5 区段 3：Device（计算设备）

**标签**：`"Device"` / `"计算设备"`

**控件类型**：Radio group（单选）

| 选项 | 条件 |
|---|---|
| GPU (CUDA) | CUDA 可用时启用；不可用时禁用，显示 "CUDA not detected" / "未检测到 CUDA" |
| CPU | 始终可用 |

- 默认：若 CUDA 可用则 GPU，否则 CPU
- GPU 不可用时：radio 禁用，整行 opacity 0.4，在 "GPU (CUDA)" 下方追加红色小字 "CUDA not detected" (`--color-error-foreground`, 11px)，CPU 行自动选中并追加 "(auto-selected)" / "(自动选择)"

**切换过渡态**：与模型切换同构（Switching / Success / Failed），参见 §4.3

#### 3.4.6 区段 4：Audio Input（音频输入）

**标签**：`"Audio Input"` / `"音频输入"`

**控件类型**：Dropdown select

- 自动检测所有可用音频输入设备
- 默认显示 `"Auto (System Default)"` / `"自动 (系统默认)"`
- 下拉列表显示所有检测到的设备名称
- 设备热插拔时实时更新列表（通过 PulseAudio/PipeWire 事件监听）

**无设备异常状态**：
- 下拉框边框变为 `--color-error-foreground` (红)
- 内容显示 `triangle-alert` 图标 + "No devices detected" / "未检测到设备" (红色文字)
- 下方提示："Please connect an audio input device to use voice dictation." / "请连接音频输入设备以使用语音听写。"（"Geist" 11px, `--muted-foreground`）

#### 3.4.7 区段 5：Hotkey（快捷键）

**标签**：`"Hotkey"` / `"快捷键"`

**控件**：
- **Mode 行**：标签 "Mode:" / "模式:" + Dropdown（"Double Key" / "双键" 或 "Triple Key" / "三键"）
- **Key 行**：标签 "Key:" / "按键:" + Dropdown（预设组合）+ [Custom...] / [自定义...] 按钮
- **反馈行**：状态文字

**预设热键**：

| Mode | 预设选项 |
|---|---|
| Double Key | `Ctrl+Space`, `Alt+Space`, `Ctrl+Alt+V` |
| Triple Key | `Ctrl+Alt+Space`, `Ctrl+Shift+Space`, `Super+Alt+V` |

**反馈文字状态**：

| 状态 | 文字 | 颜色 |
|---|---|---|
| 可用 | "✓ Available" / "✓ 可用" | `--color-success-foreground` (绿) |
| 冲突 | "✗ Conflict with {source} — reverted to {prev}" / "✗ 与 {source} 冲突 — 已恢复为 {prev}" | `--color-error-foreground` (红) |

**自定义按键捕获模式**（点击 Custom 按钮触发）：
1. Key 下拉框变为输入框，边框高亮 `--primary` 2px
2. placeholder: "Press your hotkey..." / "按下快捷键..."
3. 旁边显示 "Cancel" / "取消" 文字链接
4. 下方提示："Press a 2 or 3 key combination. Original hotkey functions are suppressed." / "按下 2 或 3 键组合。原快捷键功能已被抑制。"
5. 用户按下组合键后：
   - 无冲突 → 设置成功，退出捕获模式，反馈显示 "✓ Available"
   - 有冲突 → 弹出 Hotkey Conflict Modal，自动恢复上一个热键

**按键抑制机制**：
- 进入捕获模式时，临时抢占（grab）所有键盘事件
- 使用 `XGrabKeyboard()` (X11) 或 `inhibit_shortcuts` (Wayland)
- 确保用户按下的组合键不会触发系统/应用快捷键
- 退出捕获模式时释放抢占

**冲突检测算法**：
1. 查询系统全局快捷键（gsettings / kglobalaccel）
2. 查询已知应用快捷键（通过 D-Bus 查询活跃窗口绑定）
3. 对比用户输入的组合键
4. 若匹配到任何已注册快捷键 → 判定为冲突

**Hotkey Conflict Modal（冲突弹窗）**：
- 尺寸：360×220px（含遮罩层），内容卡片 300px 宽
- 遮罩：`#000000AA` 半透明黑色
- 卡片：`--card` 背景，圆角 12，阴影 blur 24
- 图标：`triangle-alert` 24×24, `--color-warning-foreground`
- 标题："Hotkey Conflict Detected" / "检测到快捷键冲突"（"JetBrains Mono" 16px, weight 600）
- 正文："The combination {keys} is already used by {source}. Your hotkey has been kept as {prev}."
- 按钮：[OK] 全宽，`--primary` 背景，高度 40px，圆角 pill

#### 3.4.8 区段 6：Language（语言）

**标签**：`"Language"` / `"语言"`

**控件**：行内标签 "Interface Language:" / "界面语言:" + Dropdown

| 选项 | 值 |
|---|---|
| English | `"en"` |
| 中文 | `"zh"` |

**切换行为**：
- 选择后**即时生效**（无需点击 Save）
- 设置面板的所有文本瞬间切换为目标语言
- Indicator 的所有文本瞬间切换
- 语言偏好立即写入配置文件（独立于 Save 按钮）

#### 3.4.9 区段 7：Startup（启动）

**标签**：`"Startup"` / `"启动"`

**控件**：Checkbox + 标签 "Start automatically on system boot" / "系统启动时自动运行"

**实现**：
- 选中时：创建 `~/.config/autostart/bytecli.desktop` 文件
- 取消时：删除该文件
- .desktop 文件内容：
  ```ini
  [Desktop Entry]
  Type=Application
  Name=ByteCLI
  Exec=bytecli-service --start
  Hidden=false
  X-GNOME-Autostart-enabled=true
  ```

#### 3.4.10 Save / Cancel 按钮

**位置**：面板底部，右对齐

**变更感知逻辑**：
- 面板打开时加载当前配置快照
- 用户修改任何配置项（除 Language 外）时：
  - 比对当前值与快照值
  - 若有差异 → Save/Cancel 变为 enabled（Cancel 有边框，Save 为橙色 `--primary`）
  - 若无差异 → Save/Cancel 变为 disabled（opacity 0.4, `--muted` 背景, `--muted-foreground` 文字）

**Save 行为**：
1. 将所有变更项通过 D-Bus `SaveConfig()` 发送到 Service
2. Service 验证配置 → 写入 `config.json` → 按需执行操作（如切换模型/设备）
3. 成功：Toast "Settings saved" / "设置已保存"，更新配置快照
4. 失败：Toast "Failed to save settings" / "保存设置失败"，保留当前编辑

**Cancel 行为**：
1. 将所有配置项恢复为快照值
2. Save/Cancel 恢复 disabled 状态

---

### 3.5 热键管理器 (Hotkey Manager)

#### 3.5.1 录音流程（切换模式）

1. 用户**按下**热键组合 → 开始录音
2. Indicator 切换到 Recording 状态，计时器开始
3. 用户**再次按下**热键 → 停止录音并开始转录
4. 音频数据发送到 Whisper 引擎进行推理
5. 推理完成 → 结果通过 `xdotool type` 输入到当前焦点窗口
6. 同时追加到历史记录
7. Indicator 切换回 Idle 状态

**边界情况**：
- 两次按键间隔 < 0.3 秒：忽略第二次按键，视为误触（双击过快）
- 录音时间 > 300 秒（5 分钟）：自动停止录音，Toast 警告
- 推理期间再次按下热键：忽略，不中断当前推理
- 服务非 RUNNING 状态时按热键：无反应

#### 3.5.2 全局热键注册

- 使用 `Xlib.XGrabKey()` (X11) 或 `GlobalShortcuts` portal (Wayland)
- 服务启动时注册，停止时注销
- 确保释放时干净注销，避免快捷键泄漏

---

### 3.6 音频输入管理器 (Audio Input Manager)

#### 3.6.1 设备检测

- 启动时扫描所有 PulseAudio / PipeWire source
- 过滤 `monitor` 类型设备（仅保留实际输入设备）
- 默认选择 PulseAudio 的 `@DEFAULT_SOURCE@`

#### 3.6.2 热插拔监听

- 订阅 PulseAudio 的 `PA_SUBSCRIPTION_MASK_SOURCE` 事件
- 设备插入：追加到设备列表，发送 `AudioDeviceChanged` 信号
- 设备拔出：
  - 若拔出的是当前选择的设备 → 自动回退到默认设备，Toast 通知
  - 若拔出的不是当前设备 → 仅更新列表

#### 3.6.3 无设备处理

- 所有输入设备断开时：
  - Audio Input 区段显示红色 "No devices detected" 错误状态
  - 热键录音功能自动暂停
  - 设备重新连接后自动恢复

---

### 3.7 历史记录管理器 (History Manager)

#### 3.7.1 存储规格

| 属性 | 值 |
|---|---|
| 存储格式 | JSON 数组 |
| 文件路径 | `~/.local/share/bytecli/history.json` |
| 最大条目数 | 50（可配置，1-500） |
| 淘汰策略 | FIFO（超出上限时删除最旧条目） |

#### 3.7.2 条目格式

```json
{
  "id": "uuid-v4",
  "text": "转录的文字内容",
  "timestamp": "2026-02-28T10:30:45+08:00",
  "model": "small",
  "duration_ms": 3500
}
```

#### 3.7.3 复制到剪贴板

- 使用 `xclip` / `wl-copy` 写入系统剪贴板
- 复制成功后显示 Toast "Copied to clipboard" / "已复制到剪贴板"
- 复制失败显示 Toast Error

---

### 3.8 国际化模块 (i18n)

#### 3.8.1 实现方式

- 使用 JSON 格式的字符串表
- 路径：`/usr/share/bytecli/i18n/{lang}.json` 或内嵌
- 语言代码：`en` / `zh`
- 所有 UI 文本通过 `i18n.t("key")` 函数获取

#### 3.8.2 切换机制

1. 用户在 Language dropdown 选择新语言
2. 立即更新内存中的语言标识
3. 触发所有 UI 组件刷新（GTK 信号）
4. Indicator 通过 D-Bus 信号接收语言变更
5. 写入配置文件

**性能要求**：语言切换必须在 100ms 内完成视觉更新（"瞬间"体感）

---

### 3.9 开机自启动 (Auto-start)

#### 3.9.1 实现方案

**主方案：XDG Autostart**
- 创建/删除 `~/.config/autostart/bytecli.desktop`

**备选方案：systemd user service**
- `systemctl --user enable/disable bytecli.service`

#### 3.9.2 行为验证

- 启用后：系统重启 → 自动登录 → Service Daemon 自动启动 → Indicator 显示
- 禁用后：系统重启 → 无 ByteCLI 进程运行

---

## 4. 状态机定义

本章用形式化方式定义所有关键状态机。每个状态机均需实现为明确的枚举状态 + 事件驱动转换，禁止出现未定义的中间状态。

### 4.1 服务生命周期状态机

```
                  ┌──────────────────────────────┐
                  │                                │
                  ▼                                │
  ┌─────────┐  start   ┌──────────┐  success  ┌──────────┐
  │ STOPPED │────────►│ STARTING │─────────►│ RUNNING  │
  │         │          │          │           │          │
  └─────────┘          └────┬─────┘           └──┬───┬──┘
       ▲                     │                    │   │
       │                     │ fail/timeout       │   │
       │                     ▼                    │   │
       │               ┌──────────┐               │   │
       │               │  FAILED  │◄──────────────┘   │
       │               │          │    crash           │
       │               └────┬─────┘                    │
       │                     │ restart                  │ stop
       │                     ▼                          ▼
       │              ┌────────────┐            ┌──────────┐
       │              │ RESTARTING │            │ STOPPING │
       │              │            │            │          │
       │              └──────┬─────┘            └────┬─────┘
       │                     │                        │
       │                     │ stopped                │ done/timeout
       │                     ▼                        │
       │              ┌──────────┐                    │
       │              │ STARTING │                    │
       │              └──────────┘                    │
       │                                              │
       └──────────────────────────────────────────────┘
```

**状态枚举**：`STOPPED` | `STARTING` | `RUNNING` | `STOPPING` | `RESTARTING` | `FAILED`

**事件表**：

| 事件 | 来源 |
|---|---|
| `EVT_START` | 用户点击 Start / 系统自启动 |
| `EVT_STOP` | 用户点击 Stop |
| `EVT_RESTART` | 用户点击 Restart |
| `EVT_INIT_SUCCESS` | 引擎初始化完成 |
| `EVT_INIT_FAIL` | 引擎初始化失败 |
| `EVT_INIT_TIMEOUT` | 启动超时（30s） |
| `EVT_SHUTDOWN_DONE` | 资源释放完成 |
| `EVT_SHUTDOWN_TIMEOUT` | 停止超时（10s） |
| `EVT_CRASH` | 进程意外退出 |

**转换表**：

| 当前状态 | 事件 | 目标状态 | 副作用 |
|---|---|---|---|
| STOPPED | EVT_START | STARTING | 初始化引擎 |
| STARTING | EVT_INIT_SUCCESS | RUNNING | 显示 Indicator, 注册热键 |
| STARTING | EVT_INIT_FAIL | FAILED | 记录错误, Toast |
| STARTING | EVT_INIT_TIMEOUT | FAILED | 记录超时 |
| RUNNING | EVT_STOP | STOPPING | 注销热键, 释放模型 |
| RUNNING | EVT_RESTART | RESTARTING | 开始停止流程 |
| RUNNING | EVT_CRASH | FAILED | 记录 coredump |
| STOPPING | EVT_SHUTDOWN_DONE | STOPPED | 隐藏 Indicator |
| STOPPING | EVT_SHUTDOWN_TIMEOUT | STOPPED | SIGKILL, 隐藏 Indicator |
| RESTARTING | EVT_SHUTDOWN_DONE | STARTING | 重新初始化 |
| FAILED | EVT_RESTART | RESTARTING | 清理残留 |
| FAILED | EVT_START | STARTING | 清理残留 |

**非法转换（静默忽略）**：
- STARTING 状态下的 EVT_STOP / EVT_RESTART
- STOPPING 状态下的所有事件（除 SHUTDOWN_DONE/TIMEOUT）
- RESTARTING 状态下的 EVT_STOP / EVT_RESTART

---

### 4.2 模型切换状态机

```
  ┌────────┐  switch(model)  ┌────────────┐
  │  IDLE  │───────────────►│ SWITCHING  │
  │        │                 │            │
  └────────┘                 └──┬──────┬──┘
       ▲                        │      │
       │      success           │      │ fail
       │◄───────────────────────┘      │
       │                                │
       │      fail (auto-revert)        │
       │◄───────────────────────────────┘
```

**状态**：`IDLE` | `SWITCHING`

**转换表**：

| 当前 | 事件 | 目标 | 副作用 |
|---|---|---|---|
| IDLE | switch(new_model) | SWITCHING | 卸载旧模型, 加载新模型; UI: spinner + "Switching..." |
| SWITCHING | load_success | IDLE | UI: ✓ "Switch complete" (2s); 更新 Server Status 显示 |
| SWITCHING | load_fail | IDLE | 重新加载旧模型; UI: ✗ "Switch failed — reverted to {old}" |
| SWITCHING | timeout (60s) | IDLE | 同 load_fail 处理 |
| SWITCHING | switch(another) | SWITCHING | **忽略**，防抖 |

---

### 4.3 设备切换状态机

与模型切换状态机完全同构。

**状态**：`IDLE` | `SWITCHING`

**转换表**：

| 当前 | 事件 | 目标 | 副作用 |
|---|---|---|---|
| IDLE | switch(new_device) | SWITCHING | 模型迁移到新设备; UI: spinner |
| SWITCHING | migrate_success | IDLE | UI: ✓ "Switch complete" |
| SWITCHING | migrate_fail | IDLE | 回退旧设备; UI: ✗ "Switch failed" |
| SWITCHING | timeout (60s) | IDLE | 同 fail 处理 |

---

### 4.4 热键配置状态机

```
  ┌──────────┐  click Custom  ┌───────────┐
  │ NORMAL   │──────────────►│ CAPTURING │
  │          │                │           │
  └──────────┘                └──┬─────┬──┘
       ▲                         │     │
       │    valid keys           │     │ conflict / cancel
       │◄────────────────────────┘     │
       │                                │
       │    conflict → show modal       │
       │◄───────────────────────────────┘
```

**状态**：`NORMAL` | `CAPTURING`

**转换表**：

| 当前 | 事件 | 目标 | 副作用 |
|---|---|---|---|
| NORMAL | click_custom | CAPTURING | 显示输入框, grab 键盘, 抑制原快捷键 |
| NORMAL | select_preset(keys) | NORMAL | 检查冲突 → 无冲突则设置; 有冲突则显示 conflict 反馈 |
| CAPTURING | key_combo_valid | NORMAL | 设置新热键, release grab, 显示 "✓ Available" |
| CAPTURING | key_combo_conflict | NORMAL | 弹出 Conflict Modal, release grab, 恢复旧热键 |
| CAPTURING | click_cancel | NORMAL | Release grab, 恢复旧热键 |
| CAPTURING | escape_key | NORMAL | 同 click_cancel |

---

### 4.5 录音流程状态机（切换模式）

```
  ┌──────────┐  hotkey_press  ┌────────────┐  hotkey_press  ┌──────────────┐
  │  IDLE    │──────────────►│ RECORDING  │───────────────►│ TRANSCRIBING │
  │          │                │            │                 │              │
  └──────────┘                └────────────┘                 └──────┬───────┘
       ▲                                                            │
       │                     transcribe_done                        │
       │◄───────────────────────────────────────────────────────────┘
```

**状态**：`IDLE` | `RECORDING` | `TRANSCRIBING`

**转换表**：

| 当前 | 事件 | 目标 | 副作用 |
|---|---|---|---|
| IDLE | hotkey_press | RECORDING | 开始音频采集, Indicator → Recording, 启动计时器 |
| RECORDING | hotkey_press | TRANSCRIBING | 停止采集, 发送音频到引擎 |
| RECORDING | duration > 300s | TRANSCRIBING | 自动停止, Toast 警告 |
| RECORDING | hotkey_press (间隔 < 0.3s) | IDLE | 忽略（双击误触） |
| TRANSCRIBING | hotkey_press | — (忽略) | 转录进行中，不响应 |
| TRANSCRIBING | transcribe_done(text) | IDLE | xdotool type, 追加历史, Indicator → Idle |
| TRANSCRIBING | transcribe_fail | IDLE | Toast Error, Indicator → Idle |

---

### 4.6 Indicator 显示状态机

```
  ┌──────────┐  service_running  ┌─────────────────┐
  │ HIDDEN   │─────────────────►│ VISIBLE (Idle)   │
  │          │                   │                   │
  └──────────┘                   └──┬────────────┬──┘
       ▲                            │             │
       │                    recording_start   mouse_enter
       │                            │             │
       │                            ▼             ▼
       │                   ┌────────────┐  ┌──────────────────┐
       │                   │ VISIBLE    │  │ VISIBLE (Idle)   │
       │                   │ (Recording)│  │ + History Panel  │
       │                   └────────────┘  └──────────────────┘
       │
       │  service_stopped / service_failed
       │◄──────────────────────────────────
```

---

## 5. UI 规格

### 5.1 设计 Token 表

以下 token 值均取自设计稿 `byte_design_relive.pen` 的变量定义。**本产品仅使用 Dark 主题**。

#### 5.1.1 颜色 Token

| Token 名称 | Dark 模式值 | 用途 |
|---|---|---|
| `--background` | `#111111` | 页面/输入框背景 |
| `--foreground` | `#FFFFFF` | 主要文字 |
| `--card` | `#1A1A1A` | 卡片/面板背景 |
| `--card-foreground` | `#FFFFFF` | 卡片上的文字 |
| `--muted` | `#2E2E2E` | 次要区域背景 |
| `--muted-foreground` | `#B8B9B6` | 次要文字/placeholder |
| `--primary` | `#FF8400` | 主色调（橙色），强调按钮 |
| `--primary-foreground` | `#111111` | 主色调上的文字 |
| `--secondary` | `#2E2E2E` | 次要交互区域 |
| `--secondary-foreground` | `#FFFFFF` | 次要区域文字 |
| `--border` | `#2E2E2E` | 边框 |
| `--input` | `#2E2E2E` | 输入框边框 |
| `--accent` | `#111111` | 强调背景 |
| `--accent-foreground` | `#F2F3F0` | 强调文字 |
| `--destructive` | `#FF5C33` | 破坏性操作 |
| `--ring` | `#666666` | 焦点环 |
| `--popover` | `#1A1A1A` | 弹出层背景 |
| `--popover-foreground` | `#FFFFFF` | 弹出层文字 |

#### 5.1.2 语义颜色 Token

| Token | Dark 值 | 用途 |
|---|---|---|
| `--color-success` | `#222924` | 成功背景 |
| `--color-success-foreground` | `#B6FFCE` | 成功文字/图标 |
| `--color-error` | `#24100B` | 错误背景 |
| `--color-error-foreground` | `#FF5C33` | 错误文字/图标 |
| `--color-warning` | `#291C0F` | 警告背景 |
| `--color-warning-foreground` | `#FF8400` | 警告文字/图标 |
| `--color-info` | `#222229` | 信息背景 |
| `--color-info-foreground` | `#B2B2FF` | 信息文字/图标 |

#### 5.1.3 字体 Token

| Token | 值 | 用途 |
|---|---|---|
| `--font-primary` | JetBrains Mono | 标题、按钮、状态文字 |
| `--font-secondary` | Geist | 描述、提示、辅助文字 |

#### 5.1.4 圆角 Token

| Token | 值 | 用途 |
|---|---|---|
| `--radius-m` | 16px | 面板圆角 |
| `--radius-pill` | 999px | 按钮胶囊形 |
| `--radius-none` | 0px | 无圆角 |

### 5.2 Typography 规格

| 用途 | 字体 | 大小 | 权重 | 颜色 |
|---|---|---|---|---|
| 面板标题 | JetBrains Mono | 20px | 600 | `--foreground` |
| 区段标签 | JetBrains Mono | 14px | 600 | `--foreground` |
| 选项/正文 | Geist | 14px | normal | `--foreground` |
| 推荐标签 | Geist | 14px | normal | `--primary` |
| 提示文字 | Geist | 12px | normal | `--muted-foreground` |
| 辅助小字 | Geist | 11px | normal | `--muted-foreground` |
| 状态反馈 | Geist | 12px | normal | 语义颜色 |
| 按钮文字 | JetBrains Mono | 14px | 500 | `--foreground` 或 `--primary-foreground` |
| Indicator 文字 | JetBrains Mono | 13px | 500 | `--foreground` |
| Indicator 计时 | JetBrains Mono | 13px | normal | `--muted-foreground` |
| History 按钮 | Geist | 12px | normal | `--foreground` |

### 5.3 卡片组件规格

所有配置区段共用的卡片样式：

| 属性 | 值 |
|---|---|
| 背景 | `--muted` |
| 边框 | `--border` 1px inside |
| 圆角 | 8px |
| 内边距 | 16px |
| 行间距 | 14px（radio group）/ 12px（其他） |

### 5.4 按钮规格

#### 5.4.1 主按钮（Save）

| 状态 | 背景 | 文字颜色 | 边框 | opacity |
|---|---|---|---|---|
| Enabled | `--primary` | `--primary-foreground` | 无 | 1.0 |
| Disabled | `--muted` | `--muted-foreground` | 无 | 0.4 |
| Hover | `--primary` (lighter) | `--primary-foreground` | 无 | 1.0 |

- 高度：40px，圆角 pill，内边距 10×16

#### 5.4.2 次按钮（Cancel / Stop / Restart）

| 状态 | 背景 | 文字颜色 | 边框 | opacity |
|---|---|---|---|---|
| Enabled | `--background` | `--foreground` | `--border` 1px | 1.0 |
| Disabled | `--muted` | `--muted-foreground` | 无 | 0.4 |
| Hover | `--secondary` | `--foreground` | `--border` 1px | 1.0 |

- 高度：40px，圆角 pill，内边距 10×16，阴影 blur 1.75

#### 5.4.3 强调按钮（Start — Stopped 状态）

- 与主按钮相同（`--primary` 背景）

### 5.5 Toast 通知组件

**通用规格**：
- 宽度：320px
- 背景：`--card`
- 边框：`--border` 1px inside
- 圆角：8px
- 阴影：blur 12, y-offset 4, `#00000030`
- 内边距：12×16
- 元素间距：10px

**位置**：屏幕右下角，距边缘 24px，从下往上堆叠

**自动消失**：2 秒后 fade out

**4 种变体**：

| 类型 | 左侧竖线颜色 | 图标 | 图标颜色 |
|---|---|---|---|
| Success | `--color-success-foreground` | `circle-check` | `--color-success-foreground` |
| Error | `--color-error-foreground` | `circle-x` | `--color-error-foreground` |
| Warning | `--color-warning-foreground` | `triangle-alert` | `--color-warning-foreground` |
| Info | `--color-info-foreground` | `info` | `--color-info-foreground` |

- 竖线：宽 3px，高 20px，圆角 2px
- 图标：16×16，Lucide icon set
- 消息文字：Geist 13px, `--foreground`

### 5.6 下拉框 (Select) 规格

| 属性 | 值 |
|---|---|
| 背景 | `--background` |
| 边框 | `--border` 1px inside |
| 圆角 | 6px |
| 内边距 | 8×12 |
| 文字 | Geist 14px, `--foreground` |
| 箭头 | `chevron-down` 14×14, `--muted-foreground` |
| 错误态边框 | `--color-error-foreground` |

### 5.7 Radio Button 规格

| 属性 | 值 |
|---|---|
| 尺寸 | 16×16 |
| 边框 | `--foreground` 1px inside |
| 背景（未选中） | `--background` |
| 内圆点（选中） | `--foreground` 填充，8×8 居中 |
| 禁用态 | 边框 `--muted-foreground`，opacity 0.4 |

---

## 6. 错误处理清单

本章列出所有可预见的错误场景及其处理方式。每个错误均需实现对应的用户可见反馈。

### 6.1 服务错误

| ID | 错误场景 | 处理方式 | 用户反馈 |
|---|---|---|---|
| SVC-001 | 服务启动超时 (>30s) | 终止启动流程，转入 FAILED | 状态显示 "Failed to start"，错误详情 "Start timeout. Please try again." |
| SVC-002 | 服务启动失败 — 模型文件缺失 | 转入 FAILED | "Failed to start"，详情 "Model file not found. Please check installation." |
| SVC-003 | 服务启动失败 — 端口/资源占用 | 转入 FAILED | "Failed to start"，详情 "Resource conflict. Another instance may be running." |
| SVC-004 | 服务运行时崩溃 | systemd 自动重启（最多 3 次） | Toast Error "Service crashed. Attempting restart..." |
| SVC-005 | 连续崩溃超过上限 | 转入 FAILED，不再自动重启 | "Failed to start"，详情 "Service crashed repeatedly. Please check logs." |
| SVC-006 | 停止超时 (>10s) | 强制 SIGKILL | Toast Warning "Service stop timed out. Force stopped." |
| SVC-007 | PID 文件残留 | 清理 PID 文件后正常启动 | 无用户反馈（静默处理） |
| SVC-008 | D-Bus 连接失败 | 重试 3 次，间隔 2s | Toast Error "Cannot connect to service. Please restart." |

### 6.2 模型错误

| ID | 错误场景 | 处理方式 | 用户反馈 |
|---|---|---|---|
| MDL-001 | 模型切换超时 (>60s) | 回退旧模型 | Toast Error "Model switch timed out. Reverted to {old}." |
| MDL-002 | 模型文件损坏 | 回退旧模型 | "Switch failed — reverted to {old}"，建议重新下载 |
| MDL-003 | 模型加载 OOM | 回退旧模型 | "Switch failed — insufficient memory. Reverted to {old}." |
| MDL-004 | 切换期间再次请求切换 | 忽略后续请求 | 无额外反馈（保持 Switching 状态） |
| MDL-005 | 模型文件下载失败 | 保留部分文件，提示重试 | Toast Error "Model download failed. Please check network." |

### 6.3 设备错误

| ID | 错误场景 | 处理方式 | 用户反馈 |
|---|---|---|---|
| DEV-001 | GPU→CPU 切换失败 | 回退 GPU | "Switch failed — reverted to GPU (CUDA)" |
| DEV-002 | CPU→GPU 切换失败 | 回退 CPU | "Switch failed — reverted to CPU" |
| DEV-003 | CUDA 运行时不可用 | 自动切换到 CPU，禁用 GPU 选项 | Toast Warning "CUDA unavailable. Switched to CPU." |
| DEV-004 | GPU 显存不足 | 回退 CPU | "Switch failed — GPU out of memory. Reverted to CPU." |
| DEV-005 | 系统无 CUDA | GPU 选项标记禁用 | GPU 行 opacity 0.4 + "CUDA not detected" 红色小字 |

### 6.4 音频错误

| ID | 错误场景 | 处理方式 | 用户反馈 |
|---|---|---|---|
| AUD-001 | 无音频输入设备 | 暂停录音功能 | 红色边框 + "No devices detected" + 下方提示 |
| AUD-002 | 当前设备被拔出 | 自动切换到默认设备 | Toast Warning "Audio device disconnected. Switched to {default}." |
| AUD-003 | 所有设备断开 | 暂停录音功能 | 同 AUD-001 |
| AUD-004 | 音频采集启动失败 | 取消本次录音 | Toast Error "Failed to start audio capture." |
| AUD-005 | 音频流中断 | 停止录音，转录已采集部分 | Toast Warning "Audio stream interrupted. Partial transcription." |
| AUD-006 | PulseAudio/PipeWire 不可用 | 服务启动失败 | "Failed to start"，详情 "Audio system not available." |

### 6.5 热键错误

| ID | 错误场景 | 处理方式 | 用户反馈 |
|---|---|---|---|
| HK-001 | 热键与系统快捷键冲突 | 拒绝设置，保留旧热键 | 红色 "✗ Conflict with System" + Conflict Modal |
| HK-002 | 热键与应用快捷键冲突 | 拒绝设置，保留旧热键 | 红色 "✗ Conflict with {app_name}" + Conflict Modal |
| HK-003 | 热键注册失败（X11/Wayland） | 保留旧热键 | Toast Error "Failed to register hotkey." |
| HK-004 | 键盘 grab 失败 | 退出捕获模式 | Toast Error "Cannot capture keyboard input." |
| HK-005 | 自定义输入非法（单键/超过 3 键） | 忽略输入，等待合法组合 | 提示文字保持 "Press a 2 or 3 key combination" |

### 6.6 配置错误

| ID | 错误场景 | 处理方式 | 用户反馈 |
|---|---|---|---|
| CFG-001 | 配置文件损坏/不可解析 | 使用默认配置 + 备份旧文件 | Toast Warning "Config file corrupted. Using defaults." |
| CFG-002 | 配置文件写入失败 | 保留内存中的配置 | Toast Error "Failed to save settings. Check disk permissions." |
| CFG-003 | 配置项值非法 | 忽略非法值，使用默认值 | 无用户反馈（静默修复） |
| CFG-004 | 历史记录文件损坏 | 清空历史，备份旧文件 | Toast Warning "History file corrupted. History cleared." |

### 6.7 转录错误

| ID | 错误场景 | 处理方式 | 用户反馈 |
|---|---|---|---|
| TRS-001 | 转录失败 — 引擎异常 | 丢弃本次音频 | Toast Error "Transcription failed." |
| TRS-002 | 转录结果为空 — 静音/噪音 | 不输出，不记录历史 | Toast Info "No speech detected." |
| TRS-003 | xdotool/ydotool 不可用 | 复制结果到剪贴板 | Toast Warning "Text input unavailable. Copied to clipboard." |
| TRS-004 | 剪贴板写入失败 | 仅记录到历史 | Toast Error "Failed to copy to clipboard." |

---

## 7. 国际化字符串表

### 7.1 完整 Key-Value 对照表

以下为所有 UI 可见文本的完整 i18n 映射。Key 使用点分命名空间。

#### 7.1.1 设置面板 — 框架

| Key | EN | ZH |
|---|---|---|
| `panel.title` | Voice Dictation Settings | 语音听写设置 |
| `panel.save` | Save | 保存 |
| `panel.cancel` | Cancel | 取消 |

#### 7.1.2 服务状态

| Key | EN | ZH |
|---|---|---|
| `server.label` | Server Status | 服务状态 |
| `server.running` | Running ({model}) | 运行中 ({model}) |
| `server.stopping` | Stopping... | 停止中... |
| `server.stopped` | Stopped | 已停止 |
| `server.starting` | Starting... | 启动中... |
| `server.restarting` | Restarting... | 重启中... |
| `server.failed` | Failed to start | 启动失败 |
| `server.btn_stop` | Stop | 停止 |
| `server.btn_start` | Start | 启动 |
| `server.btn_restart` | Restart | 重启 |
| `server.refresh_hint` | Floating indicator disappeared? | 浮动指示器消失了？ |
| `server.btn_refresh` | Refresh Indicator | 刷新指示器 |

#### 7.1.3 模型选择

| Key | EN | ZH |
|---|---|---|
| `model.label` | Model Selection | 模型选择 |
| `model.fast` | Fast (tiny) | 快速 (tiny) |
| `model.fast_desc` | Fastest response | 响应最快 |
| `model.balanced` | Balanced (small) | 均衡 (small) |
| `model.balanced_desc` | Recommended | 推荐 |
| `model.accurate` | Accurate (medium) | 精确 (medium) |
| `model.accurate_desc` | Most accurate | 最高精度 |
| `model.switching` | Switching... | 切换中... |
| `model.switch_complete` | Switch complete | 切换完成 |
| `model.switch_failed` | Switch failed | 切换失败 |
| `model.reverted` | reverted to {prev} | 已恢复为 {prev} |
| `model.retry` | Retry | 重试 |

#### 7.1.4 计算设备

| Key | EN | ZH |
|---|---|---|
| `device.label` | Device | 计算设备 |
| `device.gpu` | GPU (CUDA) | GPU (CUDA) |
| `device.cpu` | CPU | CPU |
| `device.cuda_not_detected` | CUDA not detected | 未检测到 CUDA |
| `device.auto_selected` | (auto-selected) | (自动选择) |
| `device.switching` | Switching... | 切换中... |
| `device.switch_complete` | Switch complete | 切换完成 |
| `device.switch_failed` | Switch failed | 切换失败 |

#### 7.1.5 音频输入

| Key | EN | ZH |
|---|---|---|
| `audio.label` | Audio Input | 音频输入 |
| `audio.auto` | Auto (System Default) | 自动 (系统默认) |
| `audio.no_devices` | No devices detected | 未检测到设备 |
| `audio.no_devices_hint` | Please connect an audio input device to use voice dictation. | 请连接音频输入设备以使用语音听写。 |
| `audio.disconnected` | Audio device disconnected. Switched to {default}. | 音频设备已断开。已切换到 {default}。 |

#### 7.1.6 快捷键

| Key | EN | ZH |
|---|---|---|
| `hotkey.label` | Hotkey | 快捷键 |
| `hotkey.mode` | Mode: | 模式: |
| `hotkey.mode_double` | Double Key | 双键 |
| `hotkey.mode_triple` | Triple Key | 三键 |
| `hotkey.key` | Key: | 按键: |
| `hotkey.custom` | Custom... | 自定义... |
| `hotkey.available` | ✓ Available | ✓ 可用 |
| `hotkey.conflict` | ✗ Conflict with {source} — reverted to {prev} | ✗ 与 {source} 冲突 — 已恢复为 {prev} |
| `hotkey.capture_placeholder` | Press your hotkey... | 按下快捷键... |
| `hotkey.capture_hint` | Press a 2 or 3 key combination. Original hotkey functions are suppressed. | 按下 2 或 3 键组合。原快捷键功能已被抑制。 |
| `hotkey.capture_cancel` | Cancel | 取消 |
| `hotkey.conflict_title` | Hotkey Conflict Detected | 检测到快捷键冲突 |
| `hotkey.conflict_body` | The combination {keys} is already used by {source}. Your hotkey has been kept as {prev}. | 组合键 {keys} 已被 {source} 占用。您的快捷键已保持为 {prev}。 |
| `hotkey.conflict_ok` | OK | 确定 |

#### 7.1.7 语言

| Key | EN | ZH |
|---|---|---|
| `lang.label` | Language | 语言 |
| `lang.interface` | Interface Language: | 界面语言： |
| `lang.en` | English | English |
| `lang.zh` | 中文 | 中文 |

#### 7.1.8 启动

| Key | EN | ZH |
|---|---|---|
| `startup.label` | Startup | 启动 |
| `startup.auto` | Start automatically on system boot | 系统启动时自动运行 |

#### 7.1.9 Indicator

| Key | EN | ZH |
|---|---|---|
| `indicator.idle` | Idle | 空闲 |
| `indicator.recording` | Recording | 录音中 |
| `indicator.history` | History | 历史记录 |
| `indicator.history_count` | {n} entries | {n} 条记录 |
| `indicator.history_empty` | No voice input history yet | 暂无语音输入历史 |

#### 7.1.10 Toast 消息

| Key | EN | ZH |
|---|---|---|
| `toast.settings_saved` | Settings saved | 设置已保存 |
| `toast.settings_save_failed` | Failed to save settings | 保存设置失败 |
| `toast.copied` | Copied to clipboard | 已复制到剪贴板 |
| `toast.copy_failed` | Failed to copy to clipboard | 复制到剪贴板失败 |
| `toast.indicator_refreshed` | Indicator refreshed | 指示器已刷新 |
| `toast.service_crashed` | Service crashed. Attempting restart... | 服务崩溃。正在尝试重启... |
| `toast.model_timeout` | Model switch timed out. Reverted to {prev}. | 模型切换超时。已恢复为 {prev}。 |
| `toast.device_disconnected` | Audio device disconnected. Switched to {default}. | 音频设备已断开。已切换到 {default}。 |
| `toast.no_speech` | No speech detected. | 未检测到语音。 |
| `toast.transcription_failed` | Transcription failed. | 转录失败。 |
| `toast.recording_timeout` | Recording stopped — maximum duration reached. | 录音已停止 — 已达到最大时长。 |
| `toast.hotkey_register_failed` | Failed to register hotkey. | 热键注册失败。 |
| `toast.config_corrupted` | Config file corrupted. Using defaults. | 配置文件损坏。已使用默认值。 |
| `toast.cuda_unavailable` | CUDA unavailable. Switched to CPU. | CUDA 不可用。已切换到 CPU。 |
| `toast.service_stop_timeout` | Service stop timed out. Force stopped. | 服务停止超时。已强制终止。 |
| `toast.audio_capture_failed` | Failed to start audio capture. | 音频采集启动失败。 |
| `toast.partial_transcription` | Audio stream interrupted. Partial transcription. | 音频流中断。部分转录。 |
| `toast.text_input_fallback` | Text input unavailable. Copied to clipboard. | 文字输入不可用。已复制到剪贴板。 |

---

## 8. 端到端测试用例

### 测试用例格式说明

每个用例包含：
- **ID**：模块缩写-序号（如 SVC-T001）
- **标题**：用一句话描述测试目的
- **前置条件**：测试开始前系统必须满足的条件
- **操作步骤**：逐步操作指令
- **预期结果**：每步或最终的可验证结果
- **验证点**：需要检查的关键断言

---

### 8.1 服务生命周期测试

#### SVC-T001: 正常启动服务

**前置条件**：服务处于 Stopped 状态，模型文件已存在

**操作步骤**：
1. 打开设置面板
2. 在 Server Status 区段点击 "Start" 按钮

**预期结果**：
1. 状态立即变为 "Starting..."（橙色圆点），按钮变为 disabled
2. 30 秒内状态变为 "Running (small)"（绿色圆点）
3. Stop 和 Restart 按钮变为 enabled
4. 屏幕底部出现 Indicator（显示 "Idle"）

**验证点**：
- [ ] 状态点颜色从红色(Stopped) → 橙色(Starting) → 绿色(Running)
- [ ] Starting 期间所有按钮 disabled
- [ ] Indicator 在且仅在 Running 后出现
- [ ] Server Status 文字中显示当前模型名

---

#### SVC-T002: 正常停止服务

**前置条件**：服务处于 Running 状态，Indicator 可见

**操作步骤**：
1. 在 Server Status 区段点击 "Stop" 按钮

**预期结果**：
1. 状态变为 "Stopping..."（橙色），Stop 按钮显示 spinner
2. 10 秒内状态变为 "Stopped"（红色），按钮变为 [Start]
3. Indicator 消失

**验证点**：
- [ ] Stopping 期间 Restart 按钮 disabled
- [ ] Indicator 在状态变为 Stopped 后消失
- [ ] 再次点击 Start 可正常启动

---

#### SVC-T003: 重启服务

**前置条件**：服务处于 Running 状态

**操作步骤**：
1. 点击 "Restart" 按钮

**预期结果**：
1. 状态变为 "Restarting..."（橙色），所有按钮 disabled
2. 先经历停止流程，再经历启动流程
3. 最终回到 "Running ({model})"（绿色）
4. Indicator 在整个过程中保持可见

**验证点**：
- [ ] Restarting 期间无法再次点击 Stop/Restart
- [ ] 最终状态与重启前一致
- [ ] Indicator 保持显示，未出现闪烁/消失

---

#### SVC-T004: 启动超时

**前置条件**：模型文件损坏导致加载卡住（模拟）

**操作步骤**：
1. 点击 "Start"

**预期结果**：
1. 状态显示 "Starting..."
2. 30 秒后状态变为 "Failed to start"（红色）
3. 错误详情显示超时信息
4. Restart 按钮可用

**验证点**：
- [ ] 精确在 30 秒超时
- [ ] 无 Indicator 显示
- [ ] 错误信息清晰可读

---

#### SVC-T005: 停止超时 — 强制终止

**前置条件**：服务处于 Running 状态，模拟进程无法正常退出

**操作步骤**：
1. 点击 "Stop"

**预期结果**：
1. 10 秒内若未完成 → 强制 SIGKILL
2. 状态最终变为 "Stopped"
3. Toast Warning "Service stop timed out. Force stopped."

**验证点**：
- [ ] 进程确实被终止（ps 查询无残留）
- [ ] PID 文件已清理
- [ ] Indicator 消失

---

#### SVC-T006: 服务崩溃自动重启

**前置条件**：服务处于 Running 状态

**操作步骤**：
1. 模拟服务进程被 kill -9

**预期结果**：
1. systemd 检测到进程退出
2. 5 秒后自动重启
3. Toast "Service crashed. Attempting restart..."
4. 若重启成功 → 回到 Running 状态

**验证点**：
- [ ] 自动重启间隔 ≥ 5 秒
- [ ] Indicator 短暂消失后重新出现
- [ ] 历史记录未丢失

---

#### SVC-T007: 连续崩溃超过上限

**前置条件**：服务处于 Running 状态

**操作步骤**：
1. 连续 3 次 kill -9 服务进程（每次等待自动重启后再 kill）

**预期结果**：
1. 前 2 次自动重启成功
2. 第 3 次崩溃后不再自动重启
3. 状态变为 "Failed to start"
4. 错误详情 "Service crashed repeatedly. Please check logs."

**验证点**：
- [ ] StartLimitBurst=3 生效
- [ ] 需要用户手动点击 Restart

---

#### SVC-T008: Refresh Indicator

**前置条件**：服务 Running，Indicator 可见

**操作步骤**：
1. 点击 "Refresh Indicator"

**预期结果**：
1. Indicator 先消失再出现（可能有短暂闪烁）
2. Toast "Indicator refreshed"
3. Indicator 状态为 Idle

**验证点**：
- [ ] 全程只有 1 个 Indicator
- [ ] 位置恢复到默认位置

---

#### SVC-T009: Refresh Indicator — 服务非 Running

**前置条件**：服务 Stopped

**操作步骤**：
1. 观察 Refresh Indicator 按钮

**预期结果**：
1. Refresh Indicator 按钮为 disabled 状态

**验证点**：
- [ ] 按钮不可点击
- [ ] 视觉呈 disabled 样式（opacity 0.4）

---

### 8.2 模型切换测试

#### MDL-T001: 正常切换模型

**前置条件**：服务 Running，当前模型 Balanced (small)

**操作步骤**：
1. 在 Model Selection 选择 "Accurate (medium)"
2. 等待切换完成

**预期结果**：
1. 选中项旁出现 spinner，描述变为 "Switching..."（橙色）
2. 其他选项 opacity 0.4
3. 切换完成后 spinner 变为 ✓，描述变为 "Switch complete"（绿色）
4. 2 秒后恢复正常显示
5. Server Status 更新为 "Running (medium)"

**验证点**：
- [ ] 切换期间无法选择其他模型
- [ ] Server Status 中的模型名同步更新
- [ ] 切换期间热键录音暂停

---

#### MDL-T002: 模型切换失败 — 自动回退

**前置条件**：服务 Running，当前 Balanced (small)，模拟 medium 模型文件损坏

**操作步骤**：
1. 选择 "Accurate (medium)"

**预期结果**：
1. 显示 "Switching..." + spinner
2. 加载失败后选中项旁显示 ✗，描述 "Switch failed"（红色）
3. 自动回退选择到 "Balanced (small)"
4. 回退项显示 "(reverted)" 标记
5. 显示 "Retry" 链接

**验证点**：
- [ ] 服务仍在 RUNNING 状态
- [ ] 旧模型仍可正常推理
- [ ] Server Status 仍显示 "Running (small)"

---

#### MDL-T003: 模型切换超时

**前置条件**：模拟模型加载耗时超过 60 秒

**操作步骤**：
1. 选择新模型

**预期结果**：
1. 60 秒后自动判定失败
2. 回退到旧模型
3. Toast "Model switch timed out. Reverted to {prev}."

**验证点**：
- [ ] 精确 60 秒超时
- [ ] 旧模型可用

---

#### MDL-T004: 切换中再次请求切换（防抖）

**前置条件**：正在切换模型（Switching 状态）

**操作步骤**：
1. 尝试点击其他模型选项

**预期结果**：
1. 点击无效（其他选项 disabled）
2. 当前切换流程继续

**验证点**：
- [ ] 不会触发第二次切换
- [ ] UI 保持 Switching 状态

---

### 8.3 设备切换测试

#### DEV-T001: GPU→CPU 正常切换

**前置条件**：CUDA 可用，当前使用 GPU

**操作步骤**：
1. 在 Device 区段选择 "CPU"

**预期结果**：
1. CPU 行显示 "Switching..." + spinner
2. 切换完成后显示 ✓ "Switch complete"
3. 2 秒后恢复正常

**验证点**：
- [ ] 模型成功迁移到 CPU
- [ ] 后续推理使用 CPU

---

#### DEV-T002: GPU 不可用 — 自动选择 CPU

**前置条件**：系统无 NVIDIA GPU / CUDA 未安装

**操作步骤**：
1. 启动服务并打开设置面板

**预期结果**：
1. GPU (CUDA) 行 opacity 0.4，radio disabled
2. 下方显示 "CUDA not detected"（红色小字）
3. CPU 行自动选中，显示 "(auto-selected)"

**验证点**：
- [ ] GPU radio 不可点击
- [ ] 配置文件中 device 为 "cpu"

---

#### DEV-T003: 设备切换失败

**前置条件**：模拟 GPU 显存不足

**操作步骤**：
1. 选择 "GPU (CUDA)"

**预期结果**：
1. "Switching..." 后显示 ✗ "Switch failed"
2. 自动回退到 CPU
3. 显示 "Retry" 链接

**验证点**：
- [ ] 服务仍可用
- [ ] 旧设备（CPU）仍在工作

---

### 8.4 音频输入测试

#### AUD-T001: 自动检测默认设备

**前置条件**：系统有至少 1 个音频输入设备

**操作步骤**：
1. 打开设置面板

**预期结果**：
1. Audio Input 下拉显示 "Auto (System Default)"
2. 下拉展开后列出所有检测到的设备

**验证点**：
- [ ] 默认选中 Auto
- [ ] 设备名称与 `pactl list sources` 输出一致

---

#### AUD-T002: 手动选择设备

**前置条件**：有多个音频输入设备

**操作步骤**：
1. 展开 Audio Input 下拉
2. 选择非默认设备

**预期结果**：
1. 下拉显示更新为所选设备名
2. 后续录音使用所选设备

**验证点**：
- [ ] 配置文件更新为所选设备 ID
- [ ] 实际音频采集使用正确设备

---

#### AUD-T003: 设备热插拔 — 插入新设备

**前置条件**：服务 Running

**操作步骤**：
1. 插入 USB 麦克风

**预期结果**：
1. Audio Input 下拉列表自动更新，包含新设备
2. 当前选择不变

**验证点**：
- [ ] 新设备出现在列表中
- [ ] 无 Toast 或额外打扰

---

#### AUD-T004: 设备热插拔 — 拔出当前设备

**前置条件**：当前选择为 USB 麦克风

**操作步骤**：
1. 拔出 USB 麦克风

**预期结果**：
1. 自动切换到系统默认设备
2. Toast Warning "Audio device disconnected. Switched to {default}."
3. 下拉更新为新设备

**验证点**：
- [ ] 录音功能不中断
- [ ] 配置自动更新

---

#### AUD-T005: 所有设备断开

**前置条件**：仅有 1 个音频设备

**操作步骤**：
1. 断开该设备

**预期结果**：
1. 下拉框边框变红
2. 显示 `triangle-alert` + "No devices detected"
3. 下方提示 "Please connect an audio input device..."
4. 热键按下无反应

**验证点**：
- [ ] 录音功能暂停
- [ ] 重新连接后自动恢复

---

### 8.5 热键测试

#### HK-T001: 预设热键选择

**前置条件**：服务 Running，当前热键 Ctrl+Alt+V

**操作步骤**：
1. Mode 下拉选择 "Double Key"
2. Key 下拉选择 "Ctrl+Space"

**预期结果**：
1. 反馈文字显示 "✓ Available"（绿色）
2. 新热键立即生效

**验证点**：
- [ ] 旧热键 Ctrl+Alt+V 不再触发录音
- [ ] 新热键 Ctrl+Space 可触发录音

---

#### HK-T002: 自定义按键捕获

**前置条件**：设置面板打开

**操作步骤**：
1. 点击 "Custom..." 按钮
2. 按下 Ctrl+Shift+R

**预期结果**：
1. Key 下拉变为输入框，边框高亮橙色
2. 出现 "Cancel" 链接和提示文字
3. 按下组合键后，输入框显示 "Ctrl+Shift+R"
4. 反馈显示 "✓ Available"，退出捕获模式

**验证点**：
- [ ] 捕获期间 Ctrl+Shift+R 不触发系统操作
- [ ] 输入框正确识别按键组合
- [ ] 退出后键盘 grab 释放

---

#### HK-T003: 自定义按键 — 冲突检测

**前置条件**：设置面板打开

**操作步骤**：
1. 点击 "Custom..."
2. 按下 Ctrl+Alt+Tab（假设与系统冲突）

**预期结果**：
1. 弹出 Hotkey Conflict Modal
2. Modal 显示 "The combination Ctrl+Alt+Tab is already used by System..."
3. 点击 OK 关闭 Modal
4. 热键恢复为之前的值
5. 反馈显示红色 "✗ Conflict with System — reverted to {prev}"

**验证点**：
- [ ] 按下 Ctrl+Alt+Tab 不触发系统窗口切换
- [ ] 旧热键仍然有效
- [ ] Modal 可通过 OK 按钮关闭
- [ ] 软件保持稳定

---

#### HK-T004: 自定义按键 — 取消

**前置条件**：捕获模式已激活

**操作步骤**：
1. 点击 "Cancel" 链接

**预期结果**：
1. 退出捕获模式
2. 输入框恢复为下拉框
3. 热键保持原值
4. 键盘 grab 释放

**验证点**：
- [ ] 无任何配置变更
- [ ] 系统快捷键恢复正常

---

#### HK-T005: 自定义按键 — 单键/超过 3 键

**前置条件**：捕获模式激活

**操作步骤**：
1. 仅按下单个键（如 "A"）
2. 按下 4 键组合

**预期结果**：
1. 单键：不触发任何操作，等待更多按键
2. 4 键：忽略第 4 个键，仅取前 3 个
3. 提示文字保持 "Press a 2 or 3 key combination"

**验证点**：
- [ ] 单键不被接受
- [ ] 组合键最多 3 个

---

#### HK-T006: 预设热键冲突

**前置条件**：预设中 Ctrl+Space 与输入法冲突

**操作步骤**：
1. Key 下拉选择 "Ctrl+Space"

**预期结果**：
1. 反馈显示红色 "✗ Conflict with {source} — reverted to {prev}"
2. 热键保持原值

**验证点**：
- [ ] 未实际注册冲突热键
- [ ] 旧热键有效

---

### 8.6 Indicator 测试

#### IND-T001: Indicator 随服务显示/隐藏

**前置条件**：服务 Stopped

**操作步骤**：
1. 确认屏幕无 Indicator
2. 启动服务
3. 确认 Indicator 出现
4. 停止服务
5. 确认 Indicator 消失

**预期结果**：如操作步骤所述

**验证点**：
- [ ] Stopped → 无 Indicator
- [ ] Running → 有 Indicator
- [ ] 状态转换一一对应

---

#### IND-T002: Indicator 单实例保证

**前置条件**：服务 Running

**操作步骤**：
1. 尝试通过命令行再次启动 bytecli-service

**预期结果**：
1. 检测到已有实例
2. 第二个实例不启动（或聚焦到已有 Indicator）
3. 屏幕上始终只有 1 个 Indicator

**验证点**：
- [ ] PID 文件机制正常
- [ ] 无重复 Indicator

---

#### IND-T003: Recording 状态计时

**前置条件**：服务 Running

**操作步骤**：
1. 按住热键 5 秒
2. 观察 Indicator

**预期结果**：
1. Indicator 切换到 Recording 状态（绿色圆点）
2. 计时器从 00:00 开始递增
3. 松开后 Indicator 恢复 Idle

**验证点**：
- [ ] 计时器精度 ±1 秒
- [ ] 松开后计时器重置

---

#### IND-T004: Hover 显示 History 按钮

**前置条件**：服务 Running，Indicator 显示 Idle

**操作步骤**：
1. 将光标移到 Indicator 上
2. 观察变化
3. 移开光标

**预期结果**：
1. 悬停后出现分隔线 + "History" 按钮
2. 移开后 History 按钮消失，恢复 Idle 样式

**验证点**：
- [ ] 悬停响应 < 100ms
- [ ] 移开后干净恢复

---

### 8.7 历史记录测试

#### HST-T001: 展开 History 面板 — 有记录

**前置条件**：已有 3 条以上历史记录

**操作步骤**：
1. 悬停 Indicator → 点击 History 按钮

**预期结果**：
1. 面板从 Indicator 上方弹出
2. 显示历史条目列表（文字截断 + 时间戳 + 复制图标）
3. 头部显示 "History" + 条目计数

**验证点**：
- [ ] 条目按时间倒序排列（最新在上）
- [ ] 文字过长时截断（不换行）
- [ ] 时间戳格式正确

---

#### HST-T002: 点击历史条目 — 复制到剪贴板

**前置条件**：History 面板展开，有条目

**操作步骤**：
1. 点击某条历史记录

**预期结果**：
1. 该条文字被复制到系统剪贴板
2. Toast "Copied to clipboard"
3. 在其他应用中 Ctrl+V 可粘贴该文字

**验证点**：
- [ ] 剪贴板内容正确
- [ ] Toast 显示并 2 秒后消失

---

#### HST-T003: History 面板 — 空状态

**前置条件**：无历史记录（首次使用或清空后）

**操作步骤**：
1. 悬停 → 点击 History

**预期结果**：
1. 面板显示空状态图标 + "No voice input history yet"
2. 面板高度 120px

**验证点**：
- [ ] 无错误提示
- [ ] 图标和文字居中

---

#### HST-T004: 光标移开收起面板

**前置条件**：History 面板已展开

**操作步骤**：
1. 将光标移出 Indicator 和 History 面板区域

**预期结果**：
1. History 面板收起
2. Indicator 恢复到 Idle-Default 样式

**验证点**：
- [ ] 收起动画流畅（或瞬间消失）
- [ ] 无残留元素

---

#### HST-T005: 历史记录上限淘汰

**前置条件**：history_max_entries 设为 50

**操作步骤**：
1. 执行 51 次语音录入

**预期结果**：
1. 历史记录文件中只保留最近 50 条
2. 最旧的第 1 条被删除

**验证点**：
- [ ] 文件大小不无限增长
- [ ] FIFO 淘汰正确

---

### 8.8 语言切换测试

#### LNG-T001: EN → ZH 切换

**前置条件**：当前语言 English

**操作步骤**：
1. 在 Language 区段选择 "中文"

**预期结果**：
1. 面板所有文字**瞬间**（<100ms）变为中文
2. "Voice Dictation Settings" → "语音听写设置"
3. "Server Status" → "服务状态"
4. 所有按钮、标签、描述均翻译
5. Indicator 文字同步变化（"Idle" → "空闲"）

**验证点**：
- [ ] 无遗漏的英文文字
- [ ] 无布局错乱（中文字符宽度不同）
- [ ] 配置文件 language 字段更新为 "zh"

---

#### LNG-T002: ZH → EN 切换

**前置条件**：当前语言中文

**操作步骤**：
1. 选择 "English"

**预期结果**：
1. 所有文字瞬间切回英文
2. Indicator 同步更新

**验证点**：
- [ ] 与 LNG-T001 对称验证

---

#### LNG-T003: 切换语言不影响其他配置

**前置条件**：已修改但未保存某些配置

**操作步骤**：
1. 修改模型选择
2. 切换语言

**预期结果**：
1. 语言切换成功
2. 模型选择的修改保留（未被重置）
3. Save/Cancel 仍为 enabled 状态（有待保存变更）

**验证点**：
- [ ] 语言切换独立于 Save 流程
- [ ] 其他未保存变更不丢失

---

### 8.9 开机自启动测试

#### AST-T001: 启用自启动

**前置条件**：自启动未启用

**操作步骤**：
1. 勾选 "Start automatically on system boot"
2. 点击 Save

**预期结果**：
1. `~/.config/autostart/bytecli.desktop` 文件被创建
2. 重启系统后服务自动启动
3. 登录桌面后 Indicator 自动显示

**验证点**：
- [ ] .desktop 文件内容正确
- [ ] 系统重启后验证 Indicator 存在
- [ ] 无需手动打开设置面板

---

#### AST-T002: 禁用自启动

**前置条件**：自启动已启用

**操作步骤**：
1. 取消勾选 "Start automatically on system boot"
2. 点击 Save

**预期结果**：
1. `~/.config/autostart/bytecli.desktop` 文件被删除
2. 重启系统后无 ByteCLI 进程

**验证点**：
- [ ] 文件确实被删除
- [ ] 重启后无服务运行

---

### 8.10 设置面板交互测试

#### SET-T001: 变更感知 — 无变更时按钮 disabled

**前置条件**：打开设置面板，无任何修改

**操作步骤**：
1. 观察 Save 和 Cancel 按钮

**预期结果**：
1. 两个按钮均为 disabled 状态（opacity 0.4）
2. 不可点击

**验证点**：
- [ ] 视觉符合设计稿 disabled 状态

---

#### SET-T002: 变更感知 — 有变更时按钮 enabled

**前置条件**：打开设置面板

**操作步骤**：
1. 修改任一配置项（如切换 hotkey mode）

**预期结果**：
1. Cancel 按钮变为 enabled（有边框）
2. Save 按钮变为 enabled（橙色）

**验证点**：
- [ ] 仅修改一个配置项即触发
- [ ] 视觉符合设计稿 enabled 状态

---

#### SET-T003: Cancel 恢复原值

**前置条件**：已修改多个配置项但未保存

**操作步骤**：
1. 点击 Cancel

**预期结果**：
1. 所有配置项恢复为打开面板时的值
2. Save/Cancel 恢复 disabled
3. 无 Toast

**验证点**：
- [ ] 所有修改被正确回退
- [ ] 配置文件未被修改

---

#### SET-T004: Save 保存并反馈

**前置条件**：已修改配置

**操作步骤**：
1. 点击 Save

**预期结果**：
1. 配置写入 config.json
2. Toast "Settings saved"
3. Save/Cancel 恢复 disabled
4. 对应操作被执行（如模型切换）

**验证点**：
- [ ] config.json 内容正确更新
- [ ] 服务端接收到新配置

---

#### SET-T005: 设置面板单实例

**前置条件**：设置面板已打开

**操作步骤**：
1. 双击桌面快捷方式再次打开

**预期结果**：
1. 不创建第二个窗口
2. 已有窗口被聚焦/置前

**验证点**：
- [ ] 任务栏中只有 1 个面板窗口

---

### 8.11 语音识别测试

#### ASR-T001: 中文语音识别

**前置条件**：服务 Running，模型 Balanced

**操作步骤**：
1. 按下热键开始录音
2. 说一段中文："今天天气很好"
3. 再次按下热键停止录音

**预期结果**：
1. 当前焦点窗口出现 "今天天气很好"
2. 历史记录新增该条目

**验证点**：
- [ ] 文字准确无误
- [ ] 无英文混入

---

#### ASR-T002: 英文语音识别

**前置条件**：同上

**操作步骤**：
1. 说 "The weather is great today"

**预期结果**：
1. 输出 "The weather is great today"

**验证点**：
- [ ] 大小写合理
- [ ] 无中文混入

---

#### ASR-T003: 中英混合语音识别

**前置条件**：同上

**操作步骤**：
1. 说 "我今天用了 Python 写了一个 script"

**预期结果**：
1. 输出包含中英文混合，如 "我今天用了Python写了一个script"

**验证点**：
- [ ] 中英文准确识别
- [ ] 无幻觉（不凭空生成文字）

---

#### ASR-T004: 静音 — 无语音

**前置条件**：服务 Running

**操作步骤**：
1. 按下热键开始录音
2. 等待 3 秒（不说话）
3. 再次按下热键停止录音

**预期结果**：
1. 无文字输出
2. Toast Info "No speech detected."
3. 不追加到历史记录

**验证点**：
- [ ] 不输出空白或噪声文字
- [ ] 无幻觉

---

#### ASR-T005: 误触 — 双击间隔 <0.3 秒

**前置条件**：服务 Running

**操作步骤**：
1. 按下热键开始录音
2. 立即再次按下热键（间隔 <0.3 秒）

**预期结果**：
1. 录音被丢弃（时间过短）
2. Indicator 恢复 Idle

**验证点**：
- [ ] 无任何副作用

---

#### ASR-T006: 长时间录音 — 自动停止

**前置条件**：服务 Running

**操作步骤**：
1. 按下热键开始录音，不再按下停止，等待超过 300 秒

**预期结果**：
1. 300 秒时自动停止录音
2. 已录制内容正常转录
3. Toast Warning "Recording stopped — maximum duration reached."

**验证点**：
- [ ] 精确在 300 秒停止
- [ ] 转录结果正确

---

### 8.12 鲁棒性测试

#### ROB-T001: 快速连续启停服务

**前置条件**：服务 Stopped

**操作步骤**：
1. 快速连续点击：Start → Stop → Start → Restart

**预期结果**：
1. 系统按照状态机规则处理
2. Starting 期间的 Stop 被忽略
3. 无崩溃、无死锁
4. 最终达到稳定状态

**验证点**：
- [ ] 所有非法转换被静默忽略
- [ ] 软件保持响应
- [ ] Indicator 状态一致

---

#### ROB-T002: 录音期间停止服务

**前置条件**：正在录音（录音进行中）

**操作步骤**：
1. 在设置面板点击 Stop

**预期结果**：
1. 当前录音被终止（丢弃或转录已录部分）
2. 服务正常停止
3. Indicator 消失

**验证点**：
- [ ] 无段错误
- [ ] 音频资源释放

---

#### ROB-T003: 模型切换期间停止服务

**前置条件**：正在切换模型

**操作步骤**：
1. 点击 Stop

**预期结果**：
1. 模型切换被取消
2. 服务正常进入 Stopping 流程
3. 最终 Stopped

**验证点**：
- [ ] 无残留进程
- [ ] 无模型文件锁

---

#### ROB-T004: 配置文件损坏恢复

**前置条件**：手动破坏 config.json（写入非法 JSON）

**操作步骤**：
1. 启动服务

**预期结果**：
1. 检测到配置损坏
2. 备份旧文件为 config.json.bak
3. 使用默认配置启动
4. Toast "Config file corrupted. Using defaults."

**验证点**：
- [ ] 服务正常启动
- [ ] 默认配置值正确
- [ ] 旧文件被备份（未删除）

---

#### ROB-T005: 历史文件损坏恢复

**前置条件**：手动破坏 history.json

**操作步骤**：
1. 悬停 Indicator → 点击 History

**预期结果**：
1. 检测到历史损坏
2. 清空历史，备份旧文件
3. Toast "History file corrupted. History cleared."
4. 显示空状态

**验证点**：
- [ ] 不崩溃
- [ ] 后续录音可正常追加新历史

---

#### ROB-T006: 磁盘空间不足

**前置条件**：磁盘剩余空间极少

**操作步骤**：
1. 尝试保存配置

**预期结果**：
1. 配置写入失败
2. Toast Error "Failed to save settings. Check disk permissions."
3. 内存中配置不受影响

**验证点**：
- [ ] 不写入半截文件
- [ ] 旧配置文件完好

---

#### ROB-T007: 并发 D-Bus 调用

**前置条件**：服务 Running

**操作步骤**：
1. 从多个客户端同时发送 SwitchModel + SwitchDevice

**预期结果**：
1. 请求被序列化处理
2. 先到先处理，后到的排队或拒绝
3. 无竞态条件

**验证点**：
- [ ] 无崩溃
- [ ] 最终状态一致

---

#### ROB-T008: 超大转录文本

**前置条件**：服务 Running

**操作步骤**：
1. 连续说话 5 分钟（最大时长）

**预期结果**：
1. 转录完成（可能需要较长推理时间）
2. 文字正确输入到焦点窗口
3. 历史记录正确存储

**验证点**：
- [ ] 无内存泄漏
- [ ] 无截断

---

### 8.13 安装与桌面集成测试

#### INS-T001: 安装后桌面快捷方式

**前置条件**：完成软件安装

**操作步骤**：
1. 在桌面或应用菜单查找 ByteCLI

**预期结果**：
1. 存在 "ByteCLI Settings" 快捷方式
2. 双击打开设置面板

**验证点**：
- [ ] .desktop 文件存在于正确路径
- [ ] 图标正常显示
- [ ] 双击可正常启动

---

#### INS-T002: 卸载清理

**前置条件**：软件已安装并使用过

**操作步骤**：
1. 执行卸载命令

**预期结果**：
1. 服务停止
2. Indicator 消失
3. 自启动入口删除
4. 可选：保留用户数据（config, history, models）

**验证点**：
- [ ] 无残留进程
- [ ] 无残留自启动项

---

## 附录 A：设计稿 Frame 索引

| Frame 名称 | 设计文件 ID | 说明 |
|---|---|---|
| Voice Indicator States | `hRSW5` | 暗色指示器 4 态 + History 面板 |
| Settings Panel (EN) | `dx58M` | 英文设置面板（480×1150） |
| Settings Panel (ZH) | `scSfJ` | 中文设置面板（480×1180） |
| Reusable Components | `55ieU` | Toast 4 变体 + 冲突弹窗 |
| Server Status States | `VkHOY` | 服务状态 5 变体 |
| Model/Device Switching | `lz29U` | 模型/设备切换 6 过渡态 |
| Hotkey Interaction | `EPmHp` | 热键冲突 + 捕获模式 |
| Edge Case States | `ZwEIM` | GPU 不可用 + 无音频 + 按钮状态 |
| Chinese Indicators | `h69ET` | 中文指示器 3 态 |

---

## 附录 B：测试用例覆盖矩阵

| 模块 | 正常流程 | 失败/回退 | 超时 | 边界/异常 | 并发/鲁棒 |
|---|---|---|---|---|---|
| 服务生命周期 | SVC-T001~T003, T008 | SVC-T004, T006 | SVC-T004, T005 | SVC-T007, T009 | ROB-T001~T003 |
| 模型切换 | MDL-T001 | MDL-T002 | MDL-T003 | MDL-T004 | ROB-T007 |
| 设备切换 | DEV-T001 | DEV-T003 | — | DEV-T002 | ROB-T007 |
| 音频输入 | AUD-T001~T003 | — | — | AUD-T004, T005 | — |
| 热键 | HK-T001, T002 | HK-T003, T006 | — | HK-T004, T005 | — |
| Indicator | IND-T001, T003, T004 | — | — | IND-T002 | ROB-T002 |
| 历史记录 | HST-T001, T002 | — | — | HST-T003, T005 | HST-T004 |
| 语言切换 | LNG-T001, T002 | — | — | LNG-T003 | — |
| 自启动 | AST-T001, T002 | — | — | — | — |
| 设置面板 | SET-T001~T005 | SET-T004 (fail) | — | — | — |
| 语音识别 | ASR-T001~T003 | ASR-T004 | ASR-T006 | ASR-T005 | ROB-T008 |
| 安装集成 | INS-T001, T002 | — | — | — | — |
| 配置鲁棒性 | — | ROB-T004, T005 | — | ROB-T006 | — |

**总计：57 个测试用例**，覆盖 13 个模块，涵盖正常流程、失败回退、超时处理、边界异常、并发鲁棒五个维度。

---

*文档结束*
