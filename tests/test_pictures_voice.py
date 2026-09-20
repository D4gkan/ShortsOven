import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
import soundfile as sf
from PIL import Image, ImageDraw
from pydub import AudioSegment

from src.alignment import LineTiming
from src.config import AppConfig
from src.exceptions import TTSError
from src.ocr_engine import TextLine
from src.pictures import Picture, detect_pictures, insert_picture_pauses, outside_pictures
from src.reveal import RevealBuilder
from src.tts_engine import QwenTTSEngine
from src.voice_quality import likely_whisper


class PictureTests(unittest.TestCase):
    def test_light_dark_and_no_picture(self):
        for background in ('white', '#18212b'):
            with self.subTest(background=background), tempfile.TemporaryDirectory() as folder:
                path = Path(folder)/'source.png'
                image = Image.new('RGB', (400, 600), background)
                draw = ImageDraw.Draw(image)
                for y in range(20, 580, 25):
                    draw.text((20, y), 'A normal line of text.', fill='gray')
                image.save(path)
                self.assertEqual(detect_pictures(path), [])
                photo = np.random.default_rng(1).integers(0, 256, (220, 370, 3), dtype=np.uint8)
                image.paste(Image.fromarray(photo), (15, 180))
                image.save(path)
                self.assertEqual([(p.top, p.bottom) for p in detect_pictures(path)], [(180, 400)])

    def test_picture_pause_preserves_audio_pixels_and_small_next_move(self):
        lines = [TextLine(0, 'Before.', 10, 30, 100, 20), TextLine(1, 'After.', 10, 440, 100, 20)]
        timings = [LineTiming(0, 'Before.', 0, 1, 0, 60), LineTiming(1, 'After.', 1, 2, 60, 120)]
        pictures = [Picture(100, 400)]
        cfg = AppConfig(conversation_feather_px=0, conversation_shadow_opacity=0)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/'speech.wav'
            samples = np.sin(np.arange(48000)*2*np.pi*180/24000)*.4
            sf.write(path, samples, 24000, subtype='PCM_16')
            with path.open('rb') as stream:
                original = AudioSegment.from_wav(stream)
            shifted, duration = insert_picture_pauses(path, lines, timings, pictures, 60, .32)
            with path.open('rb') as stream:
                result = AudioSegment.from_wav(stream)
            self.assertEqual(result[:1000].raw_data, original[:1000].raw_data)
            self.assertEqual(result[2140:].raw_data, original[1000:].raw_data)
            self.assertEqual(result[1000:2140].rms, 0)
            self.assertAlmostEqual(duration, 3.14)
            self.assertAlmostEqual(shifted[1].start_sec, 2.14)
            plan = RevealBuilder(cfg).build_plan(lines, shifted, (400, 500), (400, 500), pictures=pictures)
            self.assertEqual([(c.crop_top, c.crop_bottom) for c in plan.chunks], [(0, 100), (100, 400), (400, 500)])
            photo, after = plan.chunks[1:]
            self.assertEqual(photo.line_indices, ())
            self.assertAlmostEqual(after.transition_start - photo.transition_start - photo.transition_duration, .5)
            self.assertEqual(after.shift, 100)
            self.assertFalse(outside_pictures(TextLine(2, 'Book label', 10, 200, 100, 20), pictures))

    def test_leading_and_trailing_photos(self):
        lines = [TextLine(0, 'Middle.', 10, 220, 100, 20)]
        timings = [LineTiming(0, 'Middle.', 0, 1, 0, 60)]
        pictures = [Picture(0, 200), Picture(300, 500)]
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/'speech.wav'
            AudioSegment.silent(duration=1000).export(path, format='wav').close()
            shifted, duration = insert_picture_pauses(path, lines, timings, pictures, 60, .32)
            plan = RevealBuilder(AppConfig()).build_plan(lines, shifted, (400, 500), (400, 500), pictures=pictures)
            self.assertEqual([c.line_indices for c in plan.chunks], [(), (0,), ()])
            self.assertAlmostEqual(duration, 2.64)

    def test_adjacent_pictures_each_hold_half_second(self):
        lines = [TextLine(0, 'After.', 10, 440, 100, 20)]
        timings = [LineTiming(0, 'After.', 0, 1, 0, 60)]
        pictures = [Picture(20, 200), Picture(210, 400)]
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/'speech.wav'
            AudioSegment.silent(duration=1000).export(path, format='wav').close()
            shifted, duration = insert_picture_pauses(path, lines, timings, pictures, 60, .32)
            plan = RevealBuilder(AppConfig()).build_plan(lines, shifted, (400, 500), (400, 500), pictures=pictures)
            first, second, text = plan.chunks
            self.assertAlmostEqual(second.transition_start, .5)
            self.assertAlmostEqual(text.transition_start - second.transition_start - second.transition_duration, .5)
            self.assertAlmostEqual(duration, 2.64)


class VoiceQualityTests(unittest.TestCase):
    def audio(self):
        return np.sin(np.arange(72000)*2*np.pi*150/24000)*.2

    def test_periodic_quiet_speech_vs_unvoiced_noise(self):
        voiced = self.audio()
        self.assertFalse(likely_whisper(voiced*.01, 24000))
        noise = np.random.default_rng(5).normal(0, .1, len(voiced))
        self.assertTrue(likely_whisper(noise, 24000))
        self.assertTrue(likely_whisper(np.zeros(72000), 24000))
        self.assertTrue(likely_whisper(np.r_[voiced, noise, voiced], 24000))

    def test_bounded_retry_and_rejected_take_not_cached(self):
        with tempfile.TemporaryDirectory() as folder:
            tts = QwenTTSEngine(AppConfig(project_root=folder, voice_speed=1))
            tts._voice = 'Ryan'
            noise = np.random.default_rng(5).normal(0, .1, 72000)
            with patch.object(tts, '_load_model'), patch.object(tts, '_raw_generate', return_value=(noise, 24000)) as generate:
                with self.assertRaises(TTSError):
                    tts.synthesize('A story.')
                self.assertEqual(generate.call_count, 2)
                self.assertFalse(Path(tts._cache_path('A story.')).exists())
            with patch.object(tts, '_load_model'), patch.object(tts, '_raw_generate', side_effect=[(noise, 24000), (self.audio(), 24000)]) as generate:
                path = tts.synthesize('A story.')
                self.assertTrue(Path(path).exists())
                self.assertTrue(generate.call_args.kwargs['retry'])
                self.assertEqual(tts.synthesize('A story.'), path)
                self.assertEqual(generate.call_count, 2)
            sf.write(path, noise, 24000)
            with patch.object(tts, '_load_model'), patch.object(tts, '_raw_generate', return_value=(self.audio(), 24000)) as generate:
                self.assertEqual(tts.synthesize('A story.'), path)
                generate.assert_called_once()


if __name__ == '__main__':
    unittest.main()
