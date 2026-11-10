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
| `sleep` | idle 持续 20 秒后自动触发 | 趴枕头睡觉、飘 Zzz |
| `waddle` | 睡眠 20 秒后自动触发 | 摇摇晃晃走到屏幕中央，中途随机停顿 |
| `angry` | 快速连点 4 次 (1.35 秒内) | 怒气爆发、青筋、颤抖 |
| `dragged` | 鼠标拖拽中 | 被拎起、摇摆旋转 |

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

### 大肥鱼番茄时钟

右键桌宠 → **番茄时钟 · 专注统计**，点击「开始专注 · 25 分钟」。

- **专注**：大肥鱼用膝上的小电脑轻敲键盘，配合自然眨眼和呼吸，宠物旁持续显示倒计时；点击倒计时可重新打开面板。
- **到时提醒**：大肥鱼握着小手铃，轻摇两下后停顿，并播放系统提示音（是否出声取决于系统声音设置）。点击「开始休息 · 5 分钟」进入休息。
- **休息**：大肥鱼双手捧杯，小幅抬手，间歇闭眼伸懒腰；休息结束后可手动开始下一轮，不会自动累计无人参与的番茄。
- **暂停 / 继续**：关闭面板继续计时；「结束并保留时长」结束当前一轮，保留已专注的时间。
- **起来活动**：实际专注累计满 120 分钟，宠物会主动提醒。暂停、5 分钟休息不计入这 120 分钟；点击「我已起来活动」后重新累计。

统计面板显示今日专注时间、今日完成番茄数、连续专注天数、本周工作时间及每日柱图。未完成一轮的实际专注时间也会保留；完整专注 25 分钟才记为一个番茄。每天至少完成一个番茄计为专注一天；今天尚未完成时显示截至昨天的连续天数。本周按本地日期的周一至周日统计，跨午夜的专注时间分到各自日期。

数据保存在 `~/.desktop-pet/pomodoro.json`，可用 `DESKTOP_PET_POMODORO_PATH` 指定其他位置。运行中每 5 秒保存一次，正常退出会保存并暂停；重新启动时手动继续，离线时间不计入。异常退出最多丢失最近约 5 秒的记录。保存失败会在面板提示；无法读取的原始记录会保留，本次会话暂时只在内存中计时。

番茄计时与 Claude Hook 独立运行；拖拽时保留原来的拎起动作，松手后恢复番茄状态。角色动作适用于大肥鱼，切换企鹅时计时和统计仍继续。

番茄姿势使用与角色一致的透明插画，手和电脑、杯子、手铃一同参与网格动画。暂停保留当前画面，继续时接着播放。可查看 [调整前后](docs/pomodoro/before-after.png) 和 [实际动画预览](docs/pomodoro/animation.mp4)。导出实际动画与浅色/深色背景预览：

```bash
python scripts/preview-pomodoro.py --export-dir preview/pomodoro
```

导出不连接 IPC、不读写专注数据；生成 `overview.png`、四种姿势 PNG 和 16 秒的 `animation.gif`。可用 `--seconds`、`--fps` 调整长度与帧率。

### 配置 Claude Code Hook

右键点击企鹅 → **配置Hook**，自动将 Hook 写入 `~/.claude/settings.json`。重启 Claude Code 即可生效。

也可手动配置，参考模板见 `pet_app.py` 中的 `PET_HOOKS_TEMPLATE`。

### 配置权限审批桥接 (可选)

桌宠可作为 Claude Code 权限审批面板，将 CLI 权限弹窗以图形化方式展示：

1. 启动桌宠（确保能收到 IPC 信号）
2. 右键点击企鹅 → **配置Hook**，确保 pet hooks 已写入
3. 在 `~/.claude/settings.json` 的 hooks 中手动添加：

```json
"PermissionRequest": [
  {"command": "python /path/to/desktop-pet/scripts/permission-hook.py"}
]
```

> 请将路径替换为实际仓库路径。

之后每次 Claude Code 弹出权限审批时，企鹅旁会出现带按钮的提问面板（Yes / Yes, allow all / No）。

### 从外部脚本发起提问

