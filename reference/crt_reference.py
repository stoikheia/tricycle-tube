"""Reference implementation of the display spec (spec/SPEC.md). Pure python, no dependencies.

Derived from the prototype crt_pipeline.py (2026-10-02) with two corrections (spec v0.2):
  1. frame phase is accumulated from the real frame length (89342 dots, or 89341 when the odd-frame dot is skipped)
  2. YIQ->RGB uses the matrix derived from the standard definition
and one clarification (spec v0.3): the persistence blend is rounded in exact integer arithmetic.
Spec v0.4 makes the luma filter a half-cycle notch (LUMA_NOTCH, default); the prototype's 12-sample mean is LUMA_MEAN12.
The prototype behaviour stays reachable (MATRIX_V0, frame phases 0/4/8) so the v0 vectors can still be checked.

Images are flat bytearrays of 8-bit RGB, row-major, 3 bytes per pixel.
"""
import math

# ---------------- signal stage (spec 4)
LEVELS_LO = [0.228, 0.312, 0.552, 0.880]
LEVELS_HI = [0.616, 0.840, 1.100, 1.100]
BLACK_L, WHITE_L = 0.312, 1.100
SAT = 1.6

# rows are (I coefficient, Q coefficient) for R, G, B
MATRIX_STD = ((0.955986, 0.620825), (-0.272013, -0.647204), (-1.106740, 1.704230))
MATRIX_V0 = ((0.946882, 0.623557), (-0.274788, -0.635691), (-1.108545, 1.709007))

DOTS_LONG, DOTS_SHORT = 89342, 89341      # dots per frame; one dot is 8 samples
LUMA_NOTCH, LUMA_MEAN12 = 'notch', 'mean12'  # luma filter: (s[n-3]+s[n+3])/2 then box(1)  /  12-sample mean then box(2)


def frame_phases(n, rendering=True, start=0):
    """Phase at the start of each of n frames. With rendering enabled every odd frame is one dot short."""
    out, ph = [], start % 12
    for f in range(n):
        out.append(ph)
        dots = DOTS_SHORT if (rendering and f % 2 == 1) else DOTS_LONG
        ph = (ph + 8 * dots) % 12
    return out


def encode_line(line, phase0):
    """line: palette indices of one row. Returns 8 samples per pixel, normalised so black = 0 and white = 1."""
    out = [0.0] * (len(line) * 8)
    for x, pix in enumerate(line):
        color = pix & 0x0F
        lvl = (pix >> 4) & 3
        if color > 13:
            lvl = 1
        lo, hi = LEVELS_LO[lvl], LEVELS_HI[lvl]
        if color == 0:
            lo = hi
        if color == 13:
            hi = lo
        for p in range(8):
            s = x * 8 + p
            ph = (phase0 + s) % 12
            high = color == 0 or (color < 13 and (color + ph + 8) % 12 < 6)
            out[s] = ((hi if high else lo) - BLACK_L) / (WHITE_L - BLACK_L)
    return out


def box(sig, r):
    """Mean over [i-r, i+r], edges repeated."""
    n = len(sig)
    k = 2 * r + 1
    acc = sum(sig[max(0, min(n - 1, i))] for i in range(-r, r + 1))
    out = [0.0] * n
    for i in range(n):
        out[i] = acc / k
        acc += sig[min(n - 1, i + r + 1)] - sig[max(0, i - r)]
    return out


def avg12(sig):
    """Mean over [i-6, i+5] (one subcarrier cycle), edges repeated."""
    n = len(sig)
    acc = sum(sig[max(0, min(n - 1, i))] for i in range(-6, 6))
    out = [0.0] * n
    for i in range(n):
        out[i] = acc / 12.0
        acc += sig[min(n - 1, i + 6)] - sig[max(0, i - 6)]
    return out


def luma(sig, mode=LUMA_NOTCH):
    """Luma estimate. notch: average of the samples half a subcarrier cycle away (cancels the 12-sample carrier with a
    7-sample footprint) then box(1). mean12: one-cycle moving average then box(2) (the prototype)."""
    n = len(sig)
    if mode == LUMA_NOTCH:
        return box([(sig[max(0, s - 3)] + sig[min(n - 1, s + 3)]) / 2 for s in range(n)], 1)
    return box(avg12(sig), 2)


