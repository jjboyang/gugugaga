# 大肥鱼原图骨骼动画版

本版直接使用原有 `pet/characters/dafeiyu/atlas.png` 素材，在原图上建立共享顶点的网格和骨骼权重，连续控制呼吸、头部、侧发、手脚及拖动回弹。保留原来的坐姿比例、脸型和发型，不使用重绘的 `parts.png`。眨眼、表情和阅读道具也取自原素材。

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
- `pet/characters/dafeiyu/rig/manifest.json`
- 本包的 `pet/characters/dafeiyu/atlas.png` 和 `atlas.json`（原项目缺少这两个文件时必须复制）。

可另复制 `scripts/preview-rig.py` 以使用预览工具。无需运行推送脚本或发布 GitHub。

原地待机、睡觉、点击唤醒、手动拖动、角色切换及 IPC/Hook 保留。**闲置后自动走向屏幕中央保持关闭**；动画只在桌宠窗口内部运动。

## 离线预览与导出

```bash
python scripts/preview-rig.py
```

预览窗口可切换 11 种状态、暂停播放、重置、减小动作幅度，并点击角色查看回弹。拖动状态会模拟摇摆。预览器不连接 IPC，不更改真实桌宠位置，也不读写用户桌宠配置。

导出一个状态的透明 PNG 动画序列，以及全部状态的总览：

```bash
python scripts/preview-rig.py --export-dir preview/idle --phase idle --seconds 4 --fps 30
python scripts/preview-rig.py --export-dir preview/dragged --phase dragged --seconds 4 --fps 30
python scripts/preview-rig.py --export-dir preview/sleep --phase sleep --seconds 4 --fps 30
python scripts/preview-rig.py --export-dir preview/done --phase done --seconds 4 --fps 30
```

每次导出所选状态的 `frame_0000.png` 等文件和 `contact-sheet.png`，默认 120 帧，自动使用 Qt 无窗口模式。重复使用同一输出目录会替换其中旧的 `frame_XXXX.png`，建议每个状态使用独立目录。

## 调整动画

`pet/characters/dafeiyu/rig/manifest.json` 的 `mesh_columns` 和 `mesh_rows` 控制网格密度，范围 4～32；数值越大，渲染成本越高。原图裁切、对齐比例和锚点保存在上一级 `atlas.json`，不要随意改变，以免角色尺寸或位置偏移。

`pet/rig_mesh.py` 的 `pivots` 定义原坐姿上各骨骼的锚点，`_weights_at()` 定义网格受骨骼影响的范围。`pet/rig_motion.py` 控制动作和弹簧过渡，`pet/rig_animator.py` 负责原图表情、道具与定时渲染。修改后可用预览器检查，不需要改动 IPC 或真实桌宠配置。
