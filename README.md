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

- **当前指定验收基线：V2.6.7。** 用户报告测试通过并指定其为后续基准；受测 ROM 哈希尚未独立确认。本地 [ROM](roms/oni5_v2_6_7_opening_dialogue.gb) SHA-256 `50c6d78d588ad87caa7dfc25aab970e586322dc568f692144a8168a9767e8dc9`。以 V2.6.6 为父版加入第一场战斗后的 16 句对白；只避让已观察到的主角名字图块。完整自动测试 204 项通过；详见 [Day 15 记录](notes/day-15.md)；[版本清单](versions/V2.6.7-opening-dialogue.json)保留生成时的待验收状态。
- **此前指定验收基线：V2.6.6。** 用户报告测试通过并指定其为当时基准；受测 ROM 哈希尚未独立确认。本地 ROM SHA-256 `a5f22750a56839635130d19b1df787b82f930fa65676b9a995256b4507f23ae0`。以 V2.6.5 为父版加入战斗前的三句对白，保留原战斗事件；只避让已观察到的主角名字图块。完整自动测试 200 项通过；详见 [Day 15 记录](notes/day-15.md)；[版本清单](versions/V2.6.6-opening-dialogue.json)保留生成时的待验收状态。
- **V2.6.5 用户报告测试通过。** 以 V2.6.4 为父版加入九句对白，包括自动推进的特殊句；受测 ROM 哈希尚未独立确认。只避让当前观察到的主角名字图块，其他名字暂不保证。完整自动测试 194 项通过；详见 [Day 15 记录](notes/day-15.md)；[版本清单](versions/V2.6.5-opening-dialogue.json)保留生成时的待验收状态。
- **此前指定验收基线：V2.6.4。** 用户报告测试通过并指定其为当时基准；受测 ROM 哈希尚未独立确认。本地 ROM SHA-256 `027cc41c7ee9c672014e64840c68d1ae7094d36a9b8aeb120b169b421314c793`。从 V2.6.3 加入七句开场对白和局部字形残留修复；只针对当前主角名字避让，其他自定义名字暂不保证。完整自动测试 186 项通过。见 [Day 15 记录](notes/day-15.md)；[版本清单](versions/V2.6.4-opening-dialogue.json)记录生成时的待验收状态。
- **上一验收基线 V2.6.3。** 用户报告验收通过；受测 ROM 哈希尚未独立确认。本地 ROM SHA-256 `1cb47f5e8ca4b62a03d4df9e2e22d6eb0625b813caeec826da33e37577663457`。从 V2.6.2 增量加入静那「常叶丸！？」；完整自动回归 172 项通过。见 [Day 14 记录](notes/day-14.md) 和 [V2.6.3 版本清单](versions/V2.6.3-opening-dialogue.json)。
- **上一验收基线 V2.6.2：** 本地 ROM SHA-256 `6f831505dccb94d250a58b2f8098750aae51d94a0ab83cff1271fa990bbe5cf9`，BPS SHA-256 `e40d0972ac12878768a02b1e4876d80c7d061e46c307a310f71c5507e6f6fa79`。它以 V2.6.1 为父版，加入静那的「常叶丸你这家伙！」。详见 [V2.6.2 版本清单](versions/V2.6.2-opening-dialogue.json)。
- 已建立不可变基准 **V1-opening-dialog**：[V1 ROM](roms/oni5_v1_opening_dialog.gb)、[BPS 补丁](roms/oni5_v1_opening_dialog.bps)及[版本清单](versions/V1-opening-dialog.json)。V1 只含已验证的开场中文；ROM SHA-256 `5682522e20fade44c457725a66430bae13e3d6695dcc18e04d058e4ce2e910ab`，与此前 SameBoy 验证的开场预览逐字节相同。V2/V2.1 的 gateway 问题已定位；V2.2/V2.3 的修行句尚未在确认的目标入口完成验证。V2.4 的准确哈希已在 SameBoy 确认，但必经战斗菜单乱码，故另建了增加指针高字节前置筛选的 V2.4.1。用户已报告 V2.4.1 的必经战斗可正常结束、通知板和女子译文正确，但两段首字上方分别出现异常 tile `$25`/`$14`，且本次未重新确认 ROM 哈希；V2.4.1 仍是部分验证候选。V1 保持不变；后续版本必须从指定父版本分支并一次只增加有限范围。
- 已准备原始 ROM 和模拟器存档用于本地研究。
- 已有 ROM 信息分析、指定区域转储和可打印 ASCII 字符扫描脚本。
- SameBoy 中确认当前场景使用 `$9800` tilemap；已跟踪字符码转换和 tilemap 写入路径。
- 已初步确认字符码到 tile、再到字形的转换链路；当前映射及验证状态集中记录在[字符码与字形对照表](notes/character-map.md)。
- 已在 MBC1 bank `$24` 中定位到解析器消费的文本数据流；确认两条 `$57` 事件命令后的内嵌文本边界，并用两段人工核对的画面文字验证提取与解码输出。当前只确认了 `$7B–$7F` 中几个已观察码的主要行为，尚无穷尽的控制码清单；其他文本块边界及控制码副作用仍待分析。
- 已定义 JSONL 文本记录格式，并用一个经 SameBoy 核对的事件文本样本说明 bank、正文边界、原始字节、控制码和译文的对应方式（见[格式说明](notes/text-record-format.md)）。
- 已实现按人工确认边界工作的只读提取器和保守解码器；未知码与尚未定性的空白图块会显式保留并报告。
- T10–T14 的试点主体已完成：验证 8×8 中文字形原型并构建两条受限对话试点。T15 已验证试点 ROM 与补丁清单；T16 已在 SameBoy 完成有界回归。Day 8 完成翻页过渡帧 Tile 审计、普通 NPC 对话边界回归及四段文本的 `$7C–$7F` 分类；另定位女主旁对话并记录用户确认的译文。用户确认每个文字行由上方 `$CD` 占位/濁点行和下方基字行构成，濁点位置用 `$B8`；稳定页 map/OAM 采样符合该布局。女主旁对话采用上下文映射。用户在旧版整合 ROM 中报告关闭该对话后跳转到类似出房屋的画面；已定位并修正文本终止符提前、事件流起点错位：新版在句末补 6 个 `$4D`，将 `$7F` 放回原位置 `$030F07`，确保事件流从 `$030F08` 继续。新版三文本 ROM 的 85 项测试、checksum 及续接字节核验通过；用户已确认 SameBoy 中该修复、三个目标对话及非目标 NPC 回归全部通过。当前已完成三个对话上下文及主命令菜单的试点；用户决定菜单后移。Day 9 的 T25 已确认 bank `$24`、`$01348F` 译为「今日的修行／就到此为止」；两行各 6 格。T26 已根据用户转写及 SameBoy 快照定位开场滚动文本候选范围 `$01330D–$013367`，核对 `$7D/$7F` 与 91 字节正文，统计出 31/46 个基础平假名；该段没有片假名或汉字，不能视为完整日文字集覆盖。开场五行中文译文已由用户确认；T28 已导出 37 个新增中文字形，T29 已生成只含预览改动的 BPS 补丁，原 ROM 引号、省略号和滚动尾部控制按原始字节保留。预览 ROM 尚待在 SameBoy 运行验证。菜单子项、其他对话范围、战斗和系统提示仍待继续。T21–T24 菜单来源盘点和试点已通过自动化校验及 SameBoy 回归。Day 9 当前任务见[任务清单](tasks.md)；Day 8 详细记录见[notes](notes/day-08.md)。
- T09a–T09f 已完成：已记录室内、村外、道具屋和战斗画面的代表性 map/OAM/VRAM 样本，并对大地图读取固定 VRAM 窗口（未读取完整 map/OAM）。当前没有任何 VRAM 区域被证实可安全复用。结论不涵盖完整资源加载来源或生命周期；若后续需要，应单独开展专项追踪。详见 [任务清单](tasks.md) 与 [Day 3 记录](notes/day-03.md)。
- 每日进展记录见 [Day 1：SameBoy 字符与 ROM 数据流追踪](notes/day-01.md)、[Day 2：控制码展开与页面处理追踪](notes/day-02.md)、[Day 3：只读提取与样本文本解码](notes/day-03.md) 和 [Day 4：字形、布局与翻译范围](notes/day-04.md)；近期工作见 Day 5–8 的记录，Day 9 当前任务和执行状态见[任务清单](tasks.md)。

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
- **2026-11-14（Day 9）**：按用户优先级将菜单本地化后移；确认 `$01348F` 对话片段译为「今日的修行／就到此为止」，两行各 6 格。随后根据用户提供的开场滚动全文及 SameBoy 停点，将候选范围定位到 bank `$04` 的 `$01330D–$013367`；91 字节中有唯一 `$7F` 终止符、四个正文 `$7D` 换行和闭引号后的三个滚动尾部 `$7D`。转写有 38 种不同平假名，其中标准基础平假名覆盖 31/46，无片假名或汉字；因此有助于扩大假名覆盖，但不是完整日文字集。用户确认五行中文译文，宽度 15/13/11/10/9 格。已导出 37 个新增汉字至[独立字形资产](data/chinese_glyphs_oni5_bank04_01330d.json)，并生成只包含开场预览改动的 `roms/oni5_opening_preview.bps`。SameBoy 显示 `$1D` 门控能触发但会重复，故保留一次性 `$C4F2` 标记；尝试前移到 `$0E` 后没有中文，最新补丁恢复到已命中的 `$1D`。同时使用独立省略号字形替代尚未确认展开方式的 `$D5`，并将闭引号移到译文后。预览采用 1 MiB MBC1 布局，镜像 banks `$20–$2F` 并将扩展 bank `$10` 别名到 `$30`；BPS 以 TargetCopy 引用目标中已生成的数据。bank 切换期间的 DI/EI 保护和 fallback 均保留。新补丁通过定向测试、checksum、布局和 BPS 往返验证，仍待用户重新应用并在 SameBoy 回归。[当前任务状态](tasks.md)
- **2026-11-15（Day 10）**：五上下文合并候选在 SameBoy 中开场即死机，已标记失败。为避免再把相似但不同的构建误称为“成功回退”，从原版 ROM 和开场构建输入重新生成 BPS，再应用为 **V1-opening-dialog**；新 ROM 与此前 SameBoy 验证通过的独立 opening preview 逐字节相同。V1 ROM、BPS、所有构建输入哈希和重建命令记录在[版本清单](versions/V1-opening-dialog.json)。这是后续整合唯一基准；7×8、菜单和其他对话不包含在内。
- 当前运行基线为 **V2.5 主菜单一级列表**：从不可变 V1 确定性重建 V2.4.5 已验收内容后加入菜单；修复 fixed gateway bank 恢复偏移、菜单关闭路由地址比较和菜单图形恢复 helper 的游标门槛后，用户确认 SameBoy 全部测试通过。ROM SHA-256 为 `a39eb8b30942f37f657bda03c806abf761d6cbbbc5d99b0697544dc25b03170f`；构建及回归记录见[版本清单](versions/V2.5-main-menu.json)与 [Day 12 日志](notes/day-12.md)。从 V2.6 起，每个新版本都以紧邻的前一个 SameBoy 验收基准为父版本；V1 保留为不可变历史参考。

