import hashlib
import unittest

from scripts import build_v2_6_3_dialogue as build
from scripts.apply_bps_patch import apply_bps_patch
from scripts.rom_checksums import verify_rom
from test_build_v2_6_2_dialogue import run_glyph_helper


def run_dispatcher(rom, address, memory, loader, restore):
    """Execute the dispatcher and wrapper, using the existing glyph-helper harness."""
    a, zero = 0x5A, False
    b = c = d = e = h = l = 0
    stack = []
    events = []
    helper_addresses = {0x75C0, 0x79E0, 0x6800, loader, restore}

    def run(pc):
        nonlocal a, b, c, d, e, h, l, zero
        if pc == 0x75D3:
            events.append(pc)
        if pc in helper_addresses:
            events.append(pc)
            run_glyph_helper(rom, build.SOURCE_SIZE + pc - 0x4000, memory)
            if pc == loader:
                a, zero = build.GLYPH_TILES[0][1] - 0x80, False
            return
        pc = build.SOURCE_SIZE + pc - 0x4000
        for _ in range(500):
            op = rom[pc]
            pc += 1
            if op == 0xFA:
                target = int.from_bytes(rom[pc:pc + 2], "little")
                pc += 2
                a = memory[target]
            elif op == 0xF0:
                a = memory[0xFF00 + rom[pc]]
                pc += 1
            elif op == 0xEA:
                target = int.from_bytes(rom[pc:pc + 2], "little")
                pc += 2
                memory[target] = a
            elif op == 0xFE:
                zero = a == rom[pc]
                pc += 1
            elif op == 0x20:
                displacement = int.from_bytes(rom[pc:pc + 1], "little", signed=True)
                pc += 1
                if not zero:
                    pc += displacement
            elif op in (0xC5, 0xD5, 0xE5, 0xF5):
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
            elif op in (0x21, 0x11, 0x01):
                low, high = rom[pc:pc + 2]
                pc += 2
                if op == 0x21:
                    h, l = high, low
                elif op == 0x11:
                    d, e = high, low
                else:
                    b, c = high, low
            elif op == 0xAF:
                a, zero = 0, True
            elif op in (0xCD, 0xC3, 0xCA, 0xC2):
                target = int.from_bytes(rom[pc:pc + 2], "little")
                pc += 2
                if (op != 0xCA or zero) and (op != 0xC2 or not zero):
                    if target == 0x0521:
                        source, destination, length = (h << 8) | l, (d << 8) | e, (b << 8) | c
                        if not 0x4000 <= source < 0x8000 or length != 16:
                            raise AssertionError("unexpected previous-restore copy")
                        offset = build.SOURCE_SIZE + source - 0x4000
                        memory[destination:destination + length] = rom[offset:offset + length]
                    else:
                        run(target)
                    if op in (0xC3, 0xCA, 0xC2):
                        return
            elif op == 0xC0:
                if not zero:
                    return
            elif op == 0xC9:
                return
            else:
                raise AssertionError(f"unexpected dispatcher opcode ${op:02X}")
        raise AssertionError("dispatcher did not return")

    run(address)
    if stack:
        raise AssertionError("dispatcher left an unbalanced stack")
    return events


