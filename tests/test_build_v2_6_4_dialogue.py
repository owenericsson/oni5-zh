import unittest

from scripts import build_v2_6_3_dialogue as previous
from scripts import build_v2_6_4_dialogue as build
from scripts.apply_bps_patch import apply_bps_patch
from scripts.build_opening_text_preview_patch import FONT_BANK, FONT_DESCRIPTOR, FONT_LENGTH, load_glyph_patterns
from scripts.build_v2_6_1_single_dialogue import SOURCE_ROM
from scripts.decode_gb_resource import decode_resource
from scripts.rom_checksums import verify_rom
from test_build_v2_6_2_dialogue import run_glyph_helper


def run_transition(rom, memory):
    """Run the transition wrapper, substituting the existing glyph-helper harness."""
    pc = build.TRANSITION_HELPER_OFFSET
    a = 0
    zero = False
    hl = 0x1234
    saved_hl = []
    events = []
    for _ in range(32):
        opcode = rom[pc]
        pc += 1
        if opcode == 0xFA:
            address = int.from_bytes(rom[pc:pc + 2], "little")
            pc += 2
            a = memory[address]
        elif opcode == 0xFE:
            zero = a == rom[pc]
            pc += 1
        elif opcode == 0x20:
            displacement = int.from_bytes(rom[pc:pc + 1], "little", signed=True)
            pc += 1
            if not zero:
                pc += displacement
        elif opcode == 0xE5:
            saved_hl.append(hl)
        elif opcode == 0xE1:
            hl = saved_hl.pop()
        elif opcode == 0xCD:
            address = int.from_bytes(rom[pc:pc + 2], "little")
            pc += 2
            if address == build.bank_cpu_address(build.TRANSITION_HELPER_OFFSET) + 16:
                trampoline = build.TRANSITION_HELPER_OFFSET + 16
                if rom[trampoline:trampoline + 6] != bytes.fromhex("C5 D5 F5 C3 F3 79"):
                    raise AssertionError("incorrect restore trampoline")
                synthetic = bytearray(rom)
                start = build.SOURCE_SIZE + 0x39E0
                body = build.SOURCE_SIZE + build.REPLY_RESTORE_BODY - 0x4000
                end = build.SOURCE_SIZE + 0x3ACF + 4
                restore = bytes.fromhex("C5 D5 F5") + rom[body:end]
                synthetic[start:start + len(restore)] = restore
                run_glyph_helper(synthetic, start, memory)
                hl = 0xBEEF
                events.append("restore")
            elif address == build.TOKIWA_LOADER:
                run_glyph_helper(rom, build.SOURCE_SIZE + address - 0x4000, memory)
                events.append("load")
            else:
                raise AssertionError(f"unexpected call ${address:04X}")
        elif opcode == 0xC9:
            if saved_hl:
                raise AssertionError("unbalanced HL stack")
            return events, hl
        else:
            raise AssertionError(f"unexpected transition opcode ${opcode:02X}")
    raise AssertionError("transition did not return")


class ReplyTransitionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.parent = previous.OUTPUT_ROM.read_bytes()
        cls.target = bytearray(cls.parent)
        cls.start, cls.end = build.install_reply_transition_restore(cls.target)

    def test_restores_reply_before_replacing_its_marker(self):
        memory = bytearray(0x10000)
        memory[0xC4F2] = 0x88
        memory[0xFFAD] = 0x59
        memory[0x8A00:0x8A10] = bytes.fromhex("FE FE 10 10 10 10 14 14 12 12 10 10 10 10 00 00")
        expected = bytearray(memory)
        expected[0xFFAD] = 0x53
        run_glyph_helper(self.parent, build.SOURCE_SIZE + 0x39E0, expected)
        expected[0xFFAD] = 0x59
        run_glyph_helper(self.parent, build.SOURCE_SIZE + 0x2580, expected)
        events, hl = run_transition(self.target, memory)
        self.assertEqual(events, ["restore", "load"])
        self.assertEqual(hl, 0x1234)
        self.assertEqual(memory, expected)
        self.assertEqual(memory[0xC4F2], 0x89)
        self.assertEqual(memory[0x8A00:0x8A10], self.parent[0x439D0:0x439E0])

    def test_other_markers_keep_original_loader_behavior(self):
        for marker in (0x00, 0x85, 0x89):
            with self.subTest(marker=marker):
                memory = bytearray(0x10000)
                memory[0xC4F2] = marker
                memory[0xFFAD] = 0x59
                expected = bytearray(memory)
                run_glyph_helper(self.parent, build.SOURCE_SIZE + 0x2580, expected)
                events, hl = run_transition(self.target, memory)
                self.assertEqual(events, ["load"])
                self.assertEqual(hl, 0x1234)
                self.assertEqual(memory, expected)

    def test_only_local_call_and_free_helper_space_change(self):
        for i, (before, after) in enumerate(zip(self.parent, self.target)):
            if before != after:
                self.assertTrue(
                    build.REPLY_TO_TOKIWA_CALL_OFFSET + 1 <= i < build.REPLY_TO_TOKIWA_CALL_OFFSET + 3
                    or self.start <= i < self.end,
                    f"unexpected change at ${i:06X}",
                )


