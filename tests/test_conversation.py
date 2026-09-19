import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
from PIL import Image

from src.config import AppConfig
from src.ocr_engine import TextLine
from src.alignment import LineTiming
from src.reveal import RevealBuilder
from src.text_cleanup import clean_lines


class ConversationTests(unittest.TestCase):
    def fixture(self, count=8):
        cfg = AppConfig(resolution="540x960", fps=30, conversation_chunk_lines=1)
        lines = [TextLine(i, f"Message {i}.", 30, 30 + i * 180, 600, 100) for i in range(count)]
        timings = [LineTiming(i, line.text, i * 2.0, i * 2.0 + 1.5, i * 60, i * 60 + 45)
                   for i, line in enumerate(lines)]
        builder = RevealBuilder(cfg)
        plan = builder.build_plan(lines, timings, (700, count * 180), (474, count * 122))
        return cfg, lines, timings, builder, plan

    def test_all_text_in_order_and_no_future_text_in_crops(self):
        cfg, lines, timings, builder, plan = self.fixture()
        self.assertEqual([i for c in plan.chunks for i in c.line_indices], list(range(8)))
        for chunk, line in zip(plan.chunks, lines):
            self.assertLessEqual(chunk.crop_top, line.y)
            self.assertGreaterEqual(chunk.crop_bottom, line.y + line.height)
        for previous, following in zip(plan.chunks, plan.chunks[1:]):
            self.assertLessEqual(previous.crop_bottom, following.crop_top)

    def test_holds_between_additions_and_keeps_one_stack(self):
        cfg, lines, timings, builder, plan = self.fixture()
        for i, chunk in enumerate(plan.chunks):
            self.assertAlmostEqual(plan.offset_at(i * 2 + 0.4), plan.offset_at(i * 2 + 1.4))
            bottom = plan.offset_at(i * 2 + 0.4) + chunk.stack_top + chunk.height
            self.assertAlmostEqual(bottom, plan.initial_y + plan.chunks[0].height)
        chunk = plan.chunks[2]
        begin = plan.offset_at(chunk.transition_start)
        middle = plan.offset_at(chunk.transition_start + chunk.transition_duration / 2)
        end = plan.offset_at(chunk.transition_start + chunk.transition_duration)
        self.assertGreater(begin, middle)
        self.assertGreater(middle, end)
        self.assertAlmostEqual(begin - end, chunk.shift)
        self.assertLess(plan.offset_at(16) + plan.chunks[0].height, 0)
        for previous, following in zip(plan.chunks, plan.chunks[1:]):
            self.assertEqual(following.stack_top - previous.stack_top - previous.height, cfg.conversation_gap_px)

    def test_gapless_speech_has_bounded_slide_then_hold(self):
        cfg, lines, timings, builder, _ = self.fixture()
        for i, timing in enumerate(timings):
            timing.end_sec = (i + 1) * 2
        plan = builder.build_plan(lines, timings, (700, 1440), (474, 975))
        self.assertEqual(plan.chunks[1].transition_start, 2)
        self.assertLessEqual(plan.chunks[1].transition_duration, 0.32)
        self.assertEqual(plan.offset_at(2.5), plan.offset_at(3.5))

    def test_short_line_after_picture_moves_only_by_new_height(self):
        cfg, lines, timings, builder, _ = self.fixture(3)
        lines[0].y, lines[0].height = 20, 30
        lines[1].y, lines[1].height = 750, 30
        lines[2].y, lines[2].height = 800, 30
        plan = builder.build_plan(lines, timings, (700, 850), (474, 576))
        picture, last = plan.chunks[1:]
        self.assertGreater(picture.height, last.height * 5)
        self.assertEqual(last.shift, last.height + cfg.conversation_gap_px)
        before = plan.offset_at(last.transition_start)
        after = plan.offset_at(last.transition_start + last.transition_duration)
        self.assertAlmostEqual(before - after, last.height + cfg.conversation_gap_px)

    def test_feather_changes_alpha_only_and_preserves_text(self):
        cfg, lines, timings, builder, plan = self.fixture(1)
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "source.png"
            Image.new("RGB", (700, 180), (240, 241, 242)).save(source)
            path = builder.export_chunks(str(source), plan, folder, lines)[0]
            with Image.open(path) as image:
                pixels = np.array(image)
                self.assertEqual(image.width, 474)
                self.assertLessEqual(abs(image.height / image.width -
                                         (plan.chunks[0].crop_bottom - plan.chunks[0].crop_top) / 700), 1 / 474)
            self.assertEqual(pixels[0, 0, 3], 0)
            self.assertTrue(np.any((pixels[:, :, 3] > 0) & (pixels[:, :, 3] < 255)))
            self.assertEqual(pixels[pixels.shape[0] // 2, 200, 3], 255)
            self.assertTrue(np.all(pixels[:, :, :3] == (240, 241, 242)))

    def test_paragraph_and_sentence_grouping(self):
        cfg, lines, timings, builder, _ = self.fixture(4)
        cfg.conversation_chunk_lines = 3
        for i, line in enumerate(lines):
            line.y = 20 + i * 110
            line.text = "continues" if i != 1 else "sentence ends."
        plan = builder.build_plan(lines, timings, (700, 500), (474, 338))
        self.assertEqual([c.line_indices for c in plan.chunks], [(0, 1), (2, 3)])

    def test_touching_chunks_have_opaque_seams(self):
        cfg, lines, timings, builder, plan = self.fixture(3)
        self.assertEqual(plan.gap, 0)
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "source.png"
            Image.new("RGB", (700, 540), "white").save(source)
            paths = builder.export_chunks(str(source), plan, folder, lines)
            for i, path in enumerate(paths):
                with Image.open(path) as image:
                    alpha = np.array(image)[:, :, 3]
                if i > 0:
                    self.assertEqual(alpha[0, 200], 255)
                if i < len(paths) - 1:
                    self.assertEqual(alpha[-1, 200], 255)
                self.assertEqual(alpha[0, 0], 0)
        for previous, following in zip(plan.chunks, plan.chunks[1:]):
            self.assertEqual(previous.stack_top + previous.height, following.stack_top)

    def test_username_cleanup_preserves_visual_records(self):
        raw = [TextLine(0, "@alice_17", 0, 10, 100, 20),
               TextLine(1, "@alice_17 Hello there.", 0, 40, 200, 20)]
        with patch("src.text_cleanup.clean_text", side_effect=lambda text: text):
            spoken = clean_lines(raw)
        self.assertEqual([line.index for line in spoken], [1])
        self.assertNotIn("alice_17", spoken[0].text)
        self.assertEqual(raw[0].text, "@alice_17")
        self.assertEqual(raw[1].text, "@alice_17 Hello there.")
        self.assertIsNot(raw[1], spoken[0])

    def test_complete_screenshot_survives_including_unspoken_media(self):
        raw = [TextLine(0, "@alice_17", 15, 15, 130, 20),
               TextLine(1, "First line.", 15, 50, 180, 25),
               # The large space above this username represents an embedded photo.
               TextLine(2, "@bob_9", 15, 390, 130, 20),
               TextLine(3, "Second line.", 15, 425, 180, 25)]
        spoken = [raw[1], raw[3]]
        timings = [LineTiming(line.index, line.text, i * 3, i * 3 + 2, i * 90, i * 90 + 60)
                   for i, line in enumerate(spoken)]
        cfg = AppConfig(conversation_feather_px=0)
        builder = RevealBuilder(cfg)
        plan = builder.build_plan(spoken, timings, (400, 600), (400, 600), visual_lines=raw)
        self.assertEqual([c.line_indices for c in plan.chunks], [(1,), (3,)])
        self.assertEqual(plan.chunks[0].crop_top, 0)
        self.assertEqual(plan.chunks[-1].crop_bottom, 600)
        self.assertEqual(plan.chunks[0].crop_bottom, plan.chunks[1].crop_top)
        self.assertLess(plan.chunks[1].crop_top, 390)
        # Reassemble RGB to prove no header, photo, username, or footer pixels
        # were omitted, duplicated, or rearranged by narration-only filtering.
        pixels = np.random.default_rng(17).integers(0, 256, (600, 400, 3), dtype=np.uint8)
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "source.png"
            Image.fromarray(pixels).save(source)
            paths = builder.export_chunks(str(source), plan, folder, raw)
            strips = []
            for path in paths:
                with Image.open(path) as image:
                    strips.append(np.array(image)[:, :, :3])
            np.testing.assert_array_equal(np.concatenate(strips, axis=0), pixels)


if __name__ == "__main__":
    unittest.main()
