# ONI 5 中文汉化练习

这是一个用于学习 Game Boy ROM 分析与汉化流程的个人练习项目，目标是探索并尝试为经典 RPG《ONI 5：隐忍的继承者》制作中文汉化补丁。

项目会从了解 ROM 结构开始，逐步研究游戏文本、字库、图块和相关数据，再尝试建立可重复的文本提取、翻译与回写流程。当前已通过 SameBoy 定位到一段运行时字符数据流，并确认部分字符码到图块编号的转换；完整文本组织、控制码和字库方案仍待验证。

## 项目目标

- 了解 Game Boy 卡带 ROM 的基本结构和游戏资源布局。
- 使用模拟器调试功能观察游戏运行时的内存、字库和图块。
- 找到游戏文本并分析其编码、控制码与存储方式。
- 评估中文显示所需的字库和 ROM 空间方案。
- 在确认技术方案后，逐步制作和测试中文补丁。

这是一个循序渐进的学习项目；分析结果和工具会随着验证持续更新。

## 当前进度

- 已准备原始 ROM 和模拟器存档用于本地研究。
- 已有 ROM 信息分析、指定区域转储和可打印 ASCII 字符扫描脚本。
- SameBoy 中确认当前场景使用 `$9800` tilemap；已跟踪字符码转换和 tilemap 写入路径。
- 已初步确认字符码到 tile、再到字形的转换链路；当前映射及验证状态集中记录在[字符码与字形对照表](notes/character-map.md)。
- 已在 MBC1 bank `$24` 中定位到解析器消费的文本数据流；确认两条 `$57` 事件命令后的内嵌文本边界，并用两段人工核对的画面文字验证提取与解码输出。当前只确认了 `$7B–$7F` 中几个已观察码的主要行为，尚无穷尽的控制码清单；其他文本块边界及控制码副作用仍待分析。
- 已定义 JSONL 文本记录格式，并用一个经 SameBoy 核对的事件文本样本说明 bank、正文边界、原始字节、控制码和译文的对应方式（见[格式说明](notes/text-record-format.md)）。
- 已实现按人工确认边界工作的只读提取器和保守解码器；未知码与尚未定性的空白图块会显式保留并报告。
- T10–T14 已完成：验证 8×8 中文字形原型并构建两条受限对话试点。T15 已验证试点 ROM 与补丁清单；T16 已在 SameBoy 完成通知板、女人对话、菜单/道具、战斗、存档/读取和村庄切换的有界回归。该试点不是完整汉化或发行 ROM；更广的 tile 生命周期审计仍未完成。当前状态和限制见[任务清单](tasks.md)与[Day 7 记录](notes/day-07.md)。
- T09a–T09f 已完成：已记录室内、村外、道具屋和战斗画面的代表性 map/OAM/VRAM 样本，并对大地图读取固定 VRAM 窗口（未读取完整 map/OAM）。当前没有任何 VRAM 区域被证实可安全复用。结论不涵盖完整资源加载来源或生命周期；若后续需要，应单独开展专项追踪。详见 [任务清单](tasks.md) 与 [Day 3 记录](notes/day-03.md)。
- 每日进展记录见 [Day 1：SameBoy 字符与 ROM 数据流追踪](notes/day-01.md)、[Day 2：控制码展开与页面处理追踪](notes/day-02.md)、[Day 3：只读提取与样本文本解码](notes/day-03.md) 和 [Day 4：字形、布局与翻译范围](notes/day-04.md)。

## 目录结构

```text
.
├── reports/                 # ROM 分析输出及临时预览
├── data/                    # 经确认的文本范围清单
├── notes/                   # 每日研究记录与字符映射表
├── roms/                    # 本地 ROM 与模拟器存档（不纳入 Git）
├── scripts/                 # 辅助分析脚本
├── tests/                   # 分析工具的单元测试
└── tasks.md                 # 分阶段任务清单
```

## 研究日志

按日期简要记录阶段进展；每条链接到对应的详细笔记：

- **2026-11-04（Day 1）**：通过 SameBoy 从 tilemap 追到 bank `$24` 的字符/控制码数据流，并初步验证字节到屏幕字形的转换链路。[查看详细记录](notes/day-01.md)；[查看字符映射表](notes/character-map.md)
- **2026-11-05（Day 2）**：确认 `$BF` 的计数式内联展开、`$7D/$7E/$7F` 的主要行为，以及一条 `$57` 事件文本记录的边界。[查看详细记录](notes/day-02.md)
- **2026-11-06（Day 3）**：完成边界清单驱动的只读 JSONL 提取器和已验证映射范围内的文本解码器；未知码和 `$4D` 的未定语义均不会被静默丢弃。[查看详细记录](notes/day-03.md)
- **Day 7**：生成只包含通知板和村中女人两条对话的独立试点 ROM；SameBoy 有界回归通过。详见 [Day 7 记录](notes/day-07.md)。

## 后续任务

项目的分阶段任务、完成状态和当前执行项见 [tasks.md](tasks.md)。只读提取器的 JSONL 输出约定见[文本记录格式](notes/text-record-format.md)。

