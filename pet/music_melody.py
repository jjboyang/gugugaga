"""Extract a short pitch sequence and sing it back using DaFeiYu's hum timbre."""
from __future__ import annotations

from io import BytesIO
import math
import wave

import numpy as np

from pet.browsing_motion import HUM_LENGTH


SAMPLE_RATE = 16_000
SAMPLE_SECONDS = 4.5
_HOP = 480
_FRAME = 1536
_FFT = 4096
_PITCHES = np.arange(48, 89)
_PARTIALS = np.array([1.0, 0.65, 0.47, 0.31, 0.20])
PitchPhrase = tuple[tuple[int, float, float], ...]


def extract_phrase(samples: np.ndarray) -> PitchPhrase:
    """Follow the strongest pitched line, keeping intervals, timing and rests."""
    if len(samples) < SAMPLE_RATE * 2:
        return ()
    frames = np.lib.stride_tricks.sliding_window_view(samples, _FRAME)[::_HOP]
    rms = np.sqrt(np.mean(frames ** 2, axis=1))
    audible = rms > max(0.003, float(np.percentile(rms, 80)) * 0.55)
    spectrum = np.abs(np.fft.rfft(frames * np.hanning(_FRAME), n=_FFT))
    frequencies = 440 * 2 ** ((_PITCHES - 69) / 12)
    bins = frequencies[:, None] * np.arange(1, 6) * _FFT / SAMPLE_RATE
    left = bins.astype(int)
    ratio = bins - left
    peaks = spectrum[:, left] * (1 - ratio) + spectrum[:, left + 1] * ratio
    nearby = np.maximum(spectrum[:, left - 2], spectrum[:, left + 3])
    peaks = np.maximum(peaks - 0.8 * nearby, 0)
    # Weight the fundamental so chord harmonics do not routinely get chosen
    # as new lead notes. The change cost damps one-frame octave jumps.
    strength = (peaks ** 0.7) @ _PARTIALS
    strength *= 0.55 + 0.45 * (peaks[:, :, 0] / (peaks.max(axis=(1, 2))[:, None] + 1e-8)) ** 0.45
    best = strength.max(axis=1)
    audible &= best > 1.0
    strength /= best[:, None] + 1e-8
    movement = abs(_PITCHES[:, None] - _PITCHES)
    penalty = 0.07 * (movement > 0) + 0.026 * np.minimum(movement, 12)
    paths = np.zeros(strength.shape, dtype=int)
    scores = strength[0]
    for index in range(1, len(strength)):
        candidates = scores[:, None] - penalty
        paths[index] = np.argmax(candidates, axis=0)
        scores = strength[index] * audible[index] + np.max(candidates, axis=0)
    chosen = np.empty(len(strength), dtype=int)
    chosen[-1] = int(np.argmax(scores))
    for index in range(len(chosen) - 1, 0, -1):
        chosen[index - 1] = paths[index, chosen[index]]

    timeline = np.where(audible, _PITCHES[chosen], 0)
    changes = np.r_[0, np.flatnonzero(timeline[1:] != timeline[:-1]) + 1, len(timeline)]
    notes = [(int(timeline[start]), start * _HOP / SAMPLE_RATE, stop * _HOP / SAMPLE_RATE)
             for start, stop in zip(changes[:-1], changes[1:])
             if timeline[start] and stop - start >= 5]

    # Pick one recognizable phrase. A droning tone or a few isolated noises
    # do not provide enough musical information to keep in the diary.
    best_phrase = ()
    best_score = ()
    for index, (_, start, _) in enumerate(notes):
        phrase = [(pitch, on, off) for pitch, on, off in notes[index:] if off - start <= 2.55]
        if not phrase:
            continue
        pitches = {pitch for pitch, _, _ in phrase}
        duration = sum(off - on for _, on, off in phrase)
        span = phrase[-1][2] - start
        if len(pitches) >= 3 and duration >= 0.80 and duration / span >= 0.64:
            score = (min(len(pitches), 5), min(len(phrase), 7), duration / span)
            if score > best_score:
                best_score = score
                factor = min(1.0, (HUM_LENGTH - 0.06) / span)
                best_phrase = tuple((pitch, round(float((on - start) * factor), 4), round(float((off - on) * factor), 4))
                                    for pitch, on, off in phrase)
    return best_phrase


def hum_wave(phrase: PitchPhrase) -> bytes:
    """Generate only new audio from the selected notes, with gentle onsets."""
    rate = 24_000
    samples = np.zeros(round(rate * HUM_LENGTH))
    median = sorted(pitch for pitch, _, _ in phrase)[len(phrase) // 2]
    transpose = 12 * round((63 - median) / 12)
    timbre = (1.0, 0.26, 0.15, 0.09, 0.044, 0.020)
    for pitch, onset, length in phrase:
        offset = round(rate * onset)
        count = min(round(rate * length), len(samples) - offset)
        t = np.arange(count) / rate
        hz = 440 * 2 ** ((pitch + transpose - 69) / 12)
        attack = min(0.075, length * 0.30)
        release = min(0.13, length * 0.45)
        envelope = np.clip(np.minimum(t / attack, (length - t) / release), 0, 1)
        envelope = envelope ** 2 * (3 - 2 * envelope)
        vibrato = 1 + 0.0045 * np.sin(math.tau * 5.1 * t)
        glide = 1 - 0.023 * np.exp(-t / 0.045)
        phase = np.cumsum(math.tau * hz * vibrato * glide / rate)
        tone = sum(weight * np.sin(harmonic * phase - 0.11 * harmonic ** 2)
                   for harmonic, weight in enumerate(timbre, 1))
        samples[offset:offset + count] += 0.23 * tone * envelope
    output = BytesIO()
    with wave.open(output, "wb") as wav:
        wav.setparams((1, 2, rate, 0, "NONE", "not compressed"))
        wav.writeframes(np.rint(np.clip(samples, -1, 1) * 32767).astype("<i2").tobytes())
    return output.getvalue()
