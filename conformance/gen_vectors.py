"""Generate conformance vectors (spec v0.4) from the reference implementation, and check that the reference still
reproduces the prototype vectors (vectors-v0-prototype.json) when run with the prototype's matrix and phases.
Usage: python3 gen_vectors.py OUT.json"""
import sys, os, json, hashlib
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', 'reference'))
import crt_reference as cr

PAT_A = [0x0F, 0x30, 0x0F, 0x30, 0x16, 0x16, 0x2A, 0x2A, 0x12, 0x21, 0x30, 0x0F, 0x27, 0x27, 0x1A, 0x0F]
PAT_B = [0x30, 0x0F, 0x16, 0x21] + PAT_A[4:]          # first four pixels change, the rest stay
W, H, K = 16, 3, 12
COLS = W * 8
sha = lambda b: hashlib.sha256(bytes(b)).hexdigest()
row_hex = lambda img, w, y, n: bytes(img[y * w * 3: y * w * 3 + n * 3]).hex()
sig = lambda pat, ph, m=cr.MATRIX_STD, lm=cr.LUMA_NOTCH: cr.render_signal(bytearray(pat * H), W, H, COLS, ph, m, lm)

# ---- regression against the prototype vectors
v0 = json.load(open(os.path.join(HERE, 'vectors-v0-prototype.json')))
ok = cr.hue_rotation_deg(cr.MATRIX_V0, cr.LUMA_MEAN12) == v0['hue_rotation_deg']
lut0 = cr.palette64(cr.MATRIX_V0, cr.LUMA_MEAN12)
ok &= all(list(lut0[p]) == v0['palette64_rgb'][f'{p:02X}'] for p in range(64))
for f in range(3):
    img = sig(PAT_A, 4 * f, cr.MATRIX_V0, cr.LUMA_MEAN12)
    ok &= all(row_hex(img, COLS, y, COLS) == v0['signal_pattern']['lines'][f'f{f}_y{y}'] for y in range(H))
ok &= sha(cr.crt_stage(sig(PAT_A, 0, cr.MATRIX_V0, cr.LUMA_MEAN12), COLS, H, K)) == v0['crt_stage']['output_sha256']
print('regression vs prototype vectors:', 'PASS' if ok else 'FAIL')
assert ok

# ---- v0.2 vectors
lut = cr.palette64()
lines = {f'p{ph}_y{y}': row_hex(sig(PAT_A, ph), COLS, y, COLS) for ph in (0, 4, 8) for y in range(H)}
crt_a = {ph: cr.crt_stage(sig(PAT_A, ph), COLS, H, K) for ph in (0, 4, 8)}
crt_b = {ph: cr.crt_stage(sig(PAT_B, ph), COLS, H, K) for ph in (0, 4, 8)}
c0 = crt_a[0]

ph_on, ph_off = cr.frame_phases(6, True), cr.frame_phases(6, False)
# case 1: rendering on, pattern A for frames 0-3 then pattern B for frames 4-5
fr1 = [crt_a[p] for p in ph_on[:4]] + [crt_b[p] for p in ph_on[4:]]
p1 = {f: cr.persistence_frame(fr1, ph_on, f) for f in (0, 1, 3, 4, 5)}
moving = sum(1 for i in range(0, len(fr1[5]), 3) if sum(abs(fr1[5][i + c] - fr1[3][i + c]) for c in range(3)) > 24)
# case 2: rendering off (3-frame cycle), pattern A throughout
fr2 = [crt_a[p] for p in ph_off]
p2 = cr.persistence_frame(fr2, ph_off, 5)
# case 3: display default = fixed 3-frame cycle (same phases as rendering off) with motion: A for frames 0-3, B for 4-5
fr3 = [crt_a[p] for p in ph_off[:4]] + [crt_b[p] for p in ph_off[4:]]
p3 = {f: cr.persistence_frame(fr3, ph_off, f) for f in (3, 4, 5)}
moving3 = sum(1 for i in range(0, len(fr3[5]), 3) if sum(abs(fr3[5][i + c] - fr3[2][i + c]) for c in range(3)) > 24)
small = cr.area_average(p1[3], COLS, H * K, 50, 13)

