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
- T10–T14 的试点主体已完成：验证 8×8 中文字形原型并构建两条受限对话试点。T15 已验证试点 ROM 与补丁清单；T16 已在 SameBoy 完成有界回归。Day 8 完成翻页过渡帧 Tile 审计、普通 NPC 对话边界回归及四段文本的 `$7C–$7F` 分类；另定位女主旁对话并记录用户确认的译文。用户确认每个文字行由上方 `$CD` 占位/濁点行和下方基字行构成，濁点位置用 `$B8`；稳定页 map/OAM 采样符合该布局。女主旁对话采用上下文映射。用户在旧版整合 ROM 中报告关闭该对话后跳转到类似出房屋的画面；已定位并修正文本终止符提前、事件流起点错位：新版在句末补 6 个 `$4D`，将 `$7F` 放回原位置 `$030F07`，确保事件流从 `$030F08` 继续。新版三文本 ROM 的 85 项测试、checksum 及续接字节核验通过；用户已确认 SameBoy 中该修复、三个目标对话及非目标 NPC 回归全部通过。当前只完成三个对话上下文试点，菜单及道具/状态、战斗、系统提示等非对话界面仍未完成汉化。T21 已核实主菜单和伴随小框文字的 ROM 来源，T22 已确认五项主菜单及「盘缠」译名；T23 已确认菜单绘制/退出路径与场景 map 重绘点，室外和屋内的当前 BG/OAM 样本未见菜单文字以外的 `$80–$BF` tile 冲突。T24 菜单试点已通过自动化校验及 SameBoy 回归：主菜单、「状态」子菜单、菜单退出后的字形恢复和再次开关均正常。当前状态见[任务清单](tasks.md)与[Day 8 记录](notes/day-08.md)。
- T09a–T09f 已完成：已记录室内、村外、道具屋和战斗画面的代表性 map/OAM/VRAM 样本，并对大地图读取固定 VRAM 窗口（未读取完整 map/OAM）。当前没有任何 VRAM 区域被证实可安全复用。结论不涵盖完整资源加载来源或生命周期；若后续需要，应单独开展专项追踪。详见 [任务清单](tasks.md) 与 [Day 3 记录](notes/day-03.md)。
- 每日进展记录见 [Day 1：SameBoy 字符与 ROM 数据流追踪](notes/day-01.md)、[Day 2：控制码展开与页面处理追踪](notes/day-02.md)、[Day 3：只读提取与样本文本解码](notes/day-03.md) 和 [Day 4：字形、布局与翻译范围](notes/day-04.md)；近期工作见 Day 5–8 的记录。

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

按日期简要记录每天的阶段进展；每条链接到对应的详细笔记：