def decode_line(sig, phase0, cols, rot, matrix=MATRIX_STD, sat=SAT, luma_mode=LUMA_NOTCH):
    """Returns cols RGB tuples (8-bit)."""
    n = len(sig)
    Y = luma(sig, luma_mode)
    I = [0.0] * n
    Q = [0.0] * n
    for s in range(n):
        c = sig[s] - Y[s]
        ang = math.pi * ((phase0 + s) % 12) / 6.0 + rot
        I[s] = c * math.cos(ang)
        Q[s] = c * math.sin(ang)
    I = box(box(I, 8), 8)
    Q = box(box(Q, 14), 14)
    px = []
    for c in range(cols):
        s = min(n - 1, int((c + 0.5) * n / cols))
        y, i, q = Y[s], sat * I[s], sat * Q[s]
        px.append(tuple(max(0, min(255, int(math.floor((y + mi * i + mq * q) * 255 + 0.5)))) for mi, mq in matrix))
    return px


_ROT_CACHE = {}


def hue_rotation_deg(matrix=MATRIX_STD, luma_mode=LUMA_NOTCH):
    """Angle (multiple of 5 degrees) that makes $16 reddest, $1A greenest and $12 bluest (spec 4.3)."""
    key = (matrix, luma_mode)
    if key in _ROT_CACHE:
        return _ROT_CACHE[key]
    best = None
    for deg in range(0, 360, 5):
        score = 0.0
        for color, want in ((0x16, 0), (0x1A, 1), (0x12, 2)):
            px = decode_line(encode_line([color] * 64, 0), 0, 64, math.radians(deg), matrix, luma_mode=luma_mode)[32]
            score += px[want] - (sum(px) - px[want]) / 2
        if best is None or score > best[0]:
            best = (score, deg)
    _ROT_CACHE[key] = best[1]
    return best[1]


def palette64(matrix=MATRIX_STD, luma_mode=LUMA_NOTCH):
    rot = math.radians(hue_rotation_deg(matrix, luma_mode))
    return {pix: decode_line(encode_line([pix] * 64, 0), 0, 64, rot, matrix, luma_mode=luma_mode)[32] for pix in range(64)}


def render_signal(idx, w, h, cols, frame_phase, matrix=MATRIX_STD, luma_mode=LUMA_NOTCH):
    """idx: w*h palette indices. frame_phase: phase at the start of this frame. Returns RGB image cols x h."""
    rot = math.radians(hue_rotation_deg(matrix, luma_mode))
    img = bytearray(cols * h * 3)
    for y in range(h):
        phase0 = (frame_phase + 4 * y) % 12
        px = decode_line(encode_line(idx[y * w:(y + 1) * w], phase0), phase0, cols, rot, matrix, luma_mode=luma_mode)
        o = y * cols * 3
        for c, rgb in enumerate(px):
            img[o + c * 3:o + c * 3 + 3] = bytes(rgb)
    return img


# ---------------- CRT stage (spec 5)
def _blur_h(buf, w, h, r):
    out = bytearray(len(buf))
    for y in range(h):
        row = buf[y * w * 3:(y + 1) * w * 3]
        for c in range(3):
            acc = sum(row[max(0, min(w - 1, i)) * 3 + c] for i in range(-r, r + 1))
            for x in range(w):
                out[(y * w + x) * 3 + c] = acc // (2 * r + 1)
                acc += row[min(w - 1, x + r + 1) * 3 + c] - row[max(0, x - r) * 3 + c]
    return out


def _blur_v(buf, w, h, r):
    out = bytearray(len(buf))
    for x in range(w):
        for c in range(3):
            col = buf[x * 3 + c::w * 3]
            acc = sum(col[max(0, min(h - 1, i))] for i in range(-r, r + 1))
            for y in range(h):
                out[(y * w + x) * 3 + c] = acc // (2 * r + 1)
                acc += col[min(h - 1, y + r + 1)] - col[max(0, y - r)]
    return out