class CandidateBuildTests(unittest.TestCase):
    def test_build_round_trip_and_change_scope(self):
        parent = previous.OUTPUT_ROM.read_bytes()
        target, patch, version = build.build()
        self.assertEqual(apply_bps_patch(parent, patch), target)
        self.assertTrue(verify_rom(target).passed)
        self.assertEqual(version["runtime_validation"]["status"], "pending-sameboy")
        allowed = [(start, end) for _, start, end, _ in (*build.FIRST_PAGES, *build.LATER_PAGES)]
        allowed += list(build.COMPONENT_RANGES)
        allowed += [
            (build.LOAD_GATE_OFFSET + 1, build.LOAD_GATE_OFFSET + 3),
            (build.RESTORE_WRAPPER_OFFSET + 2, build.RESTORE_WRAPPER_OFFSET + 4),
            (build.NEW_LOAD_DISPATCH_OFFSET, build.SOURCE_SIZE + 0x0200),
            (build.NEW_RESTORE_DISPATCH_OFFSET, build.SOURCE_SIZE + 0x0300),
            (build.REPLY_TO_TOKIWA_CALL_OFFSET + 1, build.REPLY_TO_TOKIWA_CALL_OFFSET + 3),
            (build.TRANSITION_HELPER_OFFSET, build.TRANSITION_HELPER_OFFSET + 22),
            (0x14E, 0x150),
        ]
        allowed += [(start + build.MBC1_MIRROR_OFFSET, end + build.MBC1_MIRROR_OFFSET)
                    for start, end in allowed if start >= 0x4000]
        for i, (before, after) in enumerate(zip(parent, target)):
            if before != after:
                self.assertTrue(any(start <= i < end for start, end in allowed),
                                f"unexpected change at ${i:06X}")


class FirstPagesTests(unittest.TestCase):
    def test_patch_preserves_page_controls_and_mirrors(self):
        parent = previous.OUTPUT_ROM.read_bytes()
        target = bytearray(parent)
        build.install_translations(target)
        for _, start, end, _ in (*build.FIRST_PAGES, *build.LATER_PAGES):
            with self.subTest(start=start):
                self.assertEqual(parent[start - 1], 0x7C)
                self.assertEqual(target[start - 1], parent[start - 1])
                self.assertEqual(target[end], parent[end])
                mirror = build.MBC1_MIRROR_OFFSET
                self.assertEqual(target[mirror + start:mirror + end], target[start:end])
        self.assertNotEqual(target[0x1348D], parent[0x1348D])
        with self.assertRaises(ValueError):
            build.install_translations(target)

    def test_encoded_pages_preserve_names_and_confirmed_text(self):
        tiles, pages = build.prepare_first_pages()
        self.assertFalse(set(tiles.values()) & build.CURRENT_NAME_TILES)
        decode = {tile - 0x80: character for character, tile in tiles.items()}
        decode.update({0x3B: "「", 0x3C: "」", 0x3E: "。", 0x4A: "？", 0x4B: "！",
                       0x7D: "\n", 0x4D: "", 0x80: "{主角}"})
        expected = (
            "静那\n「今天的修炼就到此为止。」",
            "{主角}\n「恋人来了，你就想赶紧结束\n修炼吧，静那老师？」",
            "静那\n「少说这种小大人似的话！\n回去复习今天学的内容。」",
            "{主角}\n「嘿嘿，害羞了。\n恋人先生，请慢慢聊。」",
        )
        for (_, start, end, _), text in zip(build.FIRST_PAGES, expected):
            with self.subTest(start=start):
                self.assertEqual(len(pages[start]), end - start)
                self.assertEqual("".join(decode[code] for code in pages[start]), text)

    def test_later_pages_preserve_names_and_native_punctuation(self):
        tiles, pages = build.prepare_later_pages()
        self.assertFalse(set(tiles.values()) & build.CURRENT_NAME_TILES)
        decode = {tile - 0x80: character for character, tile in tiles.items()}
        decode.update({0x3B: "「", 0x3C: "」", 0x3E: "。", 0x4A: "？", 0x4B: "！",
                       0x7D: "\n", 0x4D: "", 0x80: "{主角}", 0xD5: "{省略}",
                       0xCC: "！？」"})
        expected = (
            "常叶丸\n「什么情况这气息！？」",
            "{主角}\n「刚才是在叫我{省略}\n不可能吧，是错觉吗？」",
            "常叶丸\n「不是错觉{省略}{省略}\n刚才那到底是什么！？」",
        )
        for (_, start, end, _), text in zip(build.LATER_PAGES, expected):
            with self.subTest(start=start):
                self.assertEqual(len(pages[start]), end - start)
                self.assertEqual("".join(decode[code] for code in pages[start]), text)