## 当前脚本

从项目根目录运行以下命令：

```bash
# 输出 ROM 大小、哈希，并验证头部声明的容量及两种 checksum
python scripts/analys_rom.py roms/oni5_original.gb

# 查看指定 ROM 区域，偏移和长度支持十进制或 0x 开头的十六进制
python scripts/dump_region.py roms/oni5_original.gb 0x100 0x80

# 按已确认的边界提取文本记录为 JSONL（结果输出到标准输出）
python scripts/extract_text.py roms/oni5_original.gb data/text_manifest.json

# 解码提取记录；未知码和语义未定的图块以标记保留
python scripts/extract_text.py roms/oni5_original.gb data/text_manifest.json | python scripts/decode_text.py

# 扫描连续的可打印 ASCII 字符串
python scripts/find_ascii.py roms/oni5_original.gb

# 按 16KB bank 生成 Game Boy 2bpp 图块预览（需要 Pillow）
python scripts/render_tiles.py roms/oni5_original.gb

# 解码当前房间使用的 128 个 tile；输出是本地游戏图形数据，不要提交
python scripts/decode_gb_resource.py roms/oni5_original.gb \
  --bank 5 --descriptor 0x55D3 --length 0x800 \
  --output /tmp/oni5-resource05.bin

# 按已验证的双文本候选数据，生成受限试点 ROM 和可重建补丁清单
python scripts/build_two_text_pilot.py

# 通用构建器：按字节补丁清单生成独立 ROM；默认不覆盖已存在的输出文件
python scripts/build_rom.py roms/oni5_original.gb \
  data/rom_patch_manifest.json roms/oni5_zh.gb
```

资源解码器依据 SameBoy 反汇编还原当前已验证的 bitstream/回溯格式；命令要求明确指定 ROMX bank、描述头地址、解码长度和输出路径。输出文件已存在时默认报错；只有明确需要替换时才传入 `--overwrite`。当前只用 bank `$05` 的一类资源及运行时样本验证，不应假设其他描述头或资源都已支持。

双文本试点构建器默认读取 `roms/oni5_original.gb`、`data/tile_cache_plan_candidate.json` 和 `data/translation_encoding_candidate.json`，生成 `roms/oni5_t14c7_two_text_pilot.gb` 与 `roms/oni5_t14c7_two_text_pilot_patches.json`。也可按顺序提供这五个路径参数（原 ROM、tile cache plan、编码候选、清单输出路径、ROM 输出路径）。构建器会检查原 ROM 的预期 SHA-256、被修改位置的期望字节、候选图案/文本，并验证清单能重建与直接输出完全一致的 ROM；输出为 512 KiB 且会重算 Header/Global checksum。目标文件已存在时会拒绝覆盖；只有确认要替换生成物时才传入 `--overwrite`，原 ROM 不会被覆盖。试点 ROM、模拟器存档及生成的补丁清单在 SameBoy 验证后已按需清理；需要时可用上述命令重新生成。

通用 ROM 构建器接受 schema version 1 的 JSON 清单：顶层字段为 `source_rom_sha256` 和非空 `patches`；每条补丁提供唯一 `id`、十六进制 `offset`、`expected_hex` 和等长 `replacement_hex`。它会拒绝源哈希不匹配、原字节不符、越界、重叠或变长写入；成功时重算 Header/Global checksum，并只写入独立 ROM。当前构建器支持清单声明扩容尺寸和填充字节；具体是否扩容由清单决定。工具不生成 IPS/BPS 分发补丁。

当前双文本试点只在已确认的通知板与女人对话上下文加载和恢复中文字形；不能推断 `$80–$CF` 在全游戏中空闲，也不能当作完整汉化或正式发行版。已在 SameBoy 验证列出的有界回归，但其他 NPC 对话、地图、剧情和异常/边界路径未被覆盖；更广的 tile 生命周期审计 T14b7 仍待完成。ROM 和模拟器存档是本地研究资料，不应分享或提交。

目前的 ASCII 扫描只会找到字节值落在可打印 ASCII 范围内的片段，不能据此判断游戏文本的位置或编码。图块预览也只是原始字节的初步可视化，需通过模拟器进一步确认。
文本提取器只读取清单中人工确认的 bank 和边界，不扫描或修改 ROM；未注释的字节会保留并报告为未知 token。解码器使用 `data/text_decode_map.json` 中已确认的字符、宏和控制码映射；未收录的码不会静默丢弃。

## 本地文件与版本控制

ROM、存档、Python 虚拟环境、生成的图块预览和 `roms/` 下的生成补丁清单是本地研究资料，已通过 `.gitignore` 排除，不应提交到版本控制。历史研究记录中提到的探针文件名用于追溯实验；按需清理后，对应生成物可能不再保留。项目中的脚本、说明和有价值的分析记录可以纳入版本控制。

## 免责声明

本仓库用于个人学习和研究。请自行确保拥有并合法使用所研究的游戏副本；如需分享成果，优先分享不包含游戏原始数据的补丁文件，并遵守适用的法律及权利方要求。
