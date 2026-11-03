# 大肥鱼原图骨骼动画版

本版在原有 `pet/characters/dafeiyu/atlas.png` 上建立共享顶点网格和骨骼权重，连续控制呼吸、头部、侧发、手脚及拖动回弹。待机坐姿、睡觉、眨眼、行走、蹦跳和生气使用原素材；提起与敲屏幕分别使用保留角色形象的 `rig/pickup.png` 和 `rig/knock.png`。原图集不被覆盖。

这是使用 PySide6 实现的 2D 网格骨骼蒙皮，不需要商用 Live2D 或 Spine 运行库。动作以原图可承受的轻微变形为主；大幅转身等需要新视角素材。

## 运行与更新

安装 Python 3.10 或更新版本，在项目根目录运行：

```bash
python -m pip install -r requirements.txt
python pet_app.py
```

Windows 也可沿用 `scripts/windows/start-pet.cmd`。默认启动大肥鱼，右键菜单仍可切换企鹅。企鹅保留原精灵动画。

完整项目包可解压到新目录直接运行。若更新已有项目，先完全退出桌宠，再按相同目录结构替换或添加：

- `pet_app.py`、`pet/window.py`
- `pet/animation.py`（包含原图 atlas 加载支持）、`pet/rig_motion.py`、`pet/rig_animator.py`、`pet/rig_mesh.py`
- `pet/idle_behavior.py`、`pet/attention_renderer.py`
- `pet/characters/dafeiyu/rig/` 整个目录，包括 `manifest.json`、`pickup.png` 和 `knock.png`
- 本包的 `pet/characters/dafeiyu/atlas.png` 和 `atlas.json`（原项目缺少这两个文件时必须复制）。

可另复制 `scripts/preview-rig.py` 以使用预览工具。无需运行推送脚本或发布 GitHub。

原地待机、睡觉、点击唤醒、手动拖动、角色切换及 IPC/Hook 保留。原来闲置后自动走向屏幕中央的逻辑仍关闭；新的待机走动按已确认的范围，只在当前位置附近左右约 80 像素内往返。

拖拽开始时立即显示手指捏住头饰、双手和双脚自然下垂的提起姿势，缓慢拖动或按住不动时也保持该姿势。手指位置固定，身体绕头顶抓点随移动摆动；停下后自然摆回，松手恢复当前状态并保留短暂惯性。睡觉使用原素材中低头、平闭眼和 ZZZ 的真正睡姿，叠加缓慢呼吸；普通眨眼仍使用待机的闭眼素材。

快速连续点击 4 次可触发生气：使用原图的生气眉眼、撅嘴、红色怒气符号和叉腰站姿，伴随交替跺脚、晃头等动作。大肥鱼在约 180 毫秒开场后保持 3500 毫秒，总计约 3.7 秒，再自动恢复；生气时不会叠加普通眨眼的开心笑眼。企鹅沿用原来的动作和持续时间。

## 随机待机动作

大肥鱼在没有点击、拖拽或工作事件打断的情况下，首次闲置 8～12 秒后随机选择一个小动作。每个动作持续 4～6 秒，完成后间隔 10～18 秒再随机选择，避免连续重复同一种动作：

- 附近走动：在本次动作起点左右约 80 像素内来回走，完整走完会返回起点，并受屏幕可用边界限制。
- 敲敲屏幕：朝前轻敲几下，配合短暂的接触涟漪。
- 蹦跳：连续蹦几下，包含起跳前压身和落地缓冲。

点击、拖拽、切换角色、打开菜单或收到工作状态时会打断小动作。走动被打断后停在当前位置，避免点击时突然跳回旧起点。睡觉、提问、阅读、书写、执行或生气时不随机播放待机动作。

大肥鱼默认在没有互动约 120 秒后入睡，让待机动作有时间播放；显式设置的 `DESKTOP_PET_IDLE_SLEEP_MS` 环境变量优先，设为 `0` 可关闭自动入睡。企鹅保留原来的待机与睡眠时序。

## 离线预览与导出

```bash
python scripts/preview-rig.py
```

预览窗口可切换 11 种状态和走动、敲屏幕、蹦跳 3 种待机动作，可暂停、重置、减小动作幅度，并点击角色查看回弹。拖动状态会模拟摇摆，待机动作以 4.8 秒循环；重置会回到本轮动作的开头。预览器不连接 IPC，不更改真实桌宠位置，也不读写用户桌宠配置。

预览窗口与 PNG 导出仅展示走路步态；实际运行桌宠时才会在附近左右移动。`--action` 仅可与 `--phase idle` 搭配，省略 `--phase` 时默认即为 `idle`。

导出一个状态的透明 PNG 动画序列，以及全部状态的总览：

```bash
python scripts/preview-rig.py --export-dir preview/idle --phase idle --seconds 4 --fps 30
python scripts/preview-rig.py --export-dir preview/dragged --phase dragged --seconds 4 --fps 30
python scripts/preview-rig.py --export-dir preview/sleep --phase sleep --seconds 4 --fps 30
python scripts/preview-rig.py --export-dir preview/done --phase done --seconds 4 --fps 30
python scripts/preview-rig.py --export-dir preview/walk --action walk --seconds 5 --fps 30
python scripts/preview-rig.py --export-dir preview/knock --action knock --seconds 5 --fps 30
python scripts/preview-rig.py --export-dir preview/hop --action hop --seconds 5 --fps 30
python scripts/preview-rig.py --export-dir preview/angry --phase angry --seconds 4 --fps 30
```

每次导出所选状态或动作的 `frame_0000.png` 等文件和包含全部 14 种预览项目的 `contact-sheet.png`，默认 120 帧，自动使用 Qt 无窗口模式。动作会在 `--seconds` 指定的时长内播放一轮。重复使用同一输出目录会替换其中旧的 `frame_XXXX.png`，建议每个状态或动作使用独立目录。

## 调整动画

`pet/characters/dafeiyu/rig/manifest.json` 的 `mesh_columns` 和 `mesh_rows` 控制网格密度，范围 4～32；数值越大，渲染成本越高。原图裁切、对齐比例和锚点保存在上一级 `atlas.json`，不要随意改变，以免角色尺寸或位置偏移。

`pet/rig_mesh.py` 的 `pivots` 定义原坐姿上各骨骼的锚点，`_weights_at()` 定义网格受骨骼影响的范围。`pet/rig_motion.py` 控制动作和弹簧过渡，`pet/rig_animator.py` 负责原图表情、道具与定时渲染。修改后可用预览器检查，不需要改动 IPC 或真实桌宠配置。

`pet/idle_behavior.py` 控制随机选择、等待间隔和附近走动的路径；`pet/attention_renderer.py` 选择动作素材并绘制敲屏幕的轻微接触涟漪。

提起姿势的 `pickup_image`、`suspension_anchor`（512 画布中的抓点）和 `pickup_hand_polygons`（固定手指区域）保存在 `rig/manifest.json`。手指单独绘制，角色网格锁住同一抓点。缺少可选的 `pickup.png` 时退回原图集中的提起姿势。