out = {
 "spec_version": "v0.4", "source": "reference/crt_reference.py",
 "image_format": "8-bit RGB, row-major, 3 bytes per pixel; sha256 is taken over these raw bytes; *_hex values are the same bytes in hex",
 "luma_filter": "notch: (s[n-3]+s[n+3])/2 then box(1)",
 "yiq_to_rgb": [[1.0, a, b] for a, b in cr.MATRIX_STD],
 "hue_rotation_deg": cr.hue_rotation_deg(),
 "frame_phases": {"rendering_on": cr.frame_phases(8, True), "rendering_off": cr.frame_phases(8, False)},
 "palette64_rgb": {f"{p:02X}": list(lut[p]) for p in range(64)},
 "signal_pattern": {"pattern_a_hex": [f"{p:02X}" for p in PAT_A], "width": W, "height": H, "cols": COLS,
                    "note": "every row uses pattern A; key p<frame phase>_y<row>; value = cols RGB triplets",
                    "lines": lines},
 "crt_stage": {"input": "signal_pattern at frame phase 0", "k": K, "strength": 0.6, "gap": 0.33, "mask_period": 9, "spot": 1, "bloom": 0.15,
               "scanline_profile": [round(v, 6) for v in cr.scanline_profile(K)], "gain": 1 + 0.3 * 0.6, "stripe_dim": 1 - 0.3 * 0.6,
               "output_size": [COLS, H * K], "output_sha256": sha(c0),
               "output_row6_first24_rgb_hex": row_hex(c0, COLS, 6, 24), "output_row11_first24_rgb_hex": row_hex(c0, COLS, 11, 24),
               "output_row12_first24_rgb_hex": row_hex(c0, COLS, 12, 24),
               "key_map": {"strength": "s", "mask_period": "stripe period", "spot": "spot radius", "stripe_dim": "d", "scanline_profile": "prof[0..k-1], rounded to 6 decimals"}},
 "persistence": {
   "pattern_b_hex": [f"{p:02X}" for p in PAT_B],
   "case_motion": {"note": "rendering on; frames 0-3 show pattern A, frames 4-5 show pattern B; each frame = crt_stage(signal(pattern, frame phase))",
                   "frame_phases": ph_on, "moving_pixels_at_frame5": moving, "total_pixels": COLS * H * K,
                   "moving_note": "pixels of frame 5 with d > 24 against the same-phase frame (frame 3)",
                   "output_sha256": {f"frame{f}": sha(p1[f]) for f in sorted(p1)},
                   "frame5_row6_first24_rgb_hex": row_hex(p1[5], COLS, 6, 24), "frame3_row6_first24_rgb_hex": row_hex(p1[3], COLS, 6, 24)},
   "case_rendering_off": {"note": "rendering off; pattern A in all 6 frames", "frame_phases": ph_off,
                          "output_sha256": {"frame5": sha(p2)}, "frame5_row6_first24_rgb_hex": row_hex(p2, COLS, 6, 24)},
   "case_motion_fixed3": {"note": "display default (fixed 3-frame cycle, phases as rendering off); frames 0-3 pattern A, 4-5 pattern B; same-phase frame for frame 5 is frame 2",
                          "frame_phases": ph_off, "moving_pixels_at_frame5": moving3, "total_pixels": COLS * H * K,
                          "output_sha256": {f"frame{f}": sha(p3[f]) for f in sorted(p3)},
                          "frame5_row6_first24_rgb_hex": row_hex(p3[5], COLS, 6, 24), "frame5_output_rgb_hex": bytes(p3[5]).hex()}},
 "area_average": {"input": "persistence case_motion frame3 (128x36)", "output_size": [50, 13], "output_sha256": sha(small),
                  "row0_rgb_hex": row_hex(small, 50, 0, 50), "output_rgb_hex": bytes(small).hex()},
}
json.dump(out, open(sys.argv[1], 'w'), indent=1)
print('rot', out['hue_rotation_deg'], 'phases on', out['frame_phases']['rendering_on'], 'off', out['frame_phases']['rendering_off'])
print('lut', {f'{p:02X}': lut[p] for p in (0x0F, 0, 0x10, 0x20, 0x16, 0x1A, 0x12, 0x21, 0x27, 0x2A)})
print('moving', moving, '/', COLS * H * K, 'moving(fixed3)', moving3, 'crt sha', out['crt_stage']['output_sha256'][:12])
