"""Conservative acoustic rejection of sustained unvoiced narration.

This is a heuristic, not a learned whisper classifier. Normal consonants are
unvoiced too, so inspect multi-second windows rather than individual sounds.
"""

import numpy as np


def likely_whisper(audio, sample_rate):
    audio = np.asarray(audio, dtype=np.float32)
    if audio.ndim > 1:
        audio = audio.mean(axis=1)
    if not audio.size or not np.isfinite(audio).all():
        return True
    # Decimate to roughly 8 kHz; block averaging suppresses high-frequency noise.
    step = max(1, sample_rate // 8000)
    audio = audio[:len(audio)//step*step].reshape(-1, step).mean(axis=1)
    rate = sample_rate / step
    size, hop = int(rate * .04), int(rate * .02)
    if len(audio) < size:
        return True
    frames = np.lib.stride_tricks.sliding_window_view(audio, size)[::hop].copy()
    frames -= frames.mean(axis=1, keepdims=True)
    power = np.mean(frames**2, axis=1)
    if power.max() < 1e-9:
        return True
    active = power > max(1e-9, np.percentile(power, 90) * .025)
    fft = np.fft.rfft(frames, n=2*size, axis=1)
    correlation = np.fft.irfft(fft * fft.conj(), n=2*size, axis=1)[:, :size]
    lags = np.arange(int(rate/500), int(rate/65))
    # Normalize for the number of overlapping samples at each lag.
    normalized = correlation / np.maximum(correlation[:, :1], 1e-12)
    normalized *= size / (size-np.arange(size))
    # A periodic waveform has a repeat peak, not just a slow decay from DC.
    peaks = (normalized[:, lags] > normalized[:, lags-1]) & (normalized[:, lags] > normalized[:, lags+1])
    scores = np.where(peaks, normalized[:, lags], 0)
    voiced = scores.max(axis=1) > .5
    window = min(125, len(frames))  # 2.5 seconds, with overlapping checks
    starts = sorted(set(range(0, max(1, len(frames)-window+1), 25)) | {len(frames)-window})
    for start in starts:
        selection = active[start:start+window]
        if selection.sum() >= min(30, window*.6):
            if voiced[start:start+window][selection].mean() < .16:
                return True
    return False