- **详细日志归档**：Day 9 的开场文本整理见 [notes/day-09.md](notes/day-09.md)，Day 10 的 V1 基线建立见 [notes/day-10.md](notes/day-10.md)。
- **2026-11-16（Day 11）**：V2.5 主菜单一级列表候选已构建，静态路由器缺陷已修正；144 项全量测试、checksum、BPS 往返和双重构建一致性通过。用户确认加载 ROM 哈希正确，但报告 SameBoy 中无限重启，故 V2.5 运行验证失败，根因待调试；V2.4.5 仍为当前已验收运行基线。[查看 Day 11 详细记录](notes/day-11.md)；[V2.5 版本清单](versions/V2.5-main-menu.json)

- **2026-11-17（Day 12）**：修复 V2.5 菜单关闭后对话乱码：SameBoy 证实恢复 helper 因错误 `$FFAD` 门槛提前退出；移除该门槛后，用户确认开场、菜单、通知板、女人和伽罗对话等全部测试通过。V2.5 正式成为新的运行回归基线。[查看 Day 12 详细记录](notes/day-12.md)
- **2026-11-18（Day 13）**：完成 V2.6→V2.6.1 单句对白构建；将中文字形加载门控扩展到跨页文本指针窗口后，用户确认目标句在 SameBoy 正常显示。名字宏 `$95` 的含义曾误记；用户后来更正常叶丸并非可改名主角，而是固定姓名。V2.6.1 尚未完成全局回归，V2.6 仍为完整回归基线。[查看 Day 13 详细记录](notes/day-13.md)
- **2026-11-19**：根据 SameBoy 游标定位并整合 `$01342E` 静那回应和 `$013459` 常叶丸对白；将 `$0133EF` 的 `$95` 固定姓名局部替换为三个中文字形。保留 `$01346D` 翻页控制及后续暂缓处理的静那对白。用户实测发现字形错乱后，依据 `$C4F2=$85` 修复上下文缓存匹配；现以 `$85/$88/$89` 区分三处加载。14 项定向测试、checksum 与 BPS 往返通过；ROM SHA-256 `afe11e0f8aa3d035d76432652aada1c2b3dc2da0a95805783e2a869dae9300cf`，BPS SHA-256 `0571786effd6896ae825058df7051f85c9c72d188bb877b4729ec13e8530c51f`。待用户在 SameBoy 复测。[查看 Day 13 详细记录](notes/day-13.md)
- **2026-11-19（Day 14）**：旧 V2.6.2 候选在目标句后出现持续花屏，已按用户要求放弃并从 V2.6.1 重做。新候选不改全局姓名宏，复用原版 `$D2` 标点宏；用户报告测试通过，将其作为新基准。ROM/BPS 哈希见 [V2.6.2 版本清单](versions/V2.6.2-opening-dialogue.json)。[查看 Day 14 详细记录](notes/day-14.md)

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

