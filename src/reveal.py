"""Narration-triggered conversation chunks with one shared scrolling offset."""

import math
import os
from dataclasses import dataclass

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

from .exceptions import RenderError
from .logger_setup import get_logger

log = get_logger(__name__)


def smoothstep(t):
    t = max(0.0, min(1.0, t))
    return t * t * (3.0 - 2.0 * t)


@dataclass
class ConversationChunk:
    line_indices: tuple
    crop_top: int
    crop_bottom: int
    height: int
    stack_top: float
    start_sec: float
    end_sec: float
    transition_start: float = 0.0
    transition_duration: float = 0.0
    shift: float = 0.0


@dataclass
class RevealPlan:
    display_width: int
    chunks: list
    initial_y: float
    gap: int
    feather: int
    shadow_padding: int = 0

    def offset_at(self, seconds):
        return self.initial_y - sum(
            c.shift * smoothstep((seconds - c.transition_start) / c.transition_duration)
            for c in self.chunks[1:] if c.transition_duration > 0
        )

    def offset_expression(self):
        # All chunks use the identical expression: spacing cannot change mid-slide.
        terms = [f"{self.initial_y:.6f}"]
        for c in self.chunks[1:]:
            u = f"clip((t-{c.transition_start:.6f})/{c.transition_duration:.6f},0,1)"
            terms.append(f"-{c.shift:.6f}*({u})*({u})*(3-2*({u}))")
        return "".join(terms)