class BuildV263DialogueTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.parent = build.V2_6_2_ROM.read_bytes()
        cls.target, cls.patch, cls.version = build.build()
        cls.details = cls.version["implementation"]
        cls.loader = build.bank_cpu_address(int(cls.details["loader_offset"], 16))
        cls.restore = build.bank_cpu_address(int(cls.details["restore_offset"], 16))
        cls.dispatcher = build.bank_cpu_address(int(cls.details["dispatcher_offset"], 16))
        cls.old_dispatcher = int.from_bytes(
            cls.parent[build.RESTORE_WRAPPER_OFFSET + 2:build.RESTORE_WRAPPER_OFFSET + 4], "little"
        )

    def test_patch_and_original_macros(self):
        self.assertEqual(hashlib.sha256(self.parent).hexdigest(), build.EXPECTED_V2_6_2_SHA256)
        self.assertEqual(apply_bps_patch(self.parent, self.patch), self.target)
        self.assertTrue(verify_rom(self.target).passed)
        self.assertEqual(self.target[build.TEXT_START - 1:build.TEXT_START + 6],
                         bytes.fromhex("7C C6 7D 3B B6 CC 7F"))
        mapping = {tile - 0x80: character for character, tile in build.GLYPH_TILES}
        name = "".join(mapping[code] for code in build._read_macro(self.target, 0xC6))
        other_name = "".join(mapping[code] for code in build._read_macro(self.target, 0xB6))
        self.assertEqual(name + "\n「" + other_name, "静那\n「常叶丸")
        self.assertEqual(build._read_macro(self.target, 0xCC), bytes.fromhex("4B 4A 3C"))
        self.assertEqual(self.target[0x1709:0x1714], self.parent[0x1709:0x1714])
        self.assertEqual(self.target[0x30000:0x34000], self.parent[0x30000:0x34000])
        previous_tiles = {0x80 + code for code in self.parent[0x133EF:0x13408] if code < 0x40}
        self.assertTrue(previous_tiles.isdisjoint(tile for _, tile in build.GLYPH_TILES))

    def test_changed_bytes_are_restricted_to_dialogue_and_local_helpers(self):
        ranges = [
            (0x14E, 0x150),
            (build.TEXT_START, build.TEXT_START + len(build.TRANSLATED_TEXT)),
            (build.RESTORE_WRAPPER_OFFSET + 2, build.RESTORE_WRAPPER_OFFSET + 4),
            (build.HELPER_START, int(self.details["helper_end"], 16)),
        ]
        ranges += [(start + build.MBC1_MIRROR_OFFSET, end + build.MBC1_MIRROR_OFFSET)
                   for start, end in ranges if start >= build.TEXT_START]
        for offset, (before, after) in enumerate(zip(self.parent, self.target)):
            if before != after:
                self.assertTrue(any(start <= offset < end for start, end in ranges),
                                f"unexpected change at ${offset:06X}")

    def test_preload_and_restore_follow_existing_dialogue_restore(self):
        memory = bytearray(0x10000)
        memory[0xC4F2] = 0x85
        memory[0xC4F0] = 0x51
        memory[0xFFAA] = 0x04
        memory[0xFFAE] = 0x34
        memory[0xFFAD] = 0x09
        previous_memory = bytearray(memory)
        previous_memory[0xFFAD] = 0x08
        run_dispatcher(self.parent, self.old_dispatcher, previous_memory, self.loader, self.restore)
        events = run_dispatcher(self.target, self.dispatcher, memory, self.loader, self.restore)
        self.assertEqual(events, [0x75D3, self.loader])
        self.assertEqual(memory[0xC4F2], build.MARKER)
        self.assertEqual(memory[0xC4F0], 0x51)
        patterns = int(self.details["pattern_offset"], 16)
        originals = int(self.details["original_pattern_offset"], 16)
        new_addresses = {0x8000 + tile * 16 + byte for _, tile in build.GLYPH_TILES for byte in range(16)}
        for address in range(0x8000, 0x9800):
            if address not in new_addresses:
                self.assertEqual(memory[address], previous_memory[address], f"previous restoration differs at ${address:04X}")
        for index, (_, tile) in enumerate(build.GLYPH_TILES):
            address = 0x8000 + tile * 16
            self.assertEqual(memory[address:address + 16], self.target[patterns + index * 16:patterns + (index + 1) * 16])
        memory[0xFFAD] = build.RESTORE_CURSOR - 1
        self.assertEqual(run_dispatcher(self.target, self.dispatcher, memory, self.loader, self.restore), [])
        self.assertEqual(memory[0xC4F2], build.MARKER)
        memory[0xFFAD] = build.RESTORE_CURSOR
        self.assertEqual(run_dispatcher(self.target, self.dispatcher, memory, self.loader, self.restore), [self.restore])
        self.assertEqual(memory[0xC4F2], 0)
        for index, (_, tile) in enumerate(build.GLYPH_TILES):
            address = 0x8000 + tile * 16
            self.assertEqual(memory[address:address + 16], self.target[originals + index * 16:originals + (index + 1) * 16])

    def test_other_contexts_follow_parent_dispatcher(self):
        cases = (
            (0x00, 0x04, 0x34, 0x08),
            (0x85, 0x03, 0x34, 0x09),
            (0x85, 0x04, 0x33, 0x09),
            (0x85, 0x04, 0x34, 0x08),
            (0x85, 0x04, 0x34, 0x0A),
            (0x88, 0x04, 0x34, 0x53),
            (0x89, 0x04, 0x34, 0x7C),
            (build.MARKER, 0x0C, 0x34, build.RESTORE_CURSOR),
            (build.MARKER, 0x04, 0x35, build.RESTORE_CURSOR),
        )
        for marker, bank, high, cursor in cases:
            with self.subTest(marker=marker, bank=bank, high=high, cursor=cursor):
                parent_memory = bytearray(0x10000)
                parent_memory[0xC4F2] = marker
                parent_memory[0xC4F0] = 0x51
                parent_memory[0xFFAA] = bank
                parent_memory[0xFFAE] = high
                parent_memory[0xFFAD] = cursor
                target_memory = bytearray(parent_memory)
                run_dispatcher(self.parent, self.old_dispatcher, parent_memory, self.loader, self.restore)
                events = run_dispatcher(self.target, self.dispatcher, target_memory, self.loader, self.restore)
                self.assertNotIn(self.loader, events)
                self.assertNotIn(self.restore, events)
                self.assertEqual(target_memory, parent_memory)


if __name__ == "__main__":
    unittest.main()