def _upscale_v_nearest(buf, w, h, k):
    out = bytearray(w * h * k * 3)
    for y in range(h * k):
        out[y * w * 3:(y + 1) * w * 3] = buf[(y // k) * w * 3:(y // k + 1) * w * 3]
    return out


def _upscale_v_bilinear(buf, w, h, k):
    oh = h * k
    out = bytearray(w * oh * 3)
    for y in range(oh):
        fy = (y + 0.5) / k - 0.5
        y0 = max(0, min(h - 1, int(math.floor(fy))))
        y1 = min(h - 1, y0 + 1)
        u = max(0.0, min(1.0, fy - y0))
        r0 = buf[y0 * w * 3:(y0 + 1) * w * 3]
        r1 = buf[y1 * w * 3:(y1 + 1) * w * 3]
        o = y * w * 3
        for i in range(w * 3):
            out[o + i] = int(r0[i] * (1 - u) + r1[i] * u + 0.5)
    return out


def scanline_profile(k, strength=0.6, gap=0.33):
    return [1.0 - strength * (1 - math.exp(-((j + 0.5 - k / 2) / (k * gap)) ** 2)) for j in range(k)]


def default_mask_period(k):
    """Spec 5: max(3, floor(k / 1.3 + 0.5)); 9 for k = 12."""
    return max(3, int(math.floor(k / 1.3 + 0.5)))


def crt_stage(sigimg, cols, h, k=12, strength=0.6, mask_period=None, spot=1, bloom=0.15, gap=0.33):
    """Returns RGB image cols x (h*k). mask_period None = the spec's default for k."""
    if mask_period is None:
        mask_period = default_mask_period(k)
    s = strength
    ow, oh = cols, h * k
    sp = _blur_v(_blur_h(_upscale_v_nearest(sigimg, cols, h, k), ow, oh, spot), ow, oh, spot)
    prof = scanline_profile(k, s, gap)
    d = 1 - 0.3 * s
    stripes = [(1.0, d, d), (d, 1.0, d), (d, d, 1.0)]
    mask = [stripes[(3 * m) // mask_period] for m in range(mask_period)]
    gain = 1.0 + 0.3 * s
    out = bytearray(len(sp))
    for y in range(oh):
        p = prof[y % k]
        o = y * ow * 3
        for x in range(ow):
            m = mask[x % mask_period]
            i = o + x * 3
            for c in range(3):
                out[i + c] = min(255, int(sp[i + c] * p * m[c] * gain + 0.5))
    if bloom > 0:
        glow = _upscale_v_bilinear(_blur_v(_blur_h(sigimg, cols, h, 3), cols, h, 2), cols, h, k)
        for i in range(len(out)):
            out[i] = min(255, int(out[i] + glow[i] * bloom * s))
    return out


# ---------------- persistence stage (spec 6)
def persistence_frame(frames, phases, f, weights=(6, 3, 1), thresh=24):
    """Output for frame f. frames: CRT stage outputs in time order; phases: frame phase of each.
    Missing past frames are replaced by the current one. Motion is tested against the nearest earlier frame
    (2 or 3 back) that has the same frame phase; if there is none, no pixel is treated as moving.
    weights are integers (current, previous, one before); the blend is rounded half up in exact integer arithmetic."""
    cur = frames[f]
    prev1 = frames[f - 1] if f >= 1 else cur
    prev2 = frames[f - 2] if f >= 2 else cur
    same = None
    for back in (2, 3):
        if f - back >= 0 and phases[f - back] == phases[f]:
            same = frames[f - back]
            break
    w0, w1, w2 = weights
    tot = w0 + w1 + w2
    out = bytearray(len(cur))
    for i in range(0, len(cur), 3):
        if same is not None and (abs(cur[i] - same[i]) + abs(cur[i + 1] - same[i + 1]) + abs(cur[i + 2] - same[i + 2])) > thresh:
            out[i:i + 3] = cur[i:i + 3]
            continue
        for c in range(3):
            out[i + c] = (2 * (w0 * cur[i + c] + w1 * prev1[i + c] + w2 * prev2[i + c]) + tot) // (2 * tot)
    return out


# ---------------- downscale stage (spec 7)
def area_average(buf, w, h, ow, oh):
    """Exact area-weighted average of every source pixel overlapped by each output pixel."""
    def spans(n_src, n_out):
        res = []
        for o in range(n_out):
            a, b = o * n_src / n_out, (o + 1) * n_src / n_out
            row = []
            for i in range(int(math.floor(a)), min(n_src, int(math.ceil(b)))):
                wgt = min(b, i + 1) - max(a, i)
                if wgt > 1e-9:
                    row.append((i, wgt))
            res.append(row)
        return res
    xs, ys = spans(w, ow), spans(h, oh)
    out = bytearray(ow * oh * 3)
    for oy in range(oh):
        for ox in range(ow):
            acc = [0.0, 0.0, 0.0]
            wsum = 0.0
            for sy, wy in ys[oy]:
                for sx, wx in xs[ox]:
                    wgt = wx * wy
                    i = (sy * w + sx) * 3
                    wsum += wgt
                    acc[0] += buf[i] * wgt
                    acc[1] += buf[i + 1] * wgt
                    acc[2] += buf[i + 2] * wgt
            o = (oy * ow + ox) * 3
            for c in range(3):
                out[o + c] = int(acc[c] / wsum + 0.5)
    return out