- **2026-11-04（Day 1）**：通过 SameBoy 从 tilemap 追到 bank `$24` 的字符/控制码数据流，区分文本读取与图块资源加载，并初步验证字节到屏幕字形的转换链路。[查看详细记录](notes/day-01.md)；[查看字符映射表](notes/character-map.md)
- **2026-11-05（Day 2）**：追踪 `$BF` 内联展开及 `$7D/$7E/$7F` 的主要分支，确认换行、页面处理和文本结束会触发不同的状态与 tilemap 操作。[查看详细记录](notes/day-02.md)
- **2026-11-06（Day 3）**：完成边界清单驱动的只读 JSONL 提取器和保守解码器，并核对两条样本文本；未知码与 `$4D` 的未定语义都会显式保留。[查看详细记录](notes/day-03.md)；[文本记录格式](notes/text-record-format.md)
- **2026-11-09（Day 4）**：验证 8×8、2BPP 中文字形原型，制定对话每行 18 格的固定布局，并确定首轮可见文本试点及 ROM 补丁构建器的校验规则。[查看详细记录](notes/day-04.md)
- **2026-11-10（Day 5）**：定位村中女人对话的 banked 文本边界，检查代表场景的 BG map、OAM 和 VRAM 使用；结论是单帧未引用不等于跨场景安全，缓存备份与恢复仍需验证。[查看详细记录](notes/day-05.md)
- **2026-11-11（Day 6）**：捕获女人对话翻页时新旧页面同时可见的重叠帧，据此确定缓存需覆盖两页共存期间的字形；同时收紧试点文本的输入编码和候选 Tile 方案。[查看详细记录](notes/day-06.md)
- **2026-11-12（Day 7）**：生成 34 字形的缓存/原图备份候选，并将通知板与女人对话整合为可重建的试点 ROM。用户完成 SameBoy 对话、菜单、战斗、存档和场景切换回归；更广的 Tile 生命周期审计仍未完成，试点不等于正式发行版。[查看详细记录](notes/day-07.md)
- **2026-11-13（Day 8）**：完成女人对话翻页过渡帧的窄范围 map/OAM 审计、普通 NPC 边界回归及四段样本文本中 `$7C–$7F` 的分类；确认女主旁对话译文，并修复三文本试点中 `$7F` 提前导致的事件流错位。新版 512 KiB 三文本试点通过 85 项测试、checksum、续接字节核验和 SameBoy 整合回归。随后完成主命令菜单盘点与菜单试点：发现 MBC1 高位 bank 映射要求保留 `$20–$2F` 的原 ROM 镜像，并让扩展 helper 在 `$30` 可达，因此采用 1 MiB 候选布局；调试并修复 banked VRAM 复制期间 Timer 中断导致的不稳定，以及菜单关闭时恢复路径的中断保护。最新菜单 ROM 通过 34 项相关测试和构建校验；用户已在 SameBoy 确认主菜单、「状态」子菜单、退出恢复及第二轮开关正常。试点 ROM 和测试生成物已清理，原始 ROM 与原始存档保留。[查看详细记录](notes/day-08.md)

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

# 按上下文字形/编码候选生成独立对话缓存探针 ROM
python scripts/build_context_glyph_probe.py

# 将通知板、女人、女主旁三个对话上下文构建为独立试点 ROM
python scripts/build_three_text_pilot.py

# 构建主菜单汉化试点 ROM 和受保护补丁清单
python scripts/build_menu_pilot.py

# 通用构建器：按字节补丁清单生成独立 ROM；默认不覆盖已存在的输出文件
python scripts/build_rom.py roms/oni5_original.gb \
  data/rom_patch_manifest.json roms/oni5_zh.gb
