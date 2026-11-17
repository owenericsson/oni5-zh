# Day 12：完成 V2.5 SameBoy 回归并确立新运行基线

日期：2026-11-17

## 目标与版本范围

- 完成 V2.5 主菜单一级列表与已整合对话的 SameBoy 回归；解决菜单关闭后通知板、女人、伽罗对话字形异常。
- 本版从不可变 V1 确定性重建，包含已验收 V2.4.5 对话功能和主菜单一级列表。V2.5 不包含修行句、7×8 或整段屋内剧情。

## SameBoy 运行问题与定位

- 首个候选进入无限重启。运行时在 `$21:$76D2` 调用返回时落到 `$24:$76D5`；bank shadow 为 `$FFA9=$01`，旧 gateway 却从 `$FFAA=$04` 读取恢复值。将 V2.5 fixed gateway 改为从 `$FFA9` 恢复，开场文字随后能够正常显示。
- 开场与一级菜单显示正常，但打开/关闭一级菜单后，通知板、女人和伽罗对话译文仍乱码。
- 检查菜单关闭路由时发现返回地址应按 CPU 地址 `$494A` 比较，而非 ROM 文件偏移 `$894A`；修正 router 比较后，乱码仍存在。
- SameBoy 断点确认菜单关闭 router `$30:$6540` 和恢复 helper `$30:$6400` 均命中。helper 入口处 `$C4F2=$80`、`$FFAD=$09`；旧 helper 除检查菜单缓存标记 `$80` 外，还要求 `$FFAD=$3D`，不满足时便提前返回，未恢复菜单覆盖的字形图案。
- 移除错误的 `$FFAD` 游标门槛，保留 `$C4F2=$80` 菜单标记检查。router 已将该 helper 限定在菜单关闭分支，helper 随后从 ROM 中的备份恢复原图案并清除菜单缓存标记。

## 最终构建与自动化验证

- V2.5 ROM：1 MiB，SHA-256 `a39eb8b30942f37f657bda03c806abf761d6cbbbc5d99b0697544dc25b03170f`。
- V1→V2.5 BPS：13,396 字节，SHA-256 `e5f0eca360f4a991864669316fef2dce26bbeb01a78204158ffe32a9c2a6f845`。
- V2.5 构建测试 5 项通过；构建器完成 ROM checksum 和 BPS 往返验证。版本清单保存构建哈希、输入信息和运行验收状态。

## 防回归约束

- `test_fixed_gateway_restores_bank_from_ff_a9` 精确断言 fixed gateway 的恢复指令读取 `$FFA9`（机器码 `FA A9 FF`）；整合 ROM 测试同时核对 gateway 写入及其 bank mirror。若未来误改回读取 `$FFAA`，该测试将失败。
- 后续修改共享 gateway 或其调用路由时，先运行 `python3 -m unittest discover -s tests -p 'test_build_v2_5_menu_patch.py'`，再重建 ROM 并核对哈希；不能只凭静态生成成功或 checksum 通过就验收开场路径。

## SameBoy 验收与基线变更

用户确认上述 ROM 的全部测试通过，包括开场文本、自由活动一级菜单、菜单关闭后的图形恢复，以及通知板、女人和伽罗对话。此前 V2.4.5 是运行回归基线；从本日起，新工作以 **V2.5-main-menu**（ROM SHA-256 `a39eb8b30942f37f657bda03c806abf761d6cbbbc5d99b0697544dc25b03170f`）作为运行基线。V1 仍是构建新版本的不可变父版本。

版本清单：[V2.5-main-menu](../versions/V2.5-main-menu.json)。