class InitialLoadDispatcherTests(unittest.TestCase):
    def run_dispatch(self, bank, high, cursor, marker):
        code = build.build_initial_load_dispatcher(0x4100, 0x4200)
        memory = bytearray(0x10000)
        memory[0xFFAA], memory[0xFFAE], memory[0xFFAD] = bank, high, cursor
        memory[0xC4F2] = marker
        a = b = 0
        zero = False
        calls = []
        pc = 0
        for _ in range(100):
            op = code[pc]
            pc += 1
            if op == 0xFA:
                address = int.from_bytes(code[pc:pc + 2], "little")
                pc += 2
                a = memory[address]
            elif op == 0xFE:
                zero = a == code[pc]
                pc += 1
            elif op == 0xB7:
                zero = a == 0
            elif op == 0x20:
                delta = int.from_bytes(code[pc:pc + 1], "little", signed=True)
                pc += 1
                if not zero:
                    pc += delta
            elif op == 0xCD:
                calls.append(int.from_bytes(code[pc:pc + 2], "little"))
                pc += 2
            elif op == 0x3E:
                a = code[pc]
                pc += 1
            elif op == 0x06:
                b = code[pc]
                pc += 1
            elif op == 0xEA:
                address = int.from_bytes(code[pc:pc + 2], "little")
                pc += 2
                memory[address] = a
            elif op == 0xAF:
                a, zero = 0, True
            elif op == 0xC9:
                return a, b, memory, calls
            else:
                self.fail(f"unexpected opcode ${op:02X}")
        self.fail("loader dispatcher did not return")

    def test_exact_cursors_load_and_return_current_character(self):
        first_tiles, first_pages = build.prepare_first_pages()
        later_tiles, later_pages = build.prepare_later_pages()
        self.assertEqual((first_pages[0x1348D][0], first_tiles["静"]), (1, 0x81))
        self.assertEqual((later_pages[0x13545][0], later_tiles["常"]), (1, 0x81))
        self.assertEqual(later_pages[0x13558][:3], bytes.fromhex("80 7D 3B"))
        self.assertEqual(later_pages[0x1358B][0], 1)
        for high, cursor, marker, tile, loader in (
            (0x34, 0x8E, 0x8B, 0x81, 0x4100),
            (0x35, 0x46, 0x8C, 0x81, 0x4200),
            (0x35, 0x5B, 0x8C, 0xBB, 0x4200),
            (0x35, 0x8C, 0x8C, 0x81, 0x4200),
        ):
            with self.subTest(cursor=cursor):
                result, b, memory, calls = self.run_dispatch(4, high, cursor, 0)
                self.assertEqual((result, b, memory[0xC4F2], memory[0xC4F0], calls),
                                 (1, 0xCD, marker, tile, [loader]))
                self.assertEqual(self.run_dispatch(4, high, cursor, 0x89)[3], [])
                self.assertEqual(self.run_dispatch(5, high, cursor, 0)[3], [])
                self.assertEqual(self.run_dispatch(4, high, cursor + 1, 0)[3], [])


