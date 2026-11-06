# JSONL 文本记录格式

## 约定

- 每行是一个独立 JSON 对象，文件采用 UTF-8；下例为便于阅读而格式化展示。
- 所有 ROM 偏移都是从文件起点算起的绝对偏移；地址用带 `0x` 前缀的十六进制字符串表示。
- `end_exclusive` 采用左闭右开范围。`raw_hex` 只包含文本正文，包含终止码，但不包含触发正文的事件命令。
- `source.bank` 同时记录游戏逻辑 bank 和 ROM 实际物理 bank，避免 MBC1 映射下地址含义混淆。
- `tokens` 按原始顺序覆盖正文的每个字节，不得遗漏、重叠或重排；拼接 token 的 `raw_hex` 必须等于记录的 `raw_hex`。
- `kind` 使用 `control`、`macro_ref`、`glyph_code`、`special_glyph`、`terminator` 或 `unknown`。无法确认的字节必须保留为 `unknown`，不得静默转成字符或丢弃。
- `display` 和 `meaning` 只记录有证据支持的解释。宏展开信息可选，只有确认后才填写；未确认的译文用 `null` 表示。
- `observations` 记录模拟器中实际观察到的屏幕文本及其正文子范围；`translation.segments` 与这些范围对应。译文与原始字节分开保存，不覆盖 ROM 数据或控制码。
- 提取器使用 `data/text_manifest.json` 保存人工确认的范围和 token 注释；没有注释的正文 byte 会输出为 `unknown`，同时加入 `diagnostics.unknown_tokens` 并向标准错误报告。

## 字段

| 字段 | 含义 |
|---|---|
| `schema_version` | 记录格式版本；结构变化时递增。 |
| `id` | 稳定且唯一的记录 ID。 |
| `source.rom_sha256` | 被分析 ROM 的 SHA-256，用于确认来源。 |
| `source.bank` | 逻辑 bank、物理 bank 和 bank 大小。 |
| `source.event_command` | 触发该正文的事件命令及其 ROM/CPU 地址。 |
| `source.payload` | 正文起点、排他终点和终止码。 |
| `raw_hex` | 正文原始字节，以空格分隔的十六进制串保存。 |
| `tokens` | 与原始字节逐项对齐的解释；解释不确定时保留 `unknown`。 |
| `observations` | 经模拟器或画面核实的原文片段和对应字节范围。 |
| `translation` | 译文状态及按原文范围对应的译文片段。 |
| `verification` | 支持边界和解释的证据摘要。 |
| `diagnostics.unknown_tokens` | 提取阶段未注释的字节位置和值；未知值保留在 `tokens` 中，不会被丢弃。 |
| `decoded_text` | 解码器追加的可读文本；不会覆盖原始字节或 token。 |
| `decode_diagnostics` | 解码器追加的未知 token 和含义未定 token 列表。 |

## 已验证样本

新页正文由事件命令 `$57` 触发：命令在 ROM `$1353E`，正文从 `$1353F` 开始，包含 `$13552` 的 `$7F` 终止码，排他终点为 `$13553`。屏幕观察文本对应正文子范围 `$13545–$13552`，译文尚未填写。

```json
{
  "schema_version": 1,
  "id": "oni5-bank24-01353f",
  "source": {
    "rom_sha256": "870f83f781c103925f206f35b71cdda6a0493e5b4c70d70b49cade145c35f127",
    "bank": {
      "logical": "0x24",
      "physical": "0x04",
      "size": "0x4000"
    },
    "event_command": {
      "opcode": "0x57",
      "rom_offset": "0x01353E",
      "cpu_address": "0x753E"
    },
    "payload": {
      "start": "0x01353F",
      "end_exclusive": "0x013553",
      "terminator": "0x7F"
    }
  },
  "raw_hex": "80 7D 3B CC 7E 7C 95 7D 3B 1D 4D B7 4D 12 21 0E 36 66 CC 7F",
  "tokens": [
    {"offset": "0x01353F", "raw_hex": "80", "kind": "macro_ref"},
    {"offset": "0x013540", "raw_hex": "7D", "kind": "control", "meaning": "line_advance"},
    {"offset": "0x013541", "raw_hex": "3B", "kind": "glyph_code", "display": "「"},
    {"offset": "0x013542", "raw_hex": "CC", "kind": "macro_ref"},
    {"offset": "0x013543", "raw_hex": "7E", "kind": "control", "meaning": "page_transition"},
    {"offset": "0x013544", "raw_hex": "7C", "kind": "control", "meaning": "region_update"},
    {"offset": "0x013545", "raw_hex": "95", "kind": "macro_ref", "display": "ときわまる"},
    {"offset": "0x013546", "raw_hex": "7D", "kind": "control", "meaning": "line_advance"},
    {"offset": "0x013547", "raw_hex": "3B", "kind": "glyph_code", "display": "「"},
    {"offset": "0x013548", "raw_hex": "1D", "kind": "glyph_code", "display": "な"},
    {"offset": "0x013549", "raw_hex": "4D", "kind": "special_glyph", "display": "[空白图块$4D]", "meaning": "blank_tile; textual role not confirmed"},
    {"offset": "0x01354A", "raw_hex": "B7", "kind": "macro_ref", "display": "なんだ"},
    {"offset": "0x01354B", "raw_hex": "4D", "kind": "special_glyph", "display": "[空白图块$4D]", "meaning": "blank_tile; textual role not confirmed"},
    {"offset": "0x01354C", "raw_hex": "12", "kind": "glyph_code", "display": "こ"},
    {"offset": "0x01354D", "raw_hex": "21", "kind": "glyph_code", "display": "の"},
    {"offset": "0x01354E", "raw_hex": "0E", "kind": "glyph_code", "display": "か"},
    {"offset": "0x01354F", "raw_hex": "36", "kind": "glyph_code", "display": "ん"},
    {"offset": "0x013550", "raw_hex": "66", "kind": "glyph_code", "display": "じ"},
    {"offset": "0x013551", "raw_hex": "CC", "kind": "macro_ref", "display": "！？」"},
    {"offset": "0x013552", "raw_hex": "7F", "kind": "terminator"}
  ],
  "observations": [
    {
      "start": "0x013545",
      "end_exclusive": "0x013552",
      "text": "ときわまる\n「な なんだ このかんじ！？」",
      "evidence": "用户提供的 SameBoy 页面文字；与 ROM 字节和宏表对照"
    }
  ],
  "translation": {
    "status": "untranslated",
    "segments": [
      {
        "source_start": "0x013545",
        "source_end_exclusive": "0x013552",
        "text": null
      }
    ]
  },
  "verification": [
    "事件分派表将 $57 映射到 $6E88，处理器调用文本解析器 $16F0。",
    "运行时解析游标从 $353F 开始；$7F 在 $13552 结束当前内嵌文本段并返回事件脚本。",
    "下一个事件命令 $57 位于 $13556，其正文从 $13557 开始。"
  ],
  "diagnostics": {
    "unknown_tokens": []
  }
}
```

完整正文中 `$1353F–$13544` 的屏幕语义尚未全部确认；因此样本只把已核实的画面文字放入 `observations`，不将其误当成整条正文的完整转写。译文应在确认对应屏幕片段后填写。
