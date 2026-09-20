"""Detect broad embedded pictures and give them a silent, timed reveal."""

from dataclasses import dataclass, replace

import numpy as np
from PIL import Image
from pydub import AudioSegment


@dataclass
class Picture:
    top: int
    bottom: int
    start_sec: float = 0.0
    end_sec: float = 0.0


def detect_pictures(path):
    # Compare each row with its outside margins: works on light and dark posts.
    # Text/avatars occupy isolated patches; a photo fills most of consecutive rows.
    with Image.open(path) as image:
        rgb = np.asarray(image.convert("RGB"), dtype=np.float32)
    h, w = rgb.shape[:2]
    margin = max(2, int(w * .015))
    background = np.median(np.concatenate((rgb[:, :margin], rgb[:, -margin:]), axis=1), axis=1)
    distance = np.max(np.abs(rgb - background[:, None]), axis=2)
    occupied = (distance[:, int(w*.05):int(w*.95)] > 18).mean(axis=1) > .68
    # Bridge small highlights inside a photo, without joining separated text rows.
    from cv2 import morphologyEx, MORPH_CLOSE
    occupied = morphologyEx(occupied.astype(np.uint8)[:, None], MORPH_CLOSE,
                           np.ones((9, 1), np.uint8)).ravel().astype(bool)
    edges = np.diff(np.r_[False, occupied, False].astype(int))
    pictures = []
    for top, bottom in zip(np.where(edges == 1)[0], np.where(edges == -1)[0]):
        if bottom - top >= max(80, w * .14):
            # Reject uniform colored panels (ordinary text backgrounds).
            if np.std(rgb[top:bottom, int(w*.1):int(w*.9)], axis=(0, 1)).mean() > 18:
                pictures.append(Picture(int(top), int(bottom)))
    return pictures


def outside_pictures(line, pictures):
    return not any(p.top <= line.y + line.height / 2 < p.bottom for p in pictures)


def insert_picture_pauses(path, lines, timings, pictures, fps, slide):
    """Pause the actual narration, then shift its timestamps by the same amount.

    Each picture gets a half-second settled hold, plus entrance/exit slides.
    The pristine TTS cache is never changed; only the assembled narration is.
    """
    with open(path, 'rb') as source:
        audio = AudioSegment.from_wav(source)
    output = audio[:0]
    cursor = 0
    added = 0
    shifts = [0] * len(timings)
    followers = [next((i for i, line in enumerate(lines) if line.y >= p.bottom), len(lines)) for p in pictures]
    for picture_index, (picture, following) in enumerate(zip(pictures, followers)):
        point = round(timings[following].start_sec * 1000) if following < len(lines) else len(audio)
        point = min(len(audio), max(cursor, point))
        entrance = slide if following > 0 or picture_index > 0 else 0
        next_is_picture = picture_index + 1 < len(pictures) and followers[picture_index + 1] == following
        exit_slide = slide if following < len(lines) and not next_is_picture else 0
        hold_ms = round((entrance + .5 + exit_slide) * 1000)
        picture.start_sec = (point + added) / 1000
        picture.end_sec = picture.start_sec + entrance + .5
        output += audio[cursor:point]
        silence_frames = round(hold_ms * audio.frame_rate / 1000)
        output += AudioSegment(data=bytes(silence_frames * audio.frame_width),
                               sample_width=audio.sample_width, frame_rate=audio.frame_rate,
                               channels=audio.channels)
        cursor = point
        added += hold_ms
        for i in range(following, len(lines)):
            shifts[i] += hold_ms / 1000
    output += audio[cursor:]
    output.export(path, format="wav").close()
    shifted = [replace(t, start_sec=t.start_sec+s, end_sec=t.end_sec+s,
                       start_frame=round((t.start_sec+s)*fps), end_frame=round((t.end_sec+s)*fps))
               for t, s in zip(timings, shifts)]
    return shifted, len(output) / 1000