class RestoreDispatcherTests(unittest.TestCase):
    def run_dispatch(self, bank, high, cursor, marker):
        code = build.build_restore_dispatcher(0x4A5E, 0x4D00)
        memory = bytearray(0x10000)
        memory[0xFFAA], memory[0xFFAE], memory[0xFFAD] = bank, high, cursor
        memory[0xC4F2] = marker
        calls = []
        pc = a = 0
        zero = False
        for _ in range(100):
            op = code[pc]
            pc += 1
            if op == 0xCD:
                calls.append(int.from_bytes(code[pc:pc + 2], "little"))
                pc += 2
            elif op == 0xFA:
                address = int.from_bytes(code[pc:pc + 2], "little")
                pc += 2
                a = memory[address]
            elif op == 0xFE:
                zero = a == code[pc]
                pc += 1
            elif op == 0x20:
                delta = int.from_bytes(code[pc:pc + 1], "little", signed=True)
                pc += 1
                if not zero:
                    pc += delta
            elif op == 0xAF:
                a, zero = 0, True
            elif op == 0xEA:
                address = int.from_bytes(code[pc:pc + 2], "little")
                pc += 2
                memory[address] = a
            elif op == 0xC9:
                return calls, memory[0xC4F2]
            else:
                self.fail(f"unexpected opcode ${op:02X}")
        self.fail("restore dispatcher did not return")

    def test_only_observed_closes_restore_matching_marker(self):
        for cursor, marker in ((0x17, 0x8B), (0x78, 0x8C), (0xAC, 0x8C)):
            with self.subTest(cursor=cursor):
                self.assertEqual(self.run_dispatch(4, 0x35, cursor, marker), ([0x4A5E, 0x4D00], 0))
                self.assertEqual(self.run_dispatch(4, 0x35, cursor, 0x89), ([0x4A5E], 0x89))
                self.assertEqual(self.run_dispatch(5, 0x35, cursor, marker), ([0x4A5E], marker))
        self.assertEqual(self.run_dispatch(4, 0x35, 0x53, 0x8C), ([0x4A5E], 0x8C))

    def test_install_targets_expected_gateway_and_fits(self):
        target = bytearray(previous.OUTPUT_ROM.read_bytes())
        font = decode_resource(SOURCE_ROM.read_bytes(), FONT_BANK, FONT_DESCRIPTOR, FONT_LENGTH)
        components = build.install_glyph_components(target, font)
        build.install_dispatchers(target, components)
        self.assertEqual(int.from_bytes(target[build.LOAD_GATE_OFFSET + 1:build.LOAD_GATE_OFFSET + 3], "little"),
                         build.bank_cpu_address(build.NEW_LOAD_DISPATCH_OFFSET))
        self.assertEqual(int.from_bytes(target[build.RESTORE_WRAPPER_OFFSET + 2:build.RESTORE_WRAPPER_OFFSET + 4], "little"),
                         build.bank_cpu_address(build.NEW_RESTORE_DISPATCH_OFFSET))
        with self.assertRaises(ValueError):
            build.install_dispatchers(target, components)


