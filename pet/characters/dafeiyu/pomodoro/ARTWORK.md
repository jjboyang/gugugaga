# 大肥鱼番茄姿势素材

四张 RGBA PNG 使用 512 × 512 逻辑画布，角色可见高度约 400px，脚部基线约 486px，水平居中。原始 `atlas.png`、`atlas.json` 和提起/敲屏幕素材不被覆盖。

- `focus.png`：参考原始电脑姿势重绘，手放在键盘上，保留原头饰。
- `coffee.png`：双手捧瓷杯，手指与杯柄连接。
- `bell.png`：右侧手握住手铃，铃身与握柄连续。
- `stretch.png`：闭眼微笑、双臂舒展；同一张图的眼部也用于其余姿势的眨眼。

图片由内置图像生成工具参考本工程大肥鱼原图生成，保留头身比例、蓝色卷发、女仆头饰、服装与坐姿。生成后仅做透明区域裁切和统一画布对齐。原始生成文件不作为运行依赖。

运行时将整张姿势作为原有骨骼网格的纹理，避免把平面道具悬浮在角色面前。`PomodoroRenderer.deform_vertices` 小幅移动杯子与双手的同一片区域，或绕握柄轻摇手铃。蒸汽和铃声线条是唯一的程序化点缀。

## 生成提示词

以下为本次素材使用的提示词及输入角色。

### Coffee

输入：原图集的待机坐姿，透明背景。

> Use case: precise-object-edit. Asset type: production transparent desktop pet character sprite. Edit the referenced blue-haired chibi maid character into a quiet COFFEE BREAK pose. Preserve EXACT identity, seated front view, enormous head-to-body ratio, blue gradient long curled hair, blue eyes, white frilled headband, blue bows, black and white dress, blue shoes, charming refined anime illustration. Match original line weight and cel shading with soft gradient highlights. Keep head, headband, hair silhouette, body placement and feet as close to the reference as possible. Change only the arms/hand pose and subtle expression: her two small hands ACTUALLY cradle a small ivory porcelain mug in front of her chest, fingers visibly wrapped around it, one hand on its delicate handle. Mug has a tiny cobalt blue bow detail and fine pale-blue rim, tasteful ceramic shading, warm coffee visible. Mug is held just below her mouth, does NOT obscure eyes or nose. Contented gentle smile, relaxed eyes mostly open. No new hat. No floating props. No graphical steam, particles or effects (runtime adds steam). No background, no ground, no shadow disc, no letters. Single complete character, centered, ample transparent padding, feet fully visible. Same scale and layout as reference, highest-fidelity polished 2D character asset, not flat geometric vector drawing.

### Bell / Stretch 共同前缀

输入：原图集的待机坐姿，透明背景。

> Use case: precise-object-edit. Asset type: production transparent desktop pet sprite. Match the referenced blue-haired chibi maid's EXACT identity, proportions, seated front view, very large head, long blue gradient curled hair, blue eyes, white frilled headband, bows, black-white maid dress and dark-blue shoes. Same refined fine-line anime drawing and cel-shaded highlights. Preserve head, hair silhouette, body placement and feet as closely as possible. Single full character centered, feet visible, generous transparent padding, no background, no shadow disc, no text, no floating particles. Do not add a hat.

Bell 追加：

> Change arms and expression into a gentle FOCUS FINISHED reminder: she holds a small elegant polished brass handbell with an ivory handle in her hand on the VIEWER'S RIGHT, just beside her chest. Fingers actually wrap around the handle, bell hangs directly below her fist with believable grip; bell is not floating. Handbell has graceful curved shape, warm reflected highlights, fine dark outlines that match character art. Other hand relaxed on her lap. Cheerful but soft small open smile, bright eyes. No mallet, no disconnected accessories. Pose is a seated gentle wrist ring, not a big celebration. No sound-wave graphics; runtime will animate these.

Stretch 追加：

> Change arms and expression into a relaxed GENTLE STRETCH after a coffee break: she raises both small arms upward next to the sides of her head, elbows bent naturally, two small closed hands, shoulders relaxed. Both hands stay lower than the tip of her blue hair ahoge so she fits a square sprite. Contented peacefully closed eyes, small soft smiling mouth, relaxed cheeks. Seated legs remain as reference. Head, torso and hair positions and head-body size remain as reference. Do not use the big exuberant arms-out celebration pose. No stars, no cup, no bell, no accessories, no effects. Make hands anatomically coherent and sleeve frills delicate like original.

### Focus

输入：原图集的电脑坐姿、新的捧杯姿势，透明背景。

> Use case: precise-object-edit. Asset type: single production transparent desktop pet sprite for quiet FOCUS WORK. Input 1 is the original laptop pose, input 2 shows the polished consistent character style. Recreate the ORIGINAL SEATED LAPTOP POSE from image 1 in the precise clean refined rendering style of image 2. Preserve this exact blue-haired chibi maid identity, very large head and tiny seated body, blue long curls, blue eyes, white frilled headband, blue bows and dark blue shoes. Same front view and same proportions and sitting position as image 2. Small soft focused smile, eyes looking just slightly down at screen but eyes fully visible. A small slate-blue open laptop sits on her lap with screen back facing viewer, below her chin, both small hands naturally using the keyboard behind it; one hand visible at either side edge, coherent wrists and frilled sleeves. Laptop has elegant bevels, soft lavender-blue highlights, small white cat-face emblem, delicate matching line work; NOT a flat geometric shape. Keep feet visible. No extra hat. No detached keyboard, no desk, no extra gadgets, no mug, no bell, no text, no effects. Single complete character centered, ample genuinely transparent padding. Match placement and head silhouette in image 2 as closely as possible, same soft cel-shading, polished anime character art.
