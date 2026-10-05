"""Render the sample animations in this directory from the reference implementation. Pure Python, no dependencies.

  python3 samples/make_samples.py            # writes testcard_cycle3_60fps.png, testcard_cycle2_60fps.png, testcard_source.png

The test card is original artwork (colour swatches, fine patterns and a bouncing ball); no game graphics are used.
Output is APNG at exactly 1/60 s per frame, looping. Frames are rendered in parallel processes.
"""
import os, sys, struct, zlib
from multiprocessing import Pool

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', 'reference'))
import crt_reference as cr

W, H, K = 128, 96, 12
OUT_W, OUT_H = 512, 384
FRAMES, WARM = 12, 3                 # 12 looping frames; 3 warm-up frames so the afterglow history is periodic


# ---------------- test card (palette indices)
def test_card(t):
    """t: frame index. Returns a bytearray of W*H palette indices."""
    idx = bytearray([0x0F]) * (W * H)
    def put(x, y, v):
        if 0 <= x < W and 0 <= y < H: idx[y * W + x] = v
    # row 0: the twelve hues at level 2 plus four greys (8 px each)
    sw = [0x21, 0x22, 0x23, 0x24, 0x25, 0x26, 0x27, 0x28, 0x29, 0x2A, 0x2B, 0x2C, 0x0F, 0x00, 0x10, 0x30]
    for i, v in enumerate(sw):
        for y in range(0, 12):
            for x in range(i * 8, i * 8 + 8): put(x, y, v)
    # row 1: the same hues at level 1 and 3
    for i in range(12):
        for y in range(12, 18):
            for x in range(i * 8, i * 8 + 8): put(x, y, 0x11 + i)
        for y in range(18, 24):
            for x in range(i * 8, i * 8 + 8): put(x, y, 0x31 + i)
    # band 2 (y 26..49): fine patterns that excite cross-colour
    for y in range(26, 50):
        for x in range(0, 32):   put(x, y, 0x30 if (x + y) % 2 == 0 else 0x0F)        # 1-px checkerboard
        for x in range(32, 64):  put(x, y, 0x30 if x % 2 == 0 else 0x0F)              # 1-px vertical stripes
        for x in range(64, 96):  put(x, y, [0x12, 0x12, 0x0F, 0x30, 0x30, 0x0F, 0x21, 0x21][(x + y) % 8])  # diagonal ramps
        for x in range(96, 128): put(x, y, 0x16 if ((x // 2) + (y // 2)) % 2 == 0 else 0x1A)   # 2-px checker, red/green
    # band 3 (y 52..95): a dark field with a bouncing ball and a static ring
    for y in range(52, 96):
        for x in range(W): put(x, y, 0x01 if (x // 8 + y // 8) % 2 == 0 else 0x0C)
    cx, cy = 20 + [0, 2, 4, 6, 8, 10, 12, 10, 8, 6, 4, 2][t % 12] * 3, 74
    for y in range(cy - 9, cy + 10):
        for x in range(cx - 9, cx + 10):
            d2 = (x - cx) ** 2 + (y - cy) ** 2
            if d2 <= 81: put(x, y, 0x28 if d2 <= 36 else 0x37)
    for y in range(60, 90):
        for x in range(80, 110):
            d2 = (x - 95) ** 2 + (y - 75) ** 2
            if 100 <= d2 <= 196: put(x, y, 0x2B)
    return idx


# ---------------- PNG / APNG writers
def _chunk(tag, data):
    return struct.pack('>I', len(data)) + tag + data + struct.pack('>I', zlib.crc32(tag + data) & 0xffffffff)

def _raw(buf, w, h):
    return b''.join(b'\x00' + bytes(buf[y * w * 3:(y + 1) * w * 3]) for y in range(h))

def write_png(path, w, h, buf):
    png = b'\x89PNG\r\n\x1a\n' + _chunk(b'IHDR', struct.pack('>IIBBBBB', w, h, 8, 2, 0, 0, 0))
    png += _chunk(b'IDAT', zlib.compress(_raw(buf, w, h), 9)) + _chunk(b'IEND', b'')
    open(path, 'wb').write(png)

def write_apng(path, w, h, frames, delay=(1, 60)):
    out = b'\x89PNG\r\n\x1a\n' + _chunk(b'IHDR', struct.pack('>IIBBBBB', w, h, 8, 2, 0, 0, 0))
    out += _chunk(b'acTL', struct.pack('>II', len(frames), 0))
    seq = 0
    for i, fr in enumerate(frames):
        out += _chunk(b'fcTL', struct.pack('>IIIIIHHBB', seq, w, h, 0, 0, delay[0], delay[1], 0, 0)); seq += 1
        data = zlib.compress(_raw(fr, w, h), 9)
        if i == 0:
            out += _chunk(b'IDAT', data)
        else:
            out += _chunk(b'fdAT', struct.pack('>I', seq) + data); seq += 1
    out += _chunk(b'IEND', b'')
    open(path, 'wb').write(out)


# ---------------- rendering
def render_frame(args):
    t, phase = args
    sig = cr.render_signal(test_card(t), W, H, W * 8, phase)
    return cr.crt_stage(sig, W * 8, H, K)

def render_sequence(rendering):
    n = FRAMES + WARM
    phases = cr.frame_phases(n, rendering)
    with Pool() as pool:
        crt = pool.map(render_frame, [(f % FRAMES, phases[f]) for f in range(n)])
    out = []
    for f in range(WARM, n):
        blended = cr.persistence_frame(crt, phases, f)
        out.append(cr.area_average(blended, W * 8, H * K, OUT_W, OUT_H))
    return out

if __name__ == '__main__':
    lut = cr.palette64()
    src = test_card(0); buf = bytearray()
    for v in src: buf += bytes(lut[v])
    write_png(os.path.join(HERE, 'testcard_source.png'), W, H, buf)
    for name, rendering in (('cycle3', False), ('cycle2', True)):
        frames = render_sequence(rendering)
        write_apng(os.path.join(HERE, f'testcard_{name}_60fps.png'), OUT_W, OUT_H, frames)
        write_png(os.path.join(HERE, f'testcard_{name}_frame0.png'), OUT_W, OUT_H, frames[0])
        print('wrote', name, len(frames), 'frames')