class CompactGlyphTests(unittest.TestCase):
    def test_compact_copy_preserves_registers_and_writes_two_planes(self):
        patterns = {0x81: bytes(range(8)), 0xBF: bytes(range(8, 16))}
        expanded = {tile: bytes(value for row in rows for value in (row, row))
                    for tile, rows in patterns.items()}
        table = build.encode_compact_glyph_table(expanded)
        code = build.build_compact_copy_helper()
        memory = bytearray(0x10000)
        memory[0x4000:0x4000 + len(table)] = table
        a, b, c, d, e, h, l = 0x31, 2, 0x33, 0x44, 0x55, 0x40, 0
        initial = a, b, c, d, e, h, l
        stack = []
        zero = False
        pc = 0
        stat_reads = 0
        writes = 0
        for _ in range(1000):
            op = code[pc]
            pc += 1
            if op in (0xC5, 0xD5, 0xE5, 0xF5):
                stack.append({0xC5: (b, c), 0xD5: (d, e), 0xE5: (h, l), 0xF5: (a, zero)}[op])
            elif op in (0xC1, 0xD1, 0xE1, 0xF1):
                value = stack.pop()
                if op == 0xC1:
                    b, c = value
                elif op == 0xD1:
                    d, e = value
                elif op == 0xE1:
                    h, l = value
                else:
                    a, zero = value
            elif op == 0x2A:
                address = (h << 8) | l
                a = memory[address]
                h, l = divmod(address + 1, 256)
            elif op == 0x5F:
                e = a
            elif op == 0x57:
                d = a
            elif op == 0x0E:
                c = code[pc]
                pc += 1
            elif op == 0xF0:
                a = memory[0xFF00 + code[pc]]
                if code[pc] == 0x41:
                    stat_reads += 1
                    if stat_reads % 2:
                        a = 2
                pc += 1
            elif op == 0xE6:
                a &= code[pc]
                zero = a == 0
                pc += 1
            elif op == 0x20:
                delta = int.from_bytes(code[pc:pc + 1], "little", signed=True)
                pc += 1
                if not zero:
                    pc += delta
            elif op == 0x12:
                self.assertEqual(stat_reads % 2, 0)
                writes += 1
                memory[(d << 8) | e] = a
            elif op == 0x13:
                d, e = divmod(((d << 8) | e) + 1, 256)
            elif op == 0x0D:
                c = (c - 1) & 0xFF
                zero = c == 0
            elif op == 0x05:
                b = (b - 1) & 0xFF
                zero = b == 0
            elif op == 0xC9:
                break
            else:
                self.fail(f"unexpected opcode ${op:02X}")
        else:
            self.fail("compact copy did not return")
        self.assertEqual((a, b, c, d, e, h, l), initial)
        self.assertFalse(stack)
        self.assertEqual(writes, 32)
        self.assertEqual(stat_reads, 64)
        for tile, pattern in expanded.items():
            address = 0x8800 + (tile - 0x80) * 16
            self.assertEqual(memory[address:address + 16], pattern)

    def test_rejects_nonidentical_bitplanes(self):
        with self.assertRaises(ValueError):
            build.encode_compact_glyph_table({0xBF: bytes(range(16))})

    def test_original_patterns_preserve_both_bitplanes(self):
        tiles = set(build.prepare_first_pages()[0].values())
        font = decode_resource(SOURCE_ROM.read_bytes(), FONT_BANK, FONT_DESCRIPTOR, FONT_LENGTH)
        compact, full = build.split_original_patterns(tiles, font)
        self.assertEqual(set(compact) | set(full), tiles)
        self.assertIn(0xBF, full)
        packed = build.encode_compact_glyph_table(compact)
        for i, tile in enumerate(compact):
            entry = packed[10 * i:10 * i + 10]
            restored = bytes(value for row in entry[2:] for value in (row, row))
            self.assertEqual(restored, font[(tile - 0x80) * 16:(tile - 0x7F) * 16])
        for tile, pattern in full.items():
            self.assertEqual(pattern, font[(tile - 0x80) * 16:(tile - 0x7F) * 16])

    def test_installed_tables_load_and_restore_exact_patterns(self):
        import json

        parent = previous.OUTPUT_ROM.read_bytes()
        rom = bytearray(parent)
        font = decode_resource(SOURCE_ROM.read_bytes(), FONT_BANK, FONT_DESCRIPTOR, FONT_LENGTH)
        offsets = build.install_glyph_components(rom, font)
        asset = json.loads((build.ROOT / "data" / "chinese_glyphs_oni5_v264_dialogues.json").read_text())
        first, _ = build.prepare_first_pages()
        later, _ = build.prepare_later_pages()
        patterns = load_glyph_patterns((asset,), list(dict.fromkeys((*first, *later))))
        memory = bytearray(0x10000)
        for label, mapping in (("first", first), ("restore", first), ("later", later), ("restore", later)):
            pc = offsets[label]
            self.assertEqual(rom[pc:pc + 4], bytes.fromhex("C5 D5 E5 F5"))
            pc += 4
            while rom[pc] == 0x21:
                address = int.from_bytes(rom[pc + 1:pc + 3], "little")
                if rom[pc + 3] == 0x06:
                    count = rom[pc + 4]
                    self.assertEqual(rom[pc + 5], 0xCD)
                    self.assertEqual(int.from_bytes(rom[pc + 6:pc + 8], "little"),
                                     build.bank_cpu_address(offsets["copy"]))
                    table = build.SOURCE_SIZE + address - 0x4000
                    for i in range(count):
                        entry = rom[table + i * 10:table + i * 10 + 10]
                        destination = int.from_bytes(entry[:2], "little")
                        memory[destination:destination + 16] = bytes(
                            value for row in entry[2:] for value in (row, row)
                        )
                    pc += 8
                else:
                    self.assertEqual(rom[pc + 3], 0x11)
                    destination = int.from_bytes(rom[pc + 4:pc + 6], "little")
                    self.assertEqual(rom[pc + 6:pc + 12], bytes.fromhex("01 10 00 CD 21 05"))
                    source = build.SOURCE_SIZE + address - 0x4000
                    memory[destination:destination + 16] = rom[source:source + 16]
                    pc += 12
            self.assertEqual(rom[pc:pc + 5], bytes.fromhex("F1 E1 D1 C1 C9"))
            for character, tile in mapping.items():
                address = build.tile_vram_address(tile)
                expected = (font[(tile - 0x80) * 16:(tile - 0x7F) * 16]
                            if label == "restore" else patterns[character])
                self.assertEqual(memory[address:address + 16], expected)
        for index, (before, after) in enumerate(zip(parent, rom)):
            if before != after:
                self.assertTrue(any(start <= index < end for start, end in build.COMPONENT_RANGES))


if __name__ == "__main__":
    unittest.main()