```

资源解码器依据 SameBoy 反汇编还原当前已验证的 bitstream/回溯格式；命令要求明确指定 ROMX bank、描述头地址、解码长度和输出路径。输出文件已存在时默认报错；只有明确需要替换时才传入 `--overwrite`。当前只用 bank `$05` 的一类资源及运行时样本验证，不应假设其他描述头或资源都已支持。

双文本试点构建器默认读取 `roms/oni5_original.gb`、`data/tile_cache_plan_candidate.json` 和 `data/translation_encoding_candidate.json`，生成 `roms/oni5_t14c7_two_text_pilot.gb` 与 `roms/oni5_t14c7_two_text_pilot_patches.json`。也可按顺序提供这五个路径参数（原 ROM、tile cache plan、编码候选、清单输出路径、ROM 输出路径）。构建器会检查原 ROM 的预期 SHA-256、被修改位置的期望字节、候选图案/文本，并验证清单能重建与直接输出完全一致的 ROM；输出为 512 KiB 且会重算 Header/Global checksum。目标文件已存在时会拒绝覆盖；只有确认要替换生成物时才传入 `--overwrite`，原 ROM 不会被覆盖。试点 ROM、模拟器存档及生成的补丁清单在 SameBoy 验证后已按需清理；需要时可用上述命令重新生成。

上下文探针构建器默认读取原 ROM、`data/tile_cache_plan_oni5_bank0c_030ee8.json` 与 `data/translation_encoding_oni5_bank0c_030ee8.json`，生成独立的 `roms/oni5_t19_context_probe.gb`。三文本构建器沿用通知板/女人候选文件，并单独读取上述上下文候选，输出 `roms/oni5_t19_three_text_pilot.gb` 和受保护补丁清单；两个输出已存在时需显式传 `--overwrite`。三文本 ROM 限于这三个上下文；新版经 85 项自动化测试、ROM checksum 和文本终止位置核验，仍需 SameBoy 整合回归；不应视作正式 ROM。

菜单构建器默认读取原 ROM、`data/menu_text_manifest.json` 和 `data/menu_chinese_glyphs.json`，生成 `roms/oni5_menu_pilot.gb` 与 `roms/oni5_menu_pilot_patches.json`；默认拒绝覆盖已存在输出，明确替换时传入 `--overwrite`。原 ROM 的 MBC1 代码可能让 bank `$20–$2F` 镜像 `$00–$0F`，因此菜单候选为 1 MiB，在 `$20–$2F` 镜像原 bank，并把扩展 bank `$10` 复制为 `$30` 别名。SameBoy 在 `$19E5` 的主菜单首字入口实际观测到 `HL=$669C`、`$D2F4–$D2F7=04 05 20 46`；因此构建器已移除错误的 `05 06 9B 66` 签名门控，只保留精确指针筛选和 `$C4F2` 防重复标记。Timer 中断实测会在 bank `$30` 的 VRAM-copy 等待循环中触发；加载和关闭恢复路径现在都在切换 bank 前 `DI`，恢复目标 bank 后 `EI`。最新 ROM SHA-256 为 `b424928d181864f2f35f1e2ed9b25841eec8015b9a54281b78ec354d7c129013`，相关 34 项测试与构建校验通过。SameBoy 已确认顶层菜单、「状态」子菜单、退出后的 tile 恢复及第二轮开关均正常；关闭后 `$C4F2=$00`。尚未做备份区与 VRAM 字节级对照。

通用 ROM 构建器接受 schema version 1 的 JSON 清单：顶层字段为 `source_rom_sha256` 和非空 `patches`；每条补丁提供唯一 `id`、十六进制 `offset`、`expected_hex` 和等长 `replacement_hex`。它会拒绝源哈希不匹配、原字节不符、越界、重叠或变长写入；成功时重算 Header/Global checksum，并只写入独立 ROM。当前构建器支持清单声明扩容尺寸和填充字节；具体是否扩容由清单决定。工具不生成 IPS/BPS 分发补丁。

当前双文本试点只在已确认的通知板与女人对话上下文加载和恢复中文字形；Day 8 已完成这两个上下文的翻页过渡帧引用审计，但不能推断 `$80–$CF` 在全游戏中空闲，也不能当作完整汉化或正式发行版。已在 SameBoy 验证列出的有界回归；普通 NPC 对话、其他地图/剧情和异常边界路径仍未覆盖。ROM 和模拟器存档是本地研究资料，不应分享或提交。

目前的 ASCII 扫描只会找到字节值落在可打印 ASCII 范围内的片段，不能据此判断游戏文本的位置或编码。图块预览也只是原始字节的初步可视化，需通过模拟器进一步确认。
文本提取器只读取清单中人工确认的 bank 和边界，不扫描或修改 ROM；未注释的字节会保留并报告为未知 token。解码器使用 `data/text_decode_map.json` 中已确认的字符、宏和控制码映射；未收录的码不会静默丢弃。

## 本地文件与版本控制

ROM、存档、Python 虚拟环境、生成的图块预览和 `roms/` 下的生成补丁清单是本地研究资料，已通过 `.gitignore` 排除，不应提交到版本控制。历史研究记录中提到的探针文件名用于追溯实验；按需清理后，对应生成物可能不再保留。项目中的脚本、说明和有价值的分析记录可以纳入版本控制。

## 免责声明

本仓库用于个人学习和研究。请自行确保拥有并合法使用所研究的游戏副本；如需分享成果，优先分享不包含游戏原始数据的补丁文件，并遵守适用的法律及权利方要求。