```bash
# 以参数传入 JSON：
python scripts/ask-via-pet.py '{"text":"请选择一个","options":[{"label":"A","description":"选项A"},{"label":"B"}]}'

# 或通过管道：
echo '{"text":"请选择一个","options":[...]}' | python scripts/ask-via-pet.py
```

## 交互

| 操作 | 效果 |
|------|------|
| 拖拽企鹅 | 移动到任意位置，带摇摆物理效果 |
| 单击企鹅 | 唤醒（如果在睡觉或 waddle） |
| 快速连点 4 次 | 触发愤怒动画 |
| 右键企鹅 | 弹出自定义面板（配置Hook / 退出） |
| 三击宠物肚子（下方 45% 区域，1.5 秒内） | 大肥鱼随机回复「鲸鲸」「deep deep」「seek seek」「别吵别吵」，连续两次不重复；企鹅回复「咕咕嘎嘎」 |

连点回复采用角色配色的圆润对话气泡：大肥鱼为蓝白渐变、深蓝文字和台词对应的小插画，企鹅为暖白配色。气泡带指向宠物的小尾巴，轻轻弹出，约 2.4 秒后淡出；跟随宠物移动并避开屏幕边缘，不抢焦点、不拦截鼠标。切换角色会清除当前气泡和未完成的连点。

运行 `python scripts/preview-dialogue.py --output docs/interaction/replies.png` 可导出真实控件在浅色 / 深色桌面上的预览。

## 环境变量

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `DESKTOP_PET_HOST` | `127.0.0.1` | IPC 监听地址 |
| `DESKTOP_PET_PORT` | `19847` | IPC 监听端口 |
| `DESKTOP_PET_SILENCE_IDLE_MS` | `25000` | 活跃阶段无信号后回 idle 的等待时间（毫秒），设 0 禁用 |
| `DESKTOP_PET_IDLE_SLEEP_MS` | `20000` | idle 后进入 sleep 的等待时间（毫秒），设 0 禁用 |
| `DESKTOP_PET_SLEEP_WADDLE_MS` | `20000` | sleep 后进入 waddle（走向中央）的等待时间（毫秒），设 0 禁用 |
| `PET_DEBUG` | `0` | 设为 1 显示红色调试边框 |

## 测试

启动桌宠后，运行测试脚本验证阶段切换：

```bash
# 正常速度
python scripts/test-thinking-cycle.py

# 快速模式
python scripts/test-thinking-cycle.py --fast
```

Windows 可视化演示：

```powershell
.\scripts\demo-pet.ps1 -Seconds 3
```

## 项目结构

```
├── pet_app.py                  # 主入口
├── pet/
│   ├── window.py               # 透明置顶窗口 + 拖拽 + 摇摆物理 + 提问面板 + waddle
│   ├── animation.py            # 状态机 + 帧控制器
│   ├── ipc.py                  # TCP IPC 双向协议（阶段信号 + 问答）
│   ├── procedural_mascot.py    # 程序化企鹅绘制（无需外部素材）
│   ├── generate_sprites.py     # 精灵图生成器
│   └── sprites/                # 精灵帧 PNG
│       ├── idle/ question/ reading/ thinking/
│       ├── writing/ executing/ done/
│       ├── sleep/ angry/ dragged/ waddle/
├── scripts/
│   ├── macos/
│   │   ├── start-pet.sh        # macOS 一键启动
│   │   └── start-pet.command   # Finder 双击（同目录）
│   ├── windows/
│   │   ├── start-pet.ps1       # Windows 一键启动（PowerShell）
│   │   └── start-pet.cmd       # cmd / 资源管理器双击入口
│   ├── notify-pet.py           # Hook 通知脚本
│   ├── ask-via-pet.py          # 外部脚本提问 CLI
│   ├── permission-hook.py      # Claude Code PermissionRequest 桥接
│   ├── demo-pet.ps1            # Windows 可视化阶段演示
│   └── test-thinking-cycle.py  # 阶段切换测试
├── start-pet.command           # macOS：仓库根目录双击 → macos/start-pet.sh
└── requirements.txt
```

## 技术栈

- **GUI:** PySide6
- **IPC:** TCP localhost（双向，支持 JSON 问答协议）
- **绘图:** Pillow（程序化精灵生成）
- **跨平台透明:** macOS NSWindow shadow 剥离 + Windows DWM 装饰移除
