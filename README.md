# 咕咕嘎嘎 — Claude Code Desktop Pet

一只会随着 Claude Code 工作状态变化表情的桌面企鹅宠物。

## 效果预览

企鹅会根据 Claude Code 的当前阶段自动切换动画：

| 阶段 | 触发条件 | 表现 |
|------|---------|------|
| `idle` | 会话开始 / 闲置超时 | 缓慢眨眼、微微晃动 |
| `question` | 用户发送消息 | 歪头、冒出问号 |
| `reading` | 读取文件 (Read/Grep/Glob) | 捧书阅读 |
| `thinking` | 工具调用间隙 / 推理中 | 托腮思考、旋转圆点 |
| `writing` | 编辑文件 (Edit/Write) | 敲键盘 |
| `executing` | 执行命令 (Bash) | 飞速奔跑 + 旋转光环 |
| `done` | 任务完成 (Stop) | 开心跳起、星星环绕 |
| `sleep` | 闲置 20 秒后自动触发 | 趴枕头睡觉、飘 Zzz |
| `angry` | 快速连点 4 次 (1.35 秒内) | 怒气爆发、青筋、颤抖 |
| `dragged` | 鼠标拖拽中 | 被拎起、慌张表情 |

## 安装与运行

### 环境要求

- Python 3.11+
- Windows / macOS / Linux

### 安装依赖

```bash
pip install -r requirements.txt
```

### 生成精灵图

```bash
python pet/generate_sprites.py
```

> 如果 `assets/` 目录下有 AI 生成的基础图 (`aigen-*.png`)，会基于它们生成；否则自动使用程序化绘制的企鹅精灵。

### 启动桌宠

```bash
python pet_app.py
```

一键脚本（自动创建 `.venv`、安装依赖、生成精灵图）：

- **macOS**：双击仓库根目录的 `start-pet.command`，或运行 `./scripts/macos/start-pet.sh`
- **Windows**：双击或运行 `scripts\windows\start-pet.cmd`

企鹅会出现在屏幕右下角，始终置顶。

### 配置 Claude Code Hook

右键点击企鹅 → **配置Hook**，自动将 Hook 写入 `~/.claude/settings.json`。重启 Claude Code 即可生效。

也可手动配置，参考模板见 `pet_app.py` 中的 `PET_HOOKS_TEMPLATE`。

## 交互

| 操作 | 效果 |
|------|------|
| 拖拽企鹅 | 移动到任意位置，带摇摆物理效果 |
| 单击企鹅 | 唤醒（如果在睡觉） |
| 快速连点 4 次 | 触发愤怒动画 |
| 右键企鹅 | 弹出菜单（配置Hook / 退出） |

## 环境变量

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `DESKTOP_PET_HOST` | `127.0.0.1` | IPC 监听地址 |
| `DESKTOP_PET_PORT` | `19847` | IPC 监听端口 |
| `DESKTOP_PET_SILENCE_IDLE_MS` | `25000` | 活跃阶段无信号后回 idle 的等待时间（毫秒），设 0 禁用 |
| `DESKTOP_PET_IDLE_SLEEP_MS` | `20000` | idle 后进入 sleep 的等待时间（毫秒），设 0 禁用 |
| `PET_DEBUG` | `0` | 设为 1 显示红色调试边框 |

## 测试

启动桌宠后，运行测试脚本验证阶段切换：

```bash
# 正常速度
python scripts/test-thinking-cycle.py

# 快速模式
python scripts/test-thinking-cycle.py --fast
```

## 项目结构

```
├── pet_app.py                  # 主入口
├── pet/
│   ├── window.py               # 透明置顶窗口 + 拖拽 + 摇摆物理
│   ├── animation.py            # 状态机 + 帧控制器
│   ├── ipc.py                  # TCP IPC 监听线程
│   ├── procedural_mascot.py    # 程序化企鹅绘制（无需外部素材）
│   ├── generate_sprites.py     # 精灵图生成器
│   └── sprites/                # 精灵帧 PNG
│       ├── idle/ question/ reading/ thinking/
│       ├── writing/ executing/ done/
│       ├── sleep/ angry/ dragged/
├── scripts/
│   ├── macos/
│   │   ├── start-pet.sh        # macOS 一键启动（chmod +x）
│   │   └── start-pet.command   # Finder 双击（同目录）
│   ├── windows/
│   │   ├── start-pet.ps1       # Windows 一键启动（PowerShell）
│   │   └── start-pet.cmd       # cmd / 资源管理器双击入口
│   ├── notify-pet.py           # Hook 通知脚本
│   └── test-thinking-cycle.py  # 阶段切换测试
├── start-pet.command           # macOS：仓库根目录双击 → macos/start-pet.sh
└── requirements.txt
```

## 技术栈

- **GUI:** PySide6
- **IPC:** TCP localhost (跨平台)
- **绘图:** Pillow（程序化精灵生成）
