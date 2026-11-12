# Day 7：准备固定 Tile 字形/恢复数据

日期：2026-11-12

## 已确认

- 完成 T14b7 的稳定态 map/OAM 盘点：通知板及女人第一页、第二页的 BG map/OAM 快照已检查。女人两页文字窗口外共有 18 个 `$80–$BF` Tile 引用，排除后有 46 个候选；固定映射需要 34 个自制字形，当前暂取其中 34 个。翻页重叠帧的完整引用检查和整组自动恢复仍未完成。
- `$82` 单字试验已闭环：通知板首字符在上下文钩子下输出 `$82`，写入“中”的 2BPP 图案后显示正常，后续日文不受影响。关闭对话后完整 BG map 不再含 `$82`；原图 `00 00 00 00 30 30 00 00 38 38 44 44 04 04 38 38` 已写回并逐字节读回。
- 使用项目解码器读取原 ROM bank `$03:$5CA4` 字体资源，解出 `$800` 字节；原 ROM 尺寸与校验均通过。Tile `$82` 原图与上述恢复值完全相同，Tile `$A1` 与既有 SameBoy 对话字形记录一致。
- 新增 [`compile_tile_cache_plan.py`](../scripts/compile_tile_cache_plan.py)，生成 [`tile_cache_plan_candidate.json`](../data/tile_cache_plan_candidate.json)：34 个自制字形各有中文 2BPP 图案、目标 Tile、原始字体资源偏移和对应日文原图备份；3 个原生标点不安排图案覆盖。计划明确标记为阻断，尚不可用于 ROM 补丁。

## 验证

- `python3 -m unittest discover -s tests -p 'test_compile_tile_cache_plan.py'`：4 项通过。
- Pylance 对新脚本和测试文件均未报告诊断。
- 原版 ROM 未修改；没有生成完整中文 ROM。

## 下一步

T14c5 已开始，但自动字形加载尚未实现。原 ROM 的 MBC1+RAM+电池类型允许测试扩展 bank；新增 [`build_mbc1_expansion_probe.py`](../scripts/build_mbc1_expansion_probe.py)，把原 ROM 扩至 512 KiB，并在 bank `$10` 放置标记 `$A5`。第一版钩子未限制调用上下文；第二版虽增加 bank/游标门控，但入口使用 `CALL` 后以 `JP` 离开，导致每个字符泄漏两个栈字节。用户报告普通对话字体乱码。之后的探针已改为 `JP` 入口且仅在 bank `$0C`、取码后游标 `$0E34` 时切 bank；用户测得 `$C4F0=$A5`，但 PC `$401C` 非法指令，backtrace 显示返回 banked window。原因是旧代码在 bank `$10` 执行恢复写入后仍继续取指。现改用固定 bank `$00F8` 恢复桩，再执行 `RET`；该版本待 SameBoy 验证。原 ROM 未修改。

扩容探针 ROM 为 [`oni5_t14c5_mbc1_return_readback_probe.gb`](../roms/oni5_t14c5_mbc1_return_readback_probe.gb)，配套存档是原始 `.sav` 的新副本，不覆盖旧测试存档。SameBoy 实测 `$C4F0–$C4F2 = A5 0C 12`，确认 bank `$10` 标记可读，保存的原 bank 为 `$0C`，固定 bank 恢复桩随即读回 `$4E33=$12`。该项通过；主循环稍后读 `$4E33=$05` 对应 bank `$01` 同址字节，不构成失败。相关构建测试、ROM 容量和校验和通过；中文字形加载与恢复仍未实现，完整中文 ROM 尚未生成。

下一子步 T14c5b 已准备自动装载首字“中”的探针 [`oni5_t14c5_auto_glyph_load_probe.gb`](../roms/oni5_t14c5_auto_glyph_load_probe.gb)：仅在 bank `$0C:$0E34` 调用时，先把 VRAM tile `$82` 原图案复制到 WRAM `$C000`，再由扩展 bank `$10` 中的字形数据通过 `$0521` 复制到 `$8820`，首个 tilemap 字节输出 `$82`。6 项构建测试通过，ROM 尺寸/校验和通过；SameBoy 自动加载和显示验证待进行。该探针还没有自动恢复，测试后请重载 ROM，不要继续到其他场景。

SameBoy 首测确认 `x/$10 $8820` 是“中”图案、`x/$10 $C000` 是原 tile `$82`、`$C4F2=$82`，但用户观察到“中”上方原本应为 `$CD` 的 tile 变成 `$12`。对照原 ROM，`$1807` 的指令是 `LD B,$CD`，而首版加载后直接续接 `$180C`，跳过了这条初始化；这与邻格残留旧 B 值相符。已在命中通知板首字的入口分支补回 `LD B,$CD`，生成新版 [`oni5_t14c5_auto_glyph_load_probe_v2.gb`](../roms/oni5_t14c5_auto_glyph_load_probe_v2.gb) 和独立存档副本。22 项构建测试通过，尚待 SameBoy 复测 `$CD` 邻格；不自动恢复 tile。

SameBoy 复测 v2 通过：用户确认“中”上方格子现在为 `$CD`。T14c5b 的单字自动加载、原图备份及首格/邻格显示验证完成；新版仍不会自动恢复 tile。下一步是在通知板终止后的 map 清理完成点恢复 `$C000` 中备份的 tile `$82` 图案。

