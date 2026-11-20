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

    def test_all_dialogues_keep_their_control_boundaries(self):
        start, end = ADDITIONAL_DIALOGUE_SPAN
        translated = self.target[start:end]
        reply_start, reply_end = build_single.REPLY_TEXT_SPAN
        reply = self.target[reply_start:reply_end]
        tokiwa_start, tokiwa_end = build_single.TOKIWA_TEXT_SPAN
        tokiwa = self.target[tokiwa_start:tokiwa_end]

        self.assertEqual(len(translated), end - start)
        self.assertNotIn(0x95, translated)
        self.assertEqual(translated[3], 0x7D)
        self.assertEqual(translated[4], 0x3B)
        self.assertNotIn(0xAD, translated)
        self.assertEqual(
            build_single.FIXED_NAME_TRANSLATIONS,
            {"{静那}": "静那"},
        )
        self.assertEqual(self.target[end], 0x7F)
        self.assertEqual(len(reply), reply_end - reply_start)
        self.assertNotIn(0xAD, reply)
        self.assertEqual(reply[2], 0x7D)
        self.assertEqual(reply[3], 0x3B)
        self.assertEqual(reply[17], 0x7D)
        self.assertEqual(reply[24], 0x3E)
        self.assertEqual(reply[25], 0x3C)
        self.assertEqual(self.target[reply_end], 0x7F)
        self.assertEqual(
            self.target[reply_end + 1:0x013457],
            self.base[reply_end + 1:0x013457],
        )
        self.assertEqual(
            self.target[0x01348D:0x0134AA],
            self.base[0x01348D:0x0134AA],
        )
        self.assertEqual(len(tokiwa), tokiwa_end - tokiwa_start)
        self.assertNotIn(0x95, tokiwa)
        self.assertEqual(tokiwa[3], 0x7D)
        self.assertEqual(tokiwa[4], 0x3B)
        self.assertEqual(tokiwa[11], 0x3E)
        self.assertEqual(tokiwa[12], 0x3C)
        self.assertEqual(self.target[tokiwa_end], 0x7E)
        self.assertEqual(
            self.target[tokiwa_end + 1:0x01347C],
            self.base[tokiwa_end + 1:0x01347C],
        )
        for offset, length in ((0x013411, 0x1D), (0x013545, 0x0D)):
            self.assertEqual(
                self.target[offset:offset + length],
                self.base[offset:offset + length],
            )
        self.assertEqual(
            self.target[0x80000 + start:0x80000 + end],
            translated,
        )
        self.assertEqual(
            self.target[0x80000 + reply_start:0x80000 + reply_end],
            reply,
        )
        self.assertEqual(
            self.target[0x80000 + tokiwa_start:0x80000 + tokiwa_end],
            tokiwa,
        )

    def test_loader_dispatches_all_dialogue_contexts(self):
        dispatcher = self.target[
            build_single.LOAD_DISPATCHER_OFFSET:
            build_single.LOAD_DISPATCHER_OFFSET + 140
        ]
        self.assertEqual(dispatcher[:5], bytes.fromhex("FA AA FF FE 04"))
        self.assertEqual(dispatcher[7:12], bytes.fromhex("FA AE FF FE 33"))
        self.assertEqual(dispatcher[14:19], bytes.fromhex("FA AD FF FE EF"))
        self.assertEqual(dispatcher[23:29], bytes.fromhex("FA AE FF FE 34 20"))
        self.assertEqual(dispatcher[30:35], bytes.fromhex("FA AD FF FE 09"))
        self.assertEqual(
            dispatcher[37:46],
            bytes.fromhex("FA F2 C4 FE 85 20 02 AF C9"),
        )
        self.assertEqual(dispatcher[52:57], bytes.fromhex("FA AA FF FE 04"))
        self.assertEqual(dispatcher[59:64], bytes.fromhex("FA AE FF FE 34"))
        self.assertEqual(dispatcher[66:71], bytes.fromhex("FA AD FF FE 2E"))
        self.assertEqual(dispatcher[73:78], bytes.fromhex("FA AD FF FE 53"))
        self.assertEqual(
            dispatcher[80:89],
            bytes.fromhex("FA F2 C4 FE 88 20 02 AF C9"),
        )
        self.assertEqual(dispatcher[95:100], bytes.fromhex("FA AA FF FE 04"))
        self.assertEqual(dispatcher[102:107], bytes.fromhex("FA AE FF FE 34"))
        self.assertEqual(dispatcher[109:114], bytes.fromhex("FA AD FF FE 59"))
        self.assertEqual(dispatcher[116:121], bytes.fromhex("FA AD FF FE 6E"))
        self.assertEqual(
            dispatcher[123:132],
            bytes.fromhex("FA F2 C4 FE 89 20 02 AF C9"),
        )
        self.assertEqual(dispatcher[-2:], bytes.fromhex("AF C9"))

        def branch_target(offset):
            displacement = dispatcher[offset + 1]
            if displacement >= 0x80:
                displacement -= 0x100
            return offset + 2 + displacement

        self.assertEqual(branch_target(19), 52)
        self.assertEqual(branch_target(21), 37)
        self.assertEqual(branch_target(35), 52)
        for offset in (57, 64, 71):
            self.assertEqual(branch_target(offset), 138)
        self.assertEqual(branch_target(78), 95)
        for offset in (100, 107, 114, 121):
            self.assertEqual(branch_target(offset), 138)
        self.assertEqual(
            self.target[build_single.LOAD_GATE_OFFSET:build_single.LOAD_GATE_OFFSET + 8],
            bytes.fromhex("CD")
            + build_single.bank_cpu_address(
                build_single.LOAD_DISPATCHER_OFFSET
            ).to_bytes(2, "little")
            + bytes.fromhex("B7 C0 C3 30 40"),
        )

    def test_all_custom_contexts_restore_before_the_original_v26_path(self):
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
            build_single.RESTORE_WRAPPER_OFFSET + 8
        ]
        self.assertEqual(
            router[:2],
            bytes.fromhex("F5 CD"),
        )
        self.assertEqual(
            router[4:],
            bytes.fromhex("F1 C3")
            + build_single.bank_cpu_address(
                build_single.OLD_RESTORE_WRAPPER_OFFSET
            ).to_bytes(2, "little"),
        )
        dispatcher_address = int.from_bytes(router[2:4], "little")
        dispatcher_offset = (
            build_single.SOURCE_SIZE + dispatcher_address - 0x4000
        )
        restore_dispatcher = self.target[dispatcher_offset:dispatcher_offset + 46]
        self.assertIn(bytes.fromhex("FE 85"), restore_dispatcher)
        self.assertIn(bytes.fromhex("FA AD FF FE 08"), restore_dispatcher)
        self.assertIn(bytes.fromhex("FE 88"), restore_dispatcher)
        self.assertIn(bytes.fromhex("FA AD FF FE 53"), restore_dispatcher)
        self.assertIn(bytes.fromhex("FE 89"), restore_dispatcher)
        self.assertIn(bytes.fromhex("FA AD FF FE 6E"), restore_dispatcher)

        for call_offset, marker, cursor in (
            (14, 0x85, 0x08),
            (28, 0x88, 0x53),
            (42, 0x89, 0x6E),
        ):
            helper_address = int.from_bytes(
                restore_dispatcher[call_offset + 1:call_offset + 3],
                "little",
            )
            helper_offset = build_single.SOURCE_SIZE + helper_address - 0x4000
            self.assertIn(
                bytes((marker,)),
                self.target[helper_offset:helper_offset + 10],
            )
            self.assertEqual(
                self.target[helper_offset + 11:helper_offset + 17],
                bytes((0xFA, 0xAD, 0xFF, 0xFE, cursor, 0xC2)),
            )
        self.assertEqual(
            self.version["text_records"],
            [
                build_single.RECORD_ID,
                build_single.REPLY_RECORD_ID,
                build_single.TOKIWA_RECORD_ID,
            ],
        )


if __name__ == "__main__":
    unittest.main()
