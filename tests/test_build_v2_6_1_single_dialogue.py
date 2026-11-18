import hashlib
import unittest

from scripts import build_v2_6_1_single_dialogue as build_single
from scripts.apply_bps_patch import apply_bps_patch
from scripts.build_v2_6_prologue_patch import (
    ADDITIONAL_DIALOGUE_SPAN,
    EXPECTED_V2_6_SHA256,
)
from scripts.rom_checksums import verify_rom


class BuildV261SingleDialogueTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.base = build_single.BASE_ROM.read_bytes()
        cls.target, cls.patch, cls.version = build_single.build()

    def test_patch_is_based_on_accepted_v26_and_round_trips(self):
        self.assertEqual(hashlib.sha256(self.base).hexdigest(), EXPECTED_V2_6_SHA256)
        self.assertEqual(apply_bps_patch(self.base, self.patch), self.target)
        self.assertTrue(verify_rom(self.target).passed)

    def test_only_the_confirmed_dialogue_is_translated(self):
        start, end = ADDITIONAL_DIALOGUE_SPAN
        translated = self.target[start:end]

        self.assertEqual(len(translated), end - start)
        self.assertEqual(translated[0], 0x95)
        self.assertIn(0xAD, translated)
        self.assertEqual(
            build_single.MACROS,
            {"常叶丸": (0x95, 3), "{静那}": (0xAD, 3)},
        )
        self.assertEqual(self.target[end], 0x7F)
        for offset, length in ((0x013411, 0x20), (0x01348F, 0x1C), (0x013545, 0x0D)):
            self.assertEqual(
                self.target[offset:offset + length],
                self.base[offset:offset + length],
            )
        self.assertEqual(
            self.target[0x80000 + start:0x80000 + end],
            translated,
        )

    def test_loader_covers_the_wrapped_text_pointer_until_terminator(self):
        dispatcher = self.target[
            build_single.LOAD_DISPATCHER_OFFSET:
            build_single.LOAD_DISPATCHER_OFFSET + 53
        ]
        self.assertEqual(dispatcher[:5], bytes.fromhex("FA AA FF FE 04"))
        self.assertEqual(dispatcher[7:12], bytes.fromhex("FA AE FF FE 33"))
        self.assertEqual(dispatcher[14:19], bytes.fromhex("FA AD FF FE EF"))
        self.assertEqual(dispatcher[23:29], bytes.fromhex("FA AE FF FE 34 20"))
        self.assertEqual(dispatcher[30:35], bytes.fromhex("FA AD FF FE 09"))

        def branch_target(offset):
            displacement = dispatcher[offset + 1]
            if displacement >= 0x80:
                displacement -= 0x100
            return offset + 2 + displacement

        self.assertEqual(branch_target(19), 51)
        self.assertEqual(branch_target(21), 37)
        self.assertEqual(branch_target(35), 51)

    def test_existing_v26_restore_path_is_preserved(self):
        self.assertEqual(
            self.target[build_single.SOURCE_SIZE + 0x60:
                        build_single.SOURCE_SIZE + 0x63],
            bytes((0xC3,)) + build_single.bank_cpu_address(
                build_single.RESTORE_WRAPPER_OFFSET
            ).to_bytes(2, "little"),
        )
        self.assertEqual(
            self.target[
                build_single.OLD_RESTORE_WRAPPER_OFFSET:
                build_single.OLD_RESTORE_WRAPPER_OFFSET + 16
            ],
            bytes.fromhex("F5 FA F2 C4 FE 87 20 04 F1 C3 00 71 F1 C3 B0 48"),
        )
        router = self.target[
            build_single.RESTORE_WRAPPER_OFFSET:
            build_single.RESTORE_WRAPPER_OFFSET + 26
        ]
        self.assertEqual(
            router[:16],
            bytes.fromhex("F5 FA F2 C4 FE 85 20 0E FA AD FF FE 08 20 07 CD"),
        )
        self.assertEqual(8 + router[7], 22)
        self.assertEqual(15 + router[14], 22)
        self.assertEqual(
            router[22:26],
            bytes.fromhex("F1 C3")
            + build_single.bank_cpu_address(
                build_single.OLD_RESTORE_WRAPPER_OFFSET
            ).to_bytes(2, "little"),
        )
        helper_address = int.from_bytes(router[16:18], "little")
        helper_offset = (
            build_single.SOURCE_SIZE + helper_address - 0x4000
        )
        self.assertEqual(
            self.target[helper_offset + 11:helper_offset + 17],
            bytes.fromhex("FA AD FF FE 08 C2"),
        )
        self.assertEqual(
            self.version["text_records"],
            [build_single.RECORD_ID],
        )


if __name__ == "__main__":
    unittest.main()
