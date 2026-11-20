import hashlib
import unittest

from scripts import build_v2_6_2_dialogue as build
from scripts.apply_bps_patch import apply_bps_patch
from scripts.rom_checksums import verify_rom


def run_glyph_helper(rom, address, memory):
    """Execute the glyph helpers' instructions, substituting the 16-byte copy routine."""
    pc = address
    a = b = c = d = e = h = l = 0
    zero = False
    stack = []
    for _ in range(500):
        opcode = rom[pc]
        pc += 1
        if opcode in (0xC5, 0xD5, 0xE5, 0xF5):
            stack.append({0xC5: (b, c), 0xD5: (d, e), 0xE5: (h, l), 0xF5: (a, zero)}[opcode])
        elif opcode in (0xC1, 0xD1, 0xE1, 0xF1):
            value = stack.pop()
            if opcode == 0xC1:
                b, c = value
            elif opcode == 0xD1:
                d, e = value
            elif opcode == 0xE1:
                h, l = value
            else:
                a, zero = value
        elif opcode in (0x21, 0x11, 0x01):
            low, high = rom[pc:pc + 2]
            pc += 2
            if opcode == 0x21:
                h, l = high, low
            elif opcode == 0x11:
                d, e = high, low
            else:
                b, c = high, low
        elif opcode == 0xCD:
            target = int.from_bytes(rom[pc:pc + 2], "little")
            pc += 2
            if target != 0x0521:
                raise AssertionError(f"unexpected helper call ${target:04X}")
            src, dst, length = (h << 8) | l, (d << 8) | e, (b << 8) | c
            if not 0x4000 <= src < 0x8000 or length != 16:
                raise AssertionError("unexpected helper copy")
            offset = build.SOURCE_SIZE + src - 0x4000
            memory[dst:dst + length] = rom[offset:offset + length]
        elif opcode == 0x3E:
            a = rom[pc]
            pc += 1
        elif opcode == 0x06:
            b = rom[pc]
            pc += 1
        elif opcode == 0xEA:
            target = int.from_bytes(rom[pc:pc + 2], "little")
            pc += 2
            memory[target] = a
        elif opcode == 0xFA:
            target = int.from_bytes(rom[pc:pc + 2], "little")
            pc += 2
            a = memory[target]
        elif opcode == 0xFE:
            zero = a == rom[pc]
            pc += 1
        elif opcode == 0xC2:
            target = int.from_bytes(rom[pc:pc + 2], "little")
            pc += 2
            if not zero:
                pc = build.SOURCE_SIZE + target - 0x4000
        elif opcode == 0xAF:
            a, zero = 0, True
        elif opcode == 0xC9:
            if stack:
                raise AssertionError("helper left an unbalanced stack")
            return
        else:
            raise AssertionError(f"unexpected opcode ${opcode:02X}")
    raise AssertionError("glyph helper did not return")


class BuildV262DialogueTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.parent = build.V2_6_1_ROM.read_bytes()
        cls.target, cls.patch, cls.version = build.build()
        cls.details = cls.version["implementation"]

    def test_patch_uses_exact_parent_and_round_trips(self):
        self.assertEqual(hashlib.sha256(self.parent).hexdigest(), build.EXPECTED_V2_6_1_SHA256)
        self.assertEqual(apply_bps_patch(self.parent, self.patch), self.target)
        self.assertTrue(verify_rom(self.target).passed)

    def test_followup_expands_to_requested_text(self):
        start, end = build.SHIZUNA_FOLLOWUP_TEXT_SPAN
        glyphs = {int(tile, 16) - 0x80: character for character, tile in self.details["glyph_tiles"].items()}
        encoded = self.target[start:end]
        output = []
        for byte in encoded:
            if byte == 0x7D:
                output.append("\n")
            elif byte == 0x3B:
                output.append("「")
            elif byte == 0xD2:
                bank = 0x0C * 0x4000
                pointer = int.from_bytes(self.target[bank + 0x2A4:bank + 0x2A6], "little")
                length = self.target[bank + pointer]
                self.assertEqual(self.target[bank + pointer + 1:bank + pointer + 1 + length], b"\x4b\x3c")
                output.append("！」")
            else:
                output.append(glyphs[byte])
        self.assertEqual("".join(output), "静那\n「常叶丸你这家伙！」")
        self.assertEqual(self.target[start - 1], 0x7C)
        self.assertEqual(self.target[end], 0x7F)
        self.assertEqual(self.target[end:0x01348D], self.parent[end:0x01348D])

    def test_changes_are_confined_to_followup_and_its_glyph_helpers(self):
        start, end = build.SHIZUNA_FOLLOWUP_TEXT_SPAN
        router = self.parent[build.RESTORE_WRAPPER_OFFSET:build.RESTORE_WRAPPER_OFFSET + 8]
        restore_dispatcher = build.SOURCE_SIZE + int.from_bytes(router[2:4], "little") - 0x4000
        ranges = [
            (0x14E, 0x150),
            (start, end),
            (build.LOAD_DISPATCHER_OFFSET + 120, build.LOAD_DISPATCHER_OFFSET + 121),
            (build.LOAD_DISPATCHER_OFFSET + 133, build.LOAD_DISPATCHER_OFFSET + 135),
            (restore_dispatcher + 39, restore_dispatcher + 40),
            (restore_dispatcher + 43, restore_dispatcher + 45),
            (build.HELPER_START, int(self.details["helper_end"], 16)),
        ]
        ranges += [(a + build.MBC1_MIRROR_OFFSET, b + build.MBC1_MIRROR_OFFSET)
                   for a, b in ranges if a >= start]
        for offset, (before, after) in enumerate(zip(self.parent, self.target)):
            if before != after:
                self.assertTrue(any(a <= offset < b for a, b in ranges), f"unexpected change at ${offset:06X}")
        self.assertEqual(self.target[0x1709:0x1714], self.parent[0x1709:0x1714])
        self.assertEqual(self.target[slice(*build.TOKIWA_TEXT_SPAN)], self.parent[slice(*build.TOKIWA_TEXT_SPAN)])

    def test_glyph_helper_loads_and_restores_at_the_end_of_both_pages(self):
        memory = bytearray(0x10000)
        loader = int(self.details["loader_offset"], 16)
        restore = int(self.details["restore_offset"], 16)
        patterns = int(self.details["pattern_offset"], 16)
        originals = int(self.details["original_pattern_offset"], 16)
        tiles = [int(value, 16) for value in self.details["glyph_tiles"].values()]
        run_glyph_helper(self.target, loader, memory)
        self.assertEqual(memory[0xC4F2], build.TOKIWA_MARKER)
        for index, tile in enumerate(tiles):
            self.assertEqual(memory[0x8000 + tile * 16:0x8010 + tile * 16],
                             self.target[patterns + index * 16:patterns + (index + 1) * 16])
        memory[0xFFAD] = 0x6E
        run_glyph_helper(self.target, restore, memory)
        self.assertEqual(memory[0xC4F2], build.TOKIWA_MARKER)
        memory[0xFFAD] = build.RESTORE_CURSOR
        run_glyph_helper(self.target, restore, memory)
        self.assertEqual(memory[0xC4F2], 0)
        for index, tile in enumerate(tiles):
            self.assertEqual(memory[0x8000 + tile * 16:0x8010 + tile * 16],
                             self.target[originals + index * 16:originals + (index + 1) * 16])


if __name__ == "__main__":
    unittest.main()
