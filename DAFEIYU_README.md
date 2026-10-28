# 大肥鱼角色（预览版）

在桌宠上打开右键菜单，选择「切换角色：企鹅 / 大肥鱼」。

## 运行

```bash
pip install -r requirements.txt
python pet_app.py
```

## 素材说明

`pet/characters/dafeiyu/atlas.png` 是带透明背景的 4 × 4 图集，共 16 个单角色姿势。`atlas.json` 为各状态指定裁切区域、角色锚点和播放顺序。

每一帧只读取自己的角色区域，并使用统一的画布、比例和脚部基线，避免相邻人物、背景碎片或整图横移。图集边缘已在浅色和深色背景上检查。

待机包含眨眼，奔跑、完成、睡觉、行走包含多帧；其余状态使用单帧。素材为 AI 生成的预览版，摸头和抱鱼的专属交互尚未接入。

## 检查

```bash
QT_QPA_PLATFORM=offscreen python -m unittest discover -s tests
```