开始追踪自动恢复点：原 ROM `$17C2` 命中 `$7F` 后仍进入事件/状态处理，不是可直接恢复的简单清理钩子。虽然 `$1A7A` 曾在一段对话内容清除后命中，用户实测它只在通知板对话框出现时命中、关闭时未命中，因此排除该候选。无条件监视 `$99DE` 后在关闭路径命中 PC `$0CDE`，`AF=$0880, DE=$99DE`，回溯 `$0CDE←$07A1←$0C83←$07A1←$0C83←$1BD2←$17E5←$16F9←$6E88`；该指令已写入 `$08`。用户随后在 `$0C90`（循环 `RET`）停住，`$FFBD=$00`；VRAM Viewer 已显示多行清理，但界面仍处于重绘。停在 `$0D3E` 时 `$FF41=$A3,$FF44=$59`，STAT 低两位为 `$03`（LCD mode 3）；此时 `x/$400 $9800` 全 `$FF` 是 VRAM bus 不可读，不能当作清空证据。用户改用 VRAM Viewer 确认该停点的 BG map 已不再引用 `$82`。原指令 `$0D3D–$0D42` 为 `HALT; LDH A,($FF88); AND A; JR NZ,$0D3E`。前两个自动恢复版本在 SameBoy 卡于开机画面，因而废弃。第三版改为只挂在关闭路径候选 `$1BE8`（`$1BE5` 的 `$0D1A` 等待调用返回后），用辅助代码保留寄存器并重现原 `LD HL,$0003`；恢复仍受 `$C4F2=$82`、`$FFAD=$3D` 门控。用户确认该版可启动，随后在关闭通知板后读得 `$C4F2=$82,$FFAD=$3D`，继续运行后 `$C000` 与 `$8820` 的 16 字节均为 `00 00 00 00 30 30 00 00 38 38 44 44 04 04 38 38`，且 `$C4F2=$00`。T14c5c 自动恢复通过；完整通知板译文及其他场景回归仍未完成。

T14c5d 已更新全局输入码契约为 `input_code = tile_id - 0x80`，重新生成候选编码与 Tile cache plan。完整通知板探针 [`oni5_t14c5_full_noticeboard_probe.gb`](../roms/oni5_t14c5_full_noticeboard_probe.gb) 将 7 个原 tile 图案备份到 `$C000–$C06F`，加载中文字形并写入固定长度流 `25 2D 24 06 1A 02 23 4D 4D 7F`；关闭钩子复用已通过的 `$1BE8` 位置，在 `$C4F2=$A5,$FFAD=$3D` 时恢复七个图案并清标记。ROM 容量与校验和通过，13 项定向测试通过，Pylance 语法/诊断无问题。用户已在 SameBoy 确认能载入并显示「欢迎来到小中村」，且正常关闭对话框；关闭后 `$C4F2=$00`。七组 `$C000–$C06F` 备份与对应 VRAM `$8A50/$8AD0/$8A40/$8860/$89A0/$8820/$8A30` 的图案逐字节一致，通知板单页字形加载和自动恢复闭环通过。

T14c6a 的女人两屏探针 [`oni5_t14c6_woman_scroll_probe.gb`](../roms/oni5_t14c6_woman_scroll_probe.gb) 已生成。候选译文「女子\n「差点便被带去\n宿木堂了。宿木堂\n在何处？不知，听妖怪\n言确有此地」」共需 27 个自制字形；探针在 bank `$0C` 首字输入后游标 `$0E8F` 时一次装入全部字形，将 432 字节原 tile 图案备份至 `$C000–$C1AF`，并在两页及重叠滚动期间保持固定映射。初版保留 68 字节文本流和原 `$7F` 位置，尾部填充 30 个 `$4D`；关闭恢复门控为 `$C4F2=$94`、`$FFAD=$D2`，沿用 `$1BE8` 关闭路径钩子。构建 ROM 为 512 KiB，Header/Global checksum 通过，30 项相关测试通过，Pylance 无诊断。用户确认原生 `$BB/$BC` 引号样式正确、两页译文可读并能正常关闭，但发现第二页末尾多滚动一次。已调整编码策略：原文末尾的 30 个字节不需要作为空格输出，改为让 `$7F` 紧跟翻译正文，终止符移至 ROM `$030EB3`；恢复钩子同时改为检测 `$FFAD=$B4`。新探针 [`oni5_t14c6_woman_short_terminator_probe.gb`](../roms/oni5_t14c6_woman_short_terminator_probe.gb) 已生成，大小及校验和通过，相关 24 项测试通过。用户在 SameBoy 确认额外滚动已消失、对话可正常关闭；关闭后 `$C4F2=$00`，27 组原图备份与对应 VRAM tile 的 432 字节逐字节一致。T14c6 闭环完成。
T14c7 已生成整合通知板和女人对话的独立试点 ROM `roms/oni5_t14c7_two_text_pilot.gb` 及可重建的受保护补丁清单 `roms/oni5_t14c7_two_text_pilot_patches.json`。入口按 bank `$0C` 和游标 `$0E34/$0E8F` 分派到各自字形加载器；关闭时按 `$C4F2` 标记和终止后游标 `$3D/$B4` 选择恢复序列。女人码流只写 38 字节，原后续字节保持未改。清单有 22 段期望字节校验的补丁，并描述从原 ROM 扩到 512 KiB、以 `$FF` 填充；由清单重建的 ROM 与直接生成结果完全相同。ROM size code `$04`、Header checksum `$F0`、Global checksum `$53B5` 通过；完整 74 项 Python 测试通过，Pylance 对新增脚本和测试无诊断。用户已在 SameBoy 确认可启动，通知板与女人对话均正常显示并关闭，T15c smoke test 通过。T16a 在整合 ROM 中关闭两条对话后均回读 `$C4F2=$00`，两种恢复分派通过；T16b 菜单与道具界面、T16c 普通战斗进出及 T16d 存档/读取和村庄进出均正常。T17 已在 README 中补充构建步骤、试点限制和回归范围。按用户要求，`roms/` 下除 `oni5_original*` 外的生成 ROM、存档及清单文件已清理；试点并非正式发行版。