class RevealBuilder:
    def __init__(self, cfg):
        self.cfg = cfg

    def build_plan(self, lines, timings, orig_image_size, display_size, visual_lines=None, pictures=None):
        pictures = pictures or []
        if not lines or len(lines) != len(timings):
            raise RenderError("Conversation chunks require matching OCR lines and speech timings.")
        if any(line.index != timing.index for line, timing in zip(lines, timings)):
            raise RenderError("OCR lines and narration timing indices do not match.")
        max_lines = self.cfg.conversation_chunk_lines
        if not isinstance(max_lines, int) or not 1 <= max_lines <= 8:
            raise RenderError("conversation_chunk_lines must be an integer from 1 to 8.")
        if not 0.1 <= self.cfg.conversation_slide_sec <= 1.0:
            raise RenderError("conversation_slide_sec must be between 0.1 and 1 second.")
        if not 0.3 <= self.cfg.conversation_anchor_y <= 0.7:
            raise RenderError("conversation_anchor_y must be between 0.3 and 0.7.")
        if not 0 <= self.cfg.conversation_gap_px <= 80 or not 0 <= self.cfg.conversation_feather_px <= 40:
            raise RenderError("Conversation spacing or feather width is out of range.")
        if not 0 <= self.cfg.conversation_shadow_opacity <= 0.6 or not 0 <= self.cfg.conversation_shadow_radius_px <= 30:
            raise RenderError("Conversation shadow opacity or radius is out of range.")
        ow, oh = orig_image_size
        width = display_size[0]
        scale = width / ow
        # Split at paragraph gaps or sentence ends, with a small maximum chunk size.
        groups = []
        current = []
        for i, line in enumerate(lines):
            if current:
                prev = lines[current[-1]]
                gap = line.y - (prev.y + prev.height)
                if gap > max(prev.height, line.height) * 1.2 or any(prev.y < p.top < line.y for p in pictures):
                    groups.append(current)
                    current = []
            current.append(i)
            if len(current) >= max_lines or line.text.rstrip().endswith((".", "!", "?")):
                groups.append(current)
                current = []
        if current:
            groups.append(current)

        # Narration defines WHEN to reveal; it must never decide WHICH pixels
        # survive. Partition the entire screenshot into contiguous strips.
        # Keep intervening usernames/undetected media with the next narrated
        # line. Detected pictures are split into separate strips below.
        visual_lines = lines if visual_lines is None else visual_lines
        boundaries = [0]
        for group in groups[:-1]:
            last = lines[group[-1]]
            text_bottom = last.y + last.height
            following_y = min((line.y for line in visual_lines if line.y >= text_bottom),
                              default=oh)
            padding = min(self.cfg.line_padding_px, max(0, (following_y - text_bottom) // 2))
            boundary = min(oh, text_bottom + padding)
            if boundary <= boundaries[-1]:
                raise RenderError("Overlapping OCR bounds cannot form ordered conversation sections.")
            boundaries.append(boundary)
        boundaries.append(oh)

        # Merge visual picture events with spoken events in source order. The
        # resulting strips still cover every pixel exactly once, including names.
        events = [(lines[g[0]].y, g, None, boundaries[i + 1]) for i, g in enumerate(groups)]
        events += [(p.top, [], p, p.bottom) for p in pictures]
        events.sort(key=lambda event: event[0])
        chunks = []
        stack_top = 0
        top = 0
        for event_index, (_, group, picture, bottom) in enumerate(events):
            if event_index + 1 == len(events):
                bottom = oh
            elif events[event_index + 1][2] is not None:
                bottom = events[event_index + 1][2].top
            if bottom <= top:
                raise RenderError("Invalid OCR crop bounds for a conversation chunk.")
            height = max(1, round(bottom * scale) - round(top * scale))
            start = picture.start_sec if picture else max(0.0, timings[group[0]].start_sec)
            end = picture.end_sec if picture else max(start, timings[group[-1]].end_sec)
            chunk = ConversationChunk(tuple(lines[i].index for i in group), top, bottom,
                                      height, stack_top, start, end)
            chunks.append(chunk)
            stack_top += height + self.cfg.conversation_gap_px
            top = bottom

        for i, chunk in enumerate(chunks[1:], 1):
            prev = chunks[i - 1]
            # Prefer the gap before speech. Without a gap, use only the short
            # introduction of the new chunk, never a continuous scroll.
            start = max(prev.end_sec, chunk.start_sec - self.cfg.conversation_slide_sec)
            start = min(start, chunk.start_sec)
            if not chunk.line_indices:
                start = chunk.start_sec
            if i > 1:
                start = max(start, prev.transition_start + prev.transition_duration)
            next_start = chunks[i + 1].start_sec if i + 1 < len(chunks) else chunk.end_sec
            room = max(1 / self.cfg.fps, next_start - start)
            chunk.transition_start = start
            chunk.transition_duration = min(self.cfg.conversation_slide_sec, room)
            # Make room only for the newly appended section. Re-centering by
            # averaging both heights makes a short line after a photo jump.
            chunk.shift = chunk.height + self.cfg.conversation_gap_px

        plan = RevealPlan(width, chunks,
                          self.cfg.height * self.cfg.conversation_anchor_y - chunks[0].height / 2,
                          self.cfg.conversation_gap_px, self.cfg.conversation_feather_px)
        if self.cfg.conversation_shadow_opacity:
            plan.shadow_padding = 3 * self.cfg.conversation_shadow_radius_px + 4
        log.info("Building conversation feed: %s chunks; movements follow narration boundaries.", len(chunks))
        return plan

    def export_chunks(self, image_path, plan, output_dir, lines):
        """Crop and scale once. Feather alpha only; never blur screenshot RGB."""
        os.makedirs(output_dir, exist_ok=True)
        paths = []
        with Image.open(image_path) as source:
            source = source.convert("RGB")
            scale = plan.display_width / source.width
            for i, chunk in enumerate(plan.chunks):
                crop = source.crop((0, chunk.crop_top, source.width, chunk.crop_bottom))
                crop = crop.resize((plan.display_width, chunk.height), Image.Resampling.LANCZOS).convert("RGBA")
                y, x = np.ogrid[:chunk.height, :plan.display_width]
                # Touching chunks must not expose the background at their seams.
                # Keep side feathering, plus the top/bottom of the overall stack.
                distance = np.broadcast_to(np.minimum(x, plan.display_width - 1 - x),
                                           (chunk.height, plan.display_width)).copy()
                if plan.gap > 0 or i == 0:
                    distance = np.minimum(distance, y)
                if plan.gap > 0 or i == len(plan.chunks) - 1:
                    distance = np.minimum(distance, chunk.height - 1 - y)
                if plan.feather:
                    alpha = np.clip(distance / plan.feather, 0, 1)
                    alpha = (255 * alpha * alpha * (3 - 2 * alpha)).astype(np.uint8)
                else:
                    alpha = np.full((chunk.height, plan.display_width), 255, dtype=np.uint8)
                # Text boxes remain fully opaque even when OCR finds text near an edge.
                for line in lines:
                    if line.y >= chunk.crop_bottom or line.y + line.height <= chunk.crop_top:
                        continue
                    left = max(0, math.floor(line.x * scale) - 2)
                    right = min(plan.display_width, math.ceil((line.x + line.width) * scale) + 2)
                    top = max(0, math.floor((line.y - chunk.crop_top) * scale) - 2)
                    bottom = min(chunk.height, math.ceil((line.y + line.height - chunk.crop_top) * scale) + 2)
                    alpha[top:bottom, left:right] = 255
                crop.putalpha(Image.fromarray(alpha))
                if plan.shadow_padding:
                    pad = plan.shadow_padding
                    canvas_size = (crop.width + 2 * pad, crop.height + 2 * pad)
                    shadow = Image.new("L", canvas_size, 0)
                    # Extend internal joins before blurring, so the side shadow
                    # remains continuous rather than outlining every text line.
                    top = pad + 4 if i == 0 or plan.gap else -pad
                    bottom = pad + crop.height + 3 if i == len(plan.chunks) - 1 or plan.gap else canvas_size[1] + pad
                    ImageDraw.Draw(shadow).rectangle(
                        (pad, top, pad + crop.width - 1, bottom),
                        fill=round(255 * self.cfg.conversation_shadow_opacity))
                    shadow = shadow.filter(ImageFilter.GaussianBlur(self.cfg.conversation_shadow_radius_px))
                    if not plan.gap:
                        draw = ImageDraw.Draw(shadow)
                        if i:
                            draw.rectangle((0, 0, canvas_size[0], pad - 1), fill=0)
                        if i < len(plan.chunks) - 1:
                            draw.rectangle((0, pad + crop.height, canvas_size[0], canvas_size[1]), fill=0)
                    canvas = Image.new("RGBA", canvas_size, (0, 0, 0, 0))
                    canvas.putalpha(shadow)
                    canvas.alpha_composite(crop, (pad, pad))
                    crop = canvas
                path = os.path.abspath(os.path.join(output_dir, f"chunk_{i:04d}.png"))
                crop.save(path)
                paths.append(path)
        return paths