# 从已验收 V2.6 基线构建含开场句与修行对白的 V2.6.1 ROM/BPS
python3 -m scripts.build_v2_6_1_single_dialogue

# 从指定 V2.6.1 父版构建包含静那后页对白的 V2.6.2 ROM/BPS
python3 -m scripts.build_v2_6_2_dialogue

# 从指定 V2.6.2 父版构建静那短句的 V2.6.3 候选 ROM/BPS
python3 -m scripts.build_v2_6_3_dialogue

# 从指定 V2.6.3 父版构建七句对白的 V2.6.4 测试候选
python3 -m scripts.build_v2_6_4_dialogue

# 从指定 V2.6.4 父版构建九句对白的 V2.6.5 测试候选
python3 -m scripts.build_v2_6_5_dialogue

# 从 V2.6.5 父版构建战斗前对白的 V2.6.6 测试候选
python3 -m scripts.build_v2_6_6_dialogue

# 构建只包含开场预览改动的 BPS 补丁
python scripts/build_opening_text_preview_patch.py

# 构建开场、修行对话及三个现有对话上下文的 7x7/7x8 对照 ROM
python scripts/build_text_comparison_pilot.py

# 将开场预览 BPS 补丁应用到本地原版 ROM；输入/输出默认位于 roms/
python scripts/apply_bps_patch.py
```

资源解码器依据 SameBoy 反汇编还原当前已验证的 bitstream/回溯格式；命令要求明确指定 ROMX bank、描述头地址、解码长度和输出路径。输出文件已存在时默认报错；只有明确需要替换时才传入 `--overwrite`。当前只用 bank `$05` 的一类资源及运行时样本验证，不应假设其他描述头或资源都已支持。

开场预览补丁构建器默认读取 `roms/oni5_original.gb`、文本清单、开场字形资产、共享字形资产和已审计 Tile 池，生成 `roms/oni5_opening_preview.bps`；它只写出差分补丁，不写出完整 ROM。目标为 1 MiB MBC1 ROM，镜像 banks `$20–$2F` 并将扩展 bank `$10` 别名到 `$30`。已确认 `$D5` 宏在 bank `$0C:$02AA` 指向 `$04CE`，展开长度为 2，内容是两个 `$3A`；普通映射使 `$3A` 对应 tile `$BA`。预览原先将中文字形「活」加载到 `$BA`，与宏展开冲突；当前候选将「活」改分配到未使用的 tile `$BF`（输入码 `$3F`），保留原生 `$D5` 和行推进控制。末行闭引号已从 `$013363` 移到 `$01335C`、紧接末尾省略号；固定行长度和滚动尾部控制不变，7 个填充空格位于闭引号之后。首字修正：postlude 返回点需要 tile ID；现在将输入码 `$3B` 转成左引号 tile `$BB` 返回，而不再返回缓存标记 `$80` 或原始输入码 `$3B`。用户已在 SameBoy 确认首格为正确的「，末行间距正常且没有重启。ROM SHA-256 为 `5682522e20fade44c457725a66430bae13e3d6695dcc18e04d058e4ce2e910ab`，BPS SHA-256 为 `c3e735ab2b273e81446d1a49933186e164cd784d358b7c8e708dd43c59e2abd1`。原版 ROM 未修改。应用器默认读取该 BPS 和原版 ROM，输出到 `roms/oni5_opening_preview.gb`。可用 `--source`、`--patch`、`--output` 覆盖应用路径；输出已存在时需显式传 `--overwrite`。应用前会验证 BPS 源/目标/补丁 CRC，应用后会检查 Game Boy ROM 校验和；原版 ROM不会被覆盖。

双文本试点构建器默认读取 `roms/oni5_original.gb`、`data/tile_cache_plan_candidate.json` 和 `data/translation_encoding_candidate.json`，生成 `roms/oni5_t14c7_two_text_pilot.gb` 与 `roms/oni5_t14c7_two_text_pilot_patches.json`。也可按顺序提供这五个路径参数（原 ROM、tile cache plan、编码候选、清单输出路径、ROM 输出路径）。构建器会检查原 ROM 的预期 SHA-256、被修改位置的期望字节、候选图案/文本，并验证清单能重建与直接输出完全一致的 ROM；输出为 512 KiB 且会重算 Header/Global checksum。目标文件已存在时会拒绝覆盖；只有确认要替换生成物时才传入 `--overwrite`，原 ROM 不会被覆盖。试点 ROM、模拟器存档及生成的补丁清单在 SameBoy 验证后已按需清理；需要时可用上述命令重新生成。

上下文探针构建器默认读取原 ROM、`data/tile_cache_plan_oni5_bank0c_030ee8.json` 与 `data/translation_encoding_oni5_bank0c_030ee8.json`，生成独立的 `roms/oni5_t19_context_probe.gb`。三文本构建器沿用通知板/女人候选文件，并单独读取上述上下文候选，输出 `roms/oni5_t19_three_text_pilot.gb` 和受保护补丁清单；两个输出已存在时需显式传 `--overwrite`。三文本 ROM 限于这三个上下文；新版经 85 项自动化测试、ROM checksum 和文本终止位置核验，仍需 SameBoy 整合回归；不应视作正式 ROM。

菜单构建器默认读取原 ROM、`data/menu_text_manifest.json` 和 `data/menu_chinese_glyphs.json`，生成 `roms/oni5_menu_pilot.gb` 与 `roms/oni5_menu_pilot_patches.json`；默认拒绝覆盖已存在输出，明确替换时传入 `--overwrite`。原 ROM 的 MBC1 代码可能让 bank `$20–$2F` 镜像 `$00–$0F`，因此菜单候选为 1 MiB，在 `$20–$2F` 镜像原 bank，并把扩展 bank `$10` 复制为 `$30` 别名。SameBoy 在 `$19E5` 的主菜单首字入口实际观测到 `HL=$669C`、`$D2F4–$D2F7=04 05 20 46`；因此构建器已移除错误的 `05 06 9B 66` 签名门控，只保留精确指针筛选和 `$C4F2` 防重复标记。Timer 中断实测会在 bank `$30` 的 VRAM-copy 等待循环中触发；加载和关闭恢复路径现在都在切换 bank 前 `DI`，恢复目标 bank 后 `EI`。最新 ROM SHA-256 为 `b424928d181864f2f35f1e2ed9b25841eec8015b9a54281b78ec354d7c129013`，相关 34 项测试与构建校验通过。SameBoy 已确认顶层菜单、「状态」子菜单、退出后的 tile 恢复及第二轮开关均正常；关闭后 `$C4F2=$00`。尚未做备份区与 VRAM 字节级对照。

通用 ROM 构建器接受 schema version 1 的 JSON 清单：顶层字段为 `source_rom_sha256` 和非空 `patches`；每条补丁提供唯一 `id`、十六进制 `offset`、`expected_hex` 和等长 `replacement_hex`。它会拒绝源哈希不匹配、原字节不符、越界、重叠或变长写入；成功时重算 Header/Global checksum，并只写入独立 ROM。当前构建器支持清单声明扩容尺寸和填充字节；具体是否扩容由清单决定。`apply_bps_patch.py` 只应用已有 BPS 补丁，不生成补丁文件。

当前双文本试点只在已确认的通知板与女人对话上下文加载和恢复中文字形；Day 8 已完成这两个上下文的翻页过渡帧引用审计，但不能推断 `$80–$CF` 在全游戏中空闲，也不能当作完整汉化或正式发行版。已在 SameBoy 验证列出的有界回归；普通 NPC 对话、其他地图/剧情和异常边界路径仍未覆盖。ROM 和模拟器存档是本地研究资料，不应分享或提交。

目前的 ASCII 扫描只会找到字节值落在可打印 ASCII 范围内的片段，不能据此判断游戏文本的位置或编码。图块预览也只是原始字节的初步可视化，需通过模拟器进一步确认。
文本提取器只读取清单中人工确认的 bank 和边界，不扫描或修改 ROM；未注释的字节会保留并报告为未知 token。解码器使用 `data/text_decode_map.json` 中已确认的字符、宏和控制码映射；未收录的码不会静默丢弃。

## 不可变构建父版本：V1-opening-dialog

V1 只包含开场滚动中文，不含修行句、通知板、女人、伽罗对话或菜单。`roms/oni5_v1_opening_dialog.gb`（SHA-256 `5682522e20fade44c457725a66430bae13e3d6695dcc18e04d058e4ce2e910ab`）与此前 SameBoy 验证通过的 `roms/oni5_opening_preview.gb` 逐字节一致。V1 是不可变的构建父版本，不要覆盖；每个新候选仍从其清单指定的父 ROM 独立构建。当前已验证的运行参考基线为 **V2.4.5**，后续候选需对照它进行功能回归。

## V2 修行对话及自由活动对话版本记录

V2 只增加「今日的修行／就到此为止」。用户实测：开场 logo 后按开始，在主人公命名画面死机，开场文本尚未出现。快照为 `PC=$A0EC`、回溯经过 `$20:$1935` 文本处理路径，`$FFAA=$0C`、`$FFAD/$FFAE=$00/$00`、`$C4F0–$C4F2=00 00 00`。`$A000–$BFFF` 是外部 RAM 窗口；PC 落在那里符合控制流异常，而不是命中修行字形加载器。

字节对照确认 V2 的 32 字节通用 postlude 从 `$00E0` 写到 `$00FF`，覆盖了 `$00F7` 原有的 9 字节 fallback（`F1 FE 60 D2 15 18 C3 07 18`）。命名画面的 bank `$0C` 不属于 V2 目标上下文，会走这个 fallback；因此旧版 fallback 被覆盖是此次死机的直接缺陷。V2 补丁 [oni5_v2_opening_practice.bps](roms/oni5_v2_opening_practice.bps) 保留为失败证据，不要继续测试或作为父版本。

V2.1 的补丁 [V1→V2.1 BPS](roms/oni5_v2_1_opening_practice.bps) 在修复 `$00F7` fallback 覆盖后，仍在开场文本前触发 `Illegal Opcode. Halting.`。SameBoy 停在 `PC=$4083`；断点确认开场 loader 和 dispatcher 已成功完成（`C4F0=$BB`、`C4F2=$80`）。根因已通过追踪确认：bank `$30` 的 gateway 在 `$4007` 将 ROM bank 切回 `$04` 后，仍从 `$400A` 继续执行；由于 `$4000–$7FFF` 是 banked ROM window，后续取指已来自 bank `$24`，而不是 gateway 所在的 bank `$30`，所以未能到达固定 bank 完成桩。这与 V2.1 之前修复的 fallback 覆盖问题无关。详细停机快照和断点记录保存在 [V2.1 清单](versions/V2.1-opening-practice.json)；V2.1 不要继续测试或作为父版本。

V2.2 仍从不可变 V1 构建，只增加修行对话，并调整 gateway 返回顺序：固定 bank 代码先 `CALL` bank `$30` gateway，gateway 完成后返回固定 bank，再由固定返回桩恢复原 ROM bank。补丁 [V1→V2.2 BPS](roms/oni5_v2_2_opening_practice.bps) 为 5,728 字节，SHA-256 `41e984c5b4a1ab7531746bedaa9793fcab39a22fcf74be6466198bd000014172`；应用后的目标 ROM 预期 SHA-256 为 `6fe654dc63b8867e2744729c81d95d2afc2539c26b342ccd9503944fc6b2d634`。用户确认开场中文正常；随后在屋内剧情对话、自由活动前看到一处类似乱码的日文、未看到中文。

断点停在 `$20:$1803`，回溯经过 `$20:$176E → $20:$16F9 → $21:$6E88`；当时 `$FFAA=$04`、`$FFAE=$34`、`$FFAD=$91`。数值看起来落在修行原文起点 `$01348F` 后两个字节的位置，早期跟踪也确认修行流从 bank `$24` 的 `$748F` 读取。但用户后来澄清，当时观察的是较长屋内剧情中的其他行；没有在修行句首字符处取样，不能据此断定这份快照属于修行上下文。V2.2/V2.3 的修行句运行表现因此仍未定论。完整快照和后续范围澄清见 [V2.2 清单](versions/V2.2-opening-practice.json) 与 [V2.3 清单](versions/V2.3-opening-practice.json)。

V2.3 仍从不可变 V1 构建，保留 V2.2 的 bank-safe gateway，只把修行分派签名改为推断的 `$04/$34/$8F`。[V1→V2.3 BPS](roms/oni5_v2_3_opening_practice.bps) 为 5,730 字节，SHA-256 `a7e853dd16ad7998c89aa388371488be355aafd85b9520cf11b2830d3251cc6b`；应用后的目标 ROM 预期 SHA-256 为 `f74fe255cd67fcaa71de5e5187b229823b1574d0a3334b571bcff70650401529`。用户确认测试了此哈希，但随后澄清该画面属于开场阶段较长的屋内剧情，不是本次要单独整合的修行句。因此这次反馈不能判定修行句通过或失败；V2.3 的修行功能仍待正确场景验证。

V2.2 与 V2.3 的目标 ROM 逐字节比较显示 58 字节、9 个区间不同，差异只在入口/返回分派及其镜像区域；修行译文 payload 没有改变。因而 V2.3 的单测只能证明我们生成了预期的候选分派代码，不能证明 SameBoy 实际进入该 loader，也不能证明 `$04/$34/$8F` 是正确的首字符状态。此前依据 V2.2 的游标 `$91` 推断首游标 `$8F` 并不充分；在确认实际测试 ROM、首字符时的寄存器及 `$C4F2` 前，不再猜测并生成下一版。

随后用户在已确认哈希的 V2.3 中于 `$20:$1803` 提供了现场状态：`$FFAA=$0C`、`$FFAE=$04`、`$FFAD=$46`、`$C4F2=$00`，回溯包含 `$20:$172A`。这不匹配修行 loader 的分派签名，且 `$172A` 曾出现在宏展开路径；该快照不能证明修行句本身已进入目标 loader。此前把 V2.2 的 `$04/$34/$91` 快照直接认定为修行句，证据不足。用户决定先暂缓这段屋内剧情，待相关剧情整体翻译后再处理。

V2.3 补丁保留作历史追溯；目前不继续修行功能。若日后复测，应用补丁并核对完整 ROM 哈希：

```sh
./.venv/bin/python scripts/apply_bps_patch.py --source roms/oni5_v1_opening_dialog.gb --patch roms/oni5_v2_3_opening_practice.bps --output roms/oni5_v2_3_opening_practice.gb
shasum -a 256 roms/oni5_v2_3_opening_practice.gb
```

只有确认 SHA-256 与上面的预期值一致，才可把画面反馈归到 V2.3。保留 V1 不动；V2.3 当前不作为通过版本或下一迭代基线。

## V2.4 自由活动对话候选

V2.4 从不可变 V1 单独构建，只选择通知板和村中女子的对话上下文，采用已知 bank-safe 的 V2.2 gateway 布局；V2.2 仅提供 gateway 代码布局，不作为父 ROM。开场译文保留，修行句、伽罗、菜单和整段屋内剧情均未纳入。V2.3 屋内画面反馈不再被当作修行句实测失败证据。

[V1→V2.4 BPS](roms/oni5_v2_4_roam_dialogues.bps) 为 8,430 字节，SHA-256 `15bf9e54ed4b6f8b0918f018908daaa0de677d087d8163dcf3e3c3358f1d4448`；应用后的目标 ROM 预期 SHA-256 为 `f2f61a05971bcea719c14420ac88e0bdf1f9628ca36ca2d58bd1372f8f6f0895`。3 项定向测试通过：只修改所选对话正文及镜像、V1 开场保持不变、修行与伽罗正文未被加入、BPS 往返及重建确定性通过。用户确认 SameBoy 加载的正是此哈希，并反馈必经战斗菜单满屏乱码、但方向键/A 仍可操作；因菜单难以辨认，尚未到达通知板/女子对话。V2.4 因此仅有部分 SameBoy 反馈，不能晋升为通过版本。战斗菜单本身不在翻译范围内，但它是验证前置条件；乱码是否由 V2.4 的共享文本入口造成，仍需现场状态确认。

战斗菜单首次乱码时的 V2.4 快照为 `$FFAA=$04`、`$FFAE:$FFAD=$37:$A9`、`$C4F2=$00`。这与开场 `$04/$33/$1D`、通知板 `$0C/$0E/$34`、女子 `$0C/$0E/$8F` 的目标签名都不一致；但 V2.4 的 bank-only 入口会在后级签名分派前让 bank `$04` 进入 gateway。因而它可能干扰这个非目标文本路径。V1 原开场入口在切 bank 前会先筛指针和游标；为恢复这一边界，V2.4.1 在切 bank 前按被选上下文的指针高字节 `$33/$0E` 过滤，战斗指针高字节 `$37` 将走原文本 fallback。此为基于快照与静态代码的修复候选，仍须 SameBoy 确认。

## V2.4.1 自由活动对话候选

[V1→V2.4.1 BPS](roms/oni5_v2_4_1_roam_dialogues.bps) 为 8,438 字节，SHA-256 `d61afcff98c521372b1d7119b6f19aee521f3b77a0dd9aa98dca3cbffa93ef34`；目标 [V2.4.1 ROM](roms/oni5_v2_4_1_roam_dialogues.gb) SHA-256 `90b3ab1851d0e2ef2a6f68add9b0c1834b1570971b1dfd6c64201c4e905bc2f4`。它仍从 V1 构建，只调整共享入口的早期过滤；通知板和女子译文范围不变。用户反馈必经战斗正常结束、通知板和女子译文正确；本次反馈没有另行提供 ROM 哈希，因此运行结果与 V2.4.1 的对应关系尚未独立核验。

V2.4.1 的视觉问题为女子首字「女」上方出现 tile `$14`、通知板首字「欢」上方出现 tile `$25`。代码对照显示：开场字形加载器返回前会将 `B` 设为 `$CD`（空白上行 tile），而通知板和女子加载器没有设置 `B`；这与首字输入码恰好对应截图中出现的 tile 值相符。V2.4.2 在两个对话加载器中也设置 `B=$CD`，测试确认生成的 loader 以 `LD B,$CD; RET` 结束。该测试没有模拟 BG-map，实际视觉结果仍待 SameBoy 验证。

[V1→V2.4.2 BPS](roms/oni5_v2_4_2_roam_dialogues.bps) 为 8,446 字节，SHA-256 `acb238df5ccb816f449767d204d868a01498ae606f084697dfa5e87f771723c2`；目标 [V2.4.2 ROM](roms/oni5_v2_4_2_roam_dialogues.gb) SHA-256 `9b457c1f0f352115cb9d666ac6f6897cdc92416c23b42adacb2d5487d51f938c`。它仍以不可变 V1 为父 ROM，范围仍仅包括开场、通知板和女子对话。自动化全量 138 项测试通过；用户确认开场、必经战斗、两段译文及首字上方 tile 均正常，但随后发现任意一段中文对话结束后打开村庄菜单会出现乱码。因此 V2.4.2 只通过了已测对话流程，整体运行状态降为部分通过。详见[V2.4.2 清单](versions/V2.4.2-roam-dialogues.json)。

[V1→V2.4.3 BPS](roms/oni5_v2_4_3_roam_dialogues.bps) 将已确认的伽罗译文「伽罗／「听大娘说那三日月山之上／到底藏着什么呢？」」加入 V2.4.2 的开场、通知板和女子上下文。伽罗原文本跨度为 32 字节，编码保留 6 个 `$4D` 空白输入码，使 `$7F` 终止符仍位于原位置，避免事件游标漂移；伽罗加载器也沿用 `$B=$CD` 的上行空白修正。该候选的父 ROM 仍是不可变 V1（V2.4.2 是运行回归基准，不直接作为父 ROM），以便独立、幂等重建。BPS SHA-256 为 `3951c8e03df0f14f3e26ec1ba29cd8c22455d943b3361dc0f894ddb07d57e310`，目标 [V2.4.3 ROM](roms/oni5_v2_4_3_roam_dialogues.gb) SHA-256 为 `8738ded706f0875c78505aa61074b10f628d862efb44c415977746a6f61e643c`。全量 139 项测试通过，伽罗候选重复构建得到相同补丁和 ROM 哈希；用户已确认译文和原有流程正常，但发现任何一段中文对话后村庄菜单都会乱码。对话关闭后的快照显示 `$C4F2=$00`，说明缓存标记已清；这缩小了排查范围，但尚未证明菜单依赖的图案均已正确恢复。该候选因此只算部分 SameBoy 通过，菜单回归待定位修复。详见[V2.4.3 清单](versions/V2.4.3-roam-dialogues-garou.json)。

[V1→V2.4.4 BPS](roms/oni5_v2_4_4_roam_dialogues.bps) 保留 V2.4.3 的四段中文文本和入口门控，改为从 ROM 恢复通知板、女子、伽罗的原始字形，不再将备份写入 `$C000`。用户在 SameBoy 确认该 ROM 哈希后测试，菜单仍乱码，说明 `$C000` 冲突不是完整原因。进一步快照显示正常时 `$C4F0=$BB`，女子对话后 `$C4F0=$94`，而 `$C4F1=$00,$C4F2=$00`；共享入口 miss 返回路径会读取 `$C4F0`，因此旧的首字返回 tile 残留是更直接的原因。V2.4.4 BPS SHA-256 为 `1e4a2ae70f8b9dbb266b749dcfc5dd679c2197e6d2fcc85a3ea6ab919ca5d3f2`，目标 [V2.4.4 ROM](roms/oni5_v2_4_4_roam_dialogues.gb) SHA-256 为 `51bbdbcd1f8729ac16c3ba7992bcff37aa66a471c80017c8f0b09f7e20cc1107`。详见[V2.4.4 清单](versions/V2.4.4-roam-dialogues-garou-rom-restore.json)。

[V1→V2.4.5 BPS](roms/oni5_v2_4_5_roam_dialogues.bps) 保留 ROM 字形恢复，并在对话加载时保存原 `$C4F0` 到 `$C4F1`，对话清理时恢复 `$C4F0` 并清空 `$C4F1`。补丁 SHA-256 `2138f663bbba846defb0450a84be94ca693ef686e1650e96dd86fc6e472eba50`，目标 [V2.4.5 ROM](roms/oni5_v2_4_5_roam_dialogues.gb) SHA-256 `2543df09fb1dc3f83b7b197701b1f84f9ff7c7906fc39d522c2bbdb0bf239b99`。10 项定向测试、全量 141 项测试及确定性重建均通过；用户随后在 SameBoy 确认所有已发现问题均已解决、测试内容正常，并指定 V2.4.5 为新的运行基线。详见[V2.4.5 清单](versions/V2.4.5-roam-dialogues-return-tile-restore.json)。

## 五上下文 ROM：失败候选记录

运行 `python scripts/build_opening_dialogue_pilot.py` 可从独立开场预览 ROM 重建 1 MiB、7×7 候选，整合开场、修行句「今日的修行／就到此为止」、通知板、女人对话和伽罗对话；主菜单不包含，7×8 按用户决定暂缓。输出为 `roms/oni5_opening_dialogue_pilot.gb`，SHA-256 `956a3047cf9e8e98a5f88c077a8183b25c3699216178f6546af9dc604de6d185`。构建器要求 opening 基底 SHA-256 为 `5682522e20fade44c457725a66430bae13e3d6695dcc18e04d058e4ce2e910ab`，不会覆盖它；输出文件已存在时需显式传 `--overwrite`。

此候选的 121 项 Python 测试、ROM checksum、文本镜像和开场 loader/字形资源核对均通过，但用户实测报告**开场即死机**。它不是 V1 的替代品；不要继续使用，也不要在它上面追加修补。旧候选 `3869e8…` 与 `56f85a…` 同样失败。失败文件仅留作排查记录。

### 多上下文 ROM 集成防重启检查

后续增加文本上下文或合并已有试点时，保留并验证以下运行时契约：

- **沿用已验证的入口 miss 行为。** `$1803` 的入口会触发大量非目标文本查找。已验证的 opening preview 在 `$F7` 使用 9 字节文本 fallback（`F1 FE 60 D2 15 18 C3 07 18`），它会弹出入口保存的 `AF` 并回到原文本处理路径。不要把非目标 bank 直接跳到旧 bank-restore stub；旧 stub依赖 `$C4F1` 已保存，普通入口 miss 并不保证该条件。
- **在切换 bank 前排除非目标文本。** `$1803` 是共享文本入口，战斗文本也可能经过。历史战斗快照的 `$FFAE=$37`；之前尝试按 `$FFAE` 高字节前置筛选、并在 `$C4F2=0` 时绕过 `$1BE8` bank 切换的候选（哈希 `56f85a…`）导致开场乱码及下一幕异常，另一个合并候选也在开场即死机。它们均已判失败。V1 只含开场文本，尚未整合其他对话，因此后续每次加入上下文都必须在 SameBoy 回归战斗菜单及相关非目标文本；不能仅凭自动化测试和 checksum 声称运行安全。
- **逐个检查首字上方的 BG-map 格。** V2.4.1 中用户报告女子「女」上方为 `$14`、通知板「欢」上方为 `$25`。它们分别与译文首字输入码一致，而缓存字形 tile 分别为 `$94`、`$A5`；自动化单测只锁定输入码、目标字形和入口游标关系，不能代替图形层验证。每个新候选都要在 SameBoy 稳定显示期间检查首字上方格，并与相邻字符的占位/濁点行比较；在异常消失前不得晋升该候选。
- **缓存命中时避免重复切 bank。** `$C4F2` 是上下文缓存标记。标记非零时，后续字符应走文本 fallback，不要每个字符都进入 bank10 分派器或重复装载字形。上下文结束时，恢复路径必须清除标记。
- **勿将对话图案备份写入 `$C000–$CFFF`。** SameBoy 追踪确认游戏把此 WRAM 区域作为字体暂存区并复制到 VRAM；旧 V2.4.2/2.4.3 对话加载器写入 `$C000`，导致后续村庄菜单重载字体时显示乱码。V2.4.4 改从 ROM 暂存原图案并恢复；新候选仍须在 SameBoy 确认菜单正常。
- **对话关闭时恢复 `$C4F0` 返回 tile。** 现场确认它在正常状态为 `$BB`，女子对话后变成 `$94`；共享入口 miss 路径会读取该值。缓存清理时除清除 `$C4F2` 外，还必须恢复先前的 `$C4F0`，并清除临时保存字节 `$C4F1`。
- **区分缓存标记和返回 tile。** 开场缓存标记是首个自制字形 tile（当前 `$80`）；开场原生左引号的返回 tile 是 `$BB`。分别保存，不能互相代用。
- **保持加载器寄存器/中断约定。** 开场加载结束后需要 `B=$CD`；bank 切换期间保持 `DI`，恢复目标 bank 后再 `EI`。合并加载器还必须保留成功 preview 的 16 字节 VRAM copy 调用和对应图案数据。
- **不要把 checksum 当作运行通过。** 自动化测试、ROM checksum 和 patch rebuild 通过后，仍需在 SameBoy 实测启动与开场；再逐个回归合并的对话上下文及关闭后的 tile 恢复。出现重启时，启动清 VRAM 循环（如 `$20:$04F8`）只是重启后的状态，不能直接当作复位根因。

构建器在入口门控、loader 返回约定、缓存标记/返回 tile 分离和 bank10 分派方面有对应回归测试；修改这些路径时一并更新测试。V1 是不可变构建父版本，V2.4.5 是当前运行回归基线。任何后续候选改写共享文本/恢复入口后，都必须先确认自动开场战斗菜单能正常显示、选择并退出，再测试其他对话。

## 本地文件与版本控制

ROM、存档、Python 虚拟环境、生成的图块预览和 `roms/` 下的生成补丁清单是本地研究资料，已通过 `.gitignore` 排除，不应提交到版本控制。历史研究记录中提到的探针文件名用于追溯实验；按需清理后，对应生成物可能不再保留。项目中的脚本、说明和有价值的分析记录可以纳入版本控制。

## 免责声明

本仓库用于个人学习和研究。请自行确保拥有并合法使用所研究的游戏副本；如需分享成果，优先分享不包含游戏原始数据的补丁文件，并遵守适用的法律及权利方要求。
