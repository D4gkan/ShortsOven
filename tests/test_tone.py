import io
import json
import tempfile
import unittest
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import Mock, patch
from urllib.error import URLError

from src.config import AppConfig
from src.exceptions import ToneError, TTSError
from src.tone_engine import ToneEngine, validate_tone
from src.tts_engine import QwenTTSEngine


VALID = {"tone": "reflective", "instruct": "Speak gently with thoughtful pauses.", "voice_speed": 0.95}


class ToneTests(unittest.TestCase):
    def test_request_and_immutable_application(self):
        cfg = AppConfig()
        reply = io.BytesIO(json.dumps({"done": True, "message": {"content": json.dumps(VALID)}}).encode())
        with patch("src.tone_engine.urlopen", return_value=reply) as call:
            tone = ToneEngine(cfg).analyze("A complete story. A different ending.")
        request = call.call_args.args[0]
        payload = json.loads(request.data)
        self.assertEqual(json.loads(payload["messages"][1]["content"])["story"], "A complete story. A different ending.")
        self.assertEqual(payload["keep_alive"], 0)
        self.assertFalse(payload["stream"])
        self.assertEqual(call.call_args.kwargs["timeout"], 180)
        changed = tone.apply(cfg)
        self.assertEqual(changed.qwen_tts_instruct, VALID["instruct"])
        self.assertEqual(changed.voice_speed, 0.95)
        self.assertEqual(cfg.voice_speed, 1.0)

    def test_invalid_fields(self):
        for speed in (True, "1.0", 0.5, 2, float("nan"), float("inf")):
            with self.subTest(speed=speed), self.assertRaises(ToneError):
                validate_tone(dict(VALID, voice_speed=speed))
        for data in ({}, [], dict(VALID, instruct=" "), dict(VALID, extra=1)):
            with self.subTest(data=data), self.assertRaises(ToneError):
                validate_tone(data)

    def test_empty_and_oversized_story_do_not_call_ollama(self):
        with patch("src.tone_engine.urlopen") as call:
            for story in (" ", "x" * 16001):
                with self.assertRaises(ToneError):
                    ToneEngine(AppConfig()).analyze(story)
            call.assert_not_called()

    def test_unavailable_service(self):
        for error in (URLError("offline"), TimeoutError()):
            with patch("src.tone_engine.urlopen", side_effect=error), self.assertRaises(ToneError):
                ToneEngine(AppConfig()).analyze("Story")

    def test_malformed_response(self):
        for data in (b"bad json", b"{}", b"[]", b'{"done": false}',
                     b'{"done": true, "message": {"content": "not json"}}'):
            with patch("src.tone_engine.urlopen", return_value=io.BytesIO(data)), self.assertRaises(ToneError):
                ToneEngine(AppConfig()).analyze("Story")

    def test_tts_cache_separates_delivery_language_and_model(self):
        with tempfile.TemporaryDirectory() as root:
            cfg = AppConfig(project_root=root)
            paths = []
            for override in ({}, {"qwen_tts_instruct": "Speak sadly."},
                             {"voice_speed": 0.9}, {"qwen_tts_language": "French"},
                             {"qwen_tts_model_id": "different-model"}):
                tts = QwenTTSEngine(replace(cfg, **override))
                tts._voice = "Ryan"
                paths.append(tts._cache_path("Same story"))
            self.assertEqual(len(set(paths)), len(paths))

    def test_tts_forwards_instruction_without_silent_fallback(self):
        tts = QwenTTSEngine(AppConfig(qwen_tts_instruct=VALID["instruct"]))
        model = Mock()
        model.generate_custom_voice.return_value = ([[0.1]], 24000)
        tts._raw_generate(model, "Story", "Ryan")
        self.assertEqual(model.generate_custom_voice.call_args.kwargs["instruct"], VALID["instruct"])
        model.generate_custom_voice.side_effect = TypeError("Unsupported instruction")
        with self.assertRaises(TypeError):
            tts._raw_generate(model, "Story", "Ryan")
        self.assertEqual(model.generate_custom_voice.call_count, 2)
        with self.assertRaises(TTSError):
            tts._raw_generate(object(), "Story", "Ryan")

    def test_pipeline_orders_cleanup_tone_then_tts(self):
        import main
        events = []
        cfg = AppConfig()
        lines = [SimpleNamespace(text="Cleaned story.")]
        tone = validate_tone(VALID)
        with patch.object(main, "parse_args", return_value=SimpleNamespace(image=None)), \
             patch.object(main, "load_config", return_value=cfg), \
             patch.object(main, "AssetManager") as assets, \
             patch.object(main.Image, "open") as image, \
             patch.object(main, "OCREngine") as ocr, \
             patch.object(main, "clean_lines", side_effect=lambda _: events.append("cleanup") or lines), \
             patch.object(main, "ToneEngine") as engine, \
             patch.object(main, "QwenTTSEngine") as tts, \
             patch.object(main, "AlignmentEngine") as aligner, \
             patch.object(main, "RevealBuilder"), patch.object(main, "Renderer") as renderer:
            image.return_value.__enter__.return_value.size = (600, 800)
            ocr.return_value.detect_lines.side_effect = lambda _: events.append("ocr") or lines
            engine.return_value.analyze.side_effect = lambda _: events.append("tone") or tone
            tts.side_effect = lambda c: events.append("tts") or Mock()
            aligner.return_value.build_narration.return_value = [SimpleNamespace(end_sec=1)]
            self.assertEqual(main.run(), 0)
            self.assertEqual(events, ["ocr", "cleanup", "tone", "tts"])
            working_image = ocr.return_value.detect_lines.call_args.args[0]
            self.assertTrue(working_image.endswith("source_image.png"))
            image.return_value.__enter__.return_value.convert.return_value.save.assert_called_once_with(
                working_image, format="PNG")
            self.assertEqual(renderer.return_value.render.call_args.kwargs["image_path"], working_image)
            engine.return_value.analyze.assert_called_once_with("Cleaned story.")
            self.assertEqual(tts.call_args.args[0].qwen_tts_instruct, VALID["instruct"])
            engine.return_value.analyze.side_effect = ToneError("Unavailable")
            tts.reset_mock()
            self.assertEqual(main.run(), 1)
            tts.assert_not_called()


if __name__ == "__main__":
    unittest.main()
