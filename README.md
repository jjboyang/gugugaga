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

### 大肥鱼工作模式

右键桌宠 → **开启工作模式**。大肥鱼跟着你的按键打字，跟着滚轮滑动小屏幕，停止输入后回到待机。侧边气泡持续显示本轮操作次数，每次系统按键、鼠标按下和滚轮事件各记 1 次。右键选择「结束工作模式」即可停止，再次开启从 0 开始。

工作模式与番茄时钟可各自开启和结束。两者同时开启时，大肥鱼显示工作动作，番茄时钟继续倒计时和到时提示。

全局输入支持 Windows、macOS 和 Linux X11。macOS 需在「系统设置 → 隐私与安全性 → 输入监控」授权启动桌宠的应用，再重启桌宠。输入监听不可用时，将鼠标移到工作模式气泡上可查看原因。

### 大肥鱼番茄时钟

右键桌宠 → **番茄时钟 · 专注统计**，点击「开始专注 · 25 分钟」。

- **专注**：大肥鱼用膝上的小电脑轻敲键盘，宠物旁的气泡持续显示倒计时。点击气泡可重新打开面板。
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

### 大肥鱼的探索日记

右键大肥鱼，打开「她在干嘛」→「Agent 连接」。添加 **OpenAI Responses · 网页搜索**，填入支持网页搜索的模型和 API Key，再点「去逛一会儿」。探索记录会显示大肥鱼的想法、她读到的内容和来源链接。她有了想接着查的问题，会留到下一次。

要让她自行探索，为连接勾选「允许大肥鱼在后台自主调用」，并保存「自动探索」设置。桌宠运行时，约十分钟没有和她互动，她就可以自行探索。两轮后台探索至少间隔十五分钟。每日上限按已发起的探索轮次计数，默认三轮，手动探索也计入。她会在你点她时分享新发现。最近十四天内，如果有三天你在结束工作模式后五分钟内点过她，她也会在忙完后偶尔主动分享，每天最多一次。

探索记录和连接设置保存在 `~/.desktop-pet/exploration.sqlite3`。可以用 `DESKTOP_PET_EXPLORATION_PATH` 指定其他位置。API Key 保存到系统钥匙串，带 Key 的连接需要可用的系统凭据服务。

#### 用 DeepSeek 逛你选的网站

在「Agent 连接」添加 **DeepSeek · 网站探索**，填入 [DeepSeek 开放平台](https://platform.deepseek.com/api_keys) 的 API Key。原有的 DeepSeek 连接和 Key 可以直接继续使用。打开「探索网站」，添加你想让她先逛的域名或网址。B 站是初始预设，可以移除。每轮从列表选一个网站，用 DeepSeek 搜索该站的公开内容，尝试读取一条结果，再让 `deepseek-flash` 从候选里选一条、写一句感想，一轮最多三次 API 请求。

如果摘要或网页里出现了她有兴趣的站外链接，她可以把这个网站和发现来源记下来。她会在后续探索里回访，也可以从「她自己发现的」列表打开当时的来源或移除网站。移除的网站可以手动重新添加。视频笔记根据搜索拿到的资料生成。点「打开来源」可以在浏览器播放原视频。

#### 接入自定义 Agent

如果你在 Dify 发布了新版 Agent，选择「Dify Agent」，填写应用的 API Key、以 `/chat-messages` 结尾的 API 地址，以及网页或视频能力。Agent 要有对应的搜索工具，应用的输入变量可以留空。大肥鱼会把这次想找的内容交给它，并读取流式回复里的最终结果。

在「Agent 连接」选择「自定义 Agent · HTTP JSON」，填写能接收以下格式的服务地址、Agent 标识和网页或视频能力。现有平台的 API 可以通过一个轻量的服务转换为此格式。桌宠使用 HTTP POST，填了 API Key 时会带上 Bearer 凭据。

```json
{
  "agent": "video-finder",
  "capability": "video",
  "topic": "海鸟怎样停在栏杆上",
  "previous": {},
  "locale": "zh-CN"
}
```

`previous` 带上一次探索的 `url` 和 `reaction`，首次或更换话题时为空。服务返回一条实际找到的内容：

```json
{
  "url": "https://example.org/coast/video",
  "title": "一段海岸影像",
  "evidence_kind": "metadata",
  "observation": "简介提到海鸟停在栏杆上。",
  "reaction": "我想看看它在大风里的动作。",
  "next_topic": "海鸟在大风里是怎么站稳的"
}
```

`evidence_kind` 可填 `article`（网页正文）、`metadata`（标题或简介）或 `transcript`（可读取的字幕或转写）。视频能力用后两种。`next_topic` 为空时，大肥鱼可以去找新的话题。

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
