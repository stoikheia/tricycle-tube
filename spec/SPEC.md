# Display Specification v0.5 (draft) — Reproducing the Famicom composite signal and its CRT look

Version: v0.6 draft (2026-10-07). English is the normative text; [SPEC.ja.md](SPEC.ja.md) is the Japanese edition and follows it.
Reference implementation: [reference/crt_reference.py](../reference/crt_reference.py). Conformance vectors: [conformance/vectors.json](../conformance/vectors.json).

This document is the core of the project. The goal is that an AI agent (or a person) given only this document and the conformance vectors can implement the same picture in a new emulator, in a modified existing emulator, or as a shader. Two blind reproduction tests have passed (§12).

How to read: sections marked **(normative)** are what an implementation must follow. "Background" paragraphs explain why, so that an implementer adapting to a different environment can make consistent choices. §10 lists open items.

## 1. Terms

- **Palette index**: the 6-bit value `$00..$3F` the PPU (the Famicom's video chip, 2C02) emits per pixel. Low 4 bits = hue number, high 2 bits = brightness level.
- **Composite signal**: video with luma and chroma on one wire. The Famicom builds this signal directly without ever producing RGB.
- **Subcarrier**: the ~3.58 MHz wave that carries colour. In this spec one cycle = 12 samples.
- **Sample**: the smallest time step of the signal. One pixel = 8 samples.
- **Phase**: position within one subcarrier cycle (0..11).
- **Y / I / Q**: luma and the two colour-difference components.
- **Scanline**: one horizontal sweep of the CRT beam; corresponds to one pixel row.
- **Phosphor stripes**: the vertical red/green/blue emitters of the screen.
- **Afterglow (persistence)**: the tail of light after the phosphor is excited; represented here by blending recent frames.
- **Host**: whatever embeds this pipeline (an emulator, a frontend that loads shaders, ...).

## 2. Overall flow (normative)

Input: an image of palette indices and a frame phase. Output: an RGB image for display.

```
palette indices W×H + frame phase P
  → [signal stage]  encode to composite, decode            → RGB 8W×H
  → [CRT stage]     ×k vertically; scanlines, stripes, bloom → RGB 8W×kH
  → [afterglow]     blend the last three frames             → RGB 8W×kH
  → [downscale]     area average to the display size        → RGB any size
```

- Standard values: W = 256, H = 240, k = 12 (intermediate image 2048×2880). **The intermediate image size is fixed regardless of the display size.**
- Every stage works on gamma-encoded 0..255 values as they are (no conversion to linear light).
- Images handed between stages are 8-bit integer RGB. Inside a stage, compute in double precision; where values are rounded to integers is stated in each section's formulas.
- Out-of-range indices repeat the edge value. This applies to every average, blur and interpolation in this spec. When averages are chained, each pass clamps indices against its own input array (do not extend the signal first and then filter once).
- Not included: geometric distortion, ghosting, RF-path degradation (snow, hum, detuning).

Background: a fixed intermediate image keeps the scanline and stripe structure identical regardless of the window size; a small window shows the same structure shrunk.

## 3. Input (normative)

### 3.1 Required inputs

1. The palette index (6 bits) of every pixel, before any conversion to colour.
2. The frame phase P (0..11): the subcarrier phase at the start of the frame. See §3.3.

Anchoring: P is the phase of the first sample of visible pixel (0, 0); row y of the full 240-row picture starts at `P + 4y`. If the host crops rows before this pipeline, it must keep the original row numbers (e.g. a picture starting at row 8 uses y = 8 for its first row). Indices are taken after the PPU's greyscale processing: when PPUMASK greyscale is set, pass `index & $30`.

### 3.2 How hosts obtain the index

| Host | Method |
|---|---|
| New emulator | Pass the PPU output buffer before it is converted to RGB |
| Modified existing emulator | Hook in just before the palette lookup (e.g. Mesen-family emulators pass a 9-bit PPU output buffer to their video filter) |
| RetroArch shader | Set the core's palette option to raw; the core then outputs R = hue/15, G = level/3, B = emphasis/7. Recover with `floor(R*15+0.5)`, `floor(G*3+0.5)`, `floor(B*7+0.5)` |
| RGB-only host | Reverse-look up the nearest palette index in the host's 64-colour table. When several indices map to the same colour, use `$0F` as the representative black. Fidelity suffers |

The emphasis bits (the PPU's three colour-emphasis bits) are not used in this version (§10).

### 3.3 Frame phase

Frames are counted from 0. Frame 0 starts at P = 0; at the end of each frame, the next phase follows from that frame's length in dots:

```
P_next = (P + 8 * dots) mod 12
```

- A frame is 341 × 262 = 89342 dots, which advances P by +4.
- While rendering is enabled, odd-numbered frames are one dot short (89341 dots), which advances P by +8.
- Hence during rendering the phase runs 0, 4, 0, 4, … (a **2-frame cycle**); while rendering is disabled it runs 0, 4, 8, 0, … (a 3-frame cycle).

Per host:

| Host | Method |
|---|---|
| New emulator, modified emulator | Accumulate the dots the PPU actually produced each frame; the rendering-enabled/disabled behaviour falls out automatically |
| Host that only knows a frame number f (shaders, …) | Fixed 3-frame cycle (default): P = 4 × (f mod 3). Fixed 2-frame cycle, or hardware-faithful mode without dot counts: P = 0 for even f, 4 for odd f (assumes rendering is always on) |

**Display phase mode**: how the phase advances is a display-side setting.

| Mode | Dots fed to the formula | Phase sequence |
|---|---|---|
| Fixed 3-frame cycle (**default**) | always 89342 | 0, 4, 8, 0, … |
| Hardware-faithful | the dots the PPU actually produced | 0, 4, 0, 4, … while rendering; 0, 4, 8, … while blanked |
| Fixed 2-frame cycle | 89342 and 89341 alternately | 0, 4, 0, 4, … |

The default of a fixed 3-frame cycle is a display choice (decided 2026-10-04: keep the bleed, and make the false-colour hue keep rotating — the flicker and the crawling pattern — while normal hardware operation is a 2-frame cycle). The same-phase search in the afterglow stage (§6) works identically in every mode.

## 4. Signal stage (normative)

Each row is processed independently. The phase at the start of row y (0-based) is

```
phase0 = (P + 4*y) mod 12
```

Background: a row is 341 pixels × 8 samples = 2728 samples, which leaves a remainder of 4 when divided by 12. The phase shifts by a third of a cycle per row and repeats every 3 rows.

### 4.1 Encoding (palette index → signal)

Constants (voltages; measured on real hardware):

```
LO = [0.228, 0.312, 0.552, 0.880]
HI = [0.616, 0.840, 1.100, 1.100]
black = 0.312, white = 1.100
```

For pixel x with palette index pix:

```
color = pix & 0x0F
lvl   = (pix >> 4) & 3
if color > 13: lvl = 1
lo = LO[lvl], hi = HI[lvl]
if color == 0:  lo = hi
if color == 13: hi = lo
```

For each of the pixel's 8 samples (p = 0..7, sample index in the row s = 8x + p):

```
ph = (phase0 + s) mod 12
high = (color == 0) or (color < 13 and ((color + ph + 8) mod 12) < 6)
v = hi if high else lo
sig[s] = (v - 0.312) / (1.100 - 0.312)
```

Background: hues 1..12 are square waves with a 12-sample period and 50 % duty, each shifted by one sample. Hue 0 is the high level only (grey to white), 13 is the low level only, 14 and 15 are black.

### 4.2 Decoding (signal → RGB)

Let n = 8W be the number of samples in the row.

Write a box average as `box(a, r)[i] = mean(a[i-r .. i+r])` (sum of 2r+1 values divided by their count).

```
N[i]  = (sig[i-3] + sig[i+3]) / 2       … mean of the two samples half a cycle away (notch)
Y     = box(N, 1)
C[i]  = sig[i] - Y[i]
ang_i = π * ((phase0 + i) mod 12) / 6 + rot
Iraw[i] = C[i] * cos(ang_i)
Qraw[i] = C[i] * sin(ang_i)
I = box(box(Iraw, 8), 8)
Q = box(box(Qraw, 14), 14)
```

Output column c (0 .. cols-1; standard cols = n) uses sample `s = min(n-1, floor((c + 0.5) * n / cols))`:

```
y = Y[s], i = sat * I[s], q = sat * Q[s]        sat = 1.6
R = y + 0.955986*i + 0.620825*q
G = y - 0.272013*i - 0.647204*q
B = y - 1.106740*i + 1.704230*q
each component = clamp(floor(component*255 + 0.5), 0, 255)
```

`rot` (hue rotation) = **350°** (used in radians). How it is determined: §4.3.

Background:
- Two samples half a cycle (6 samples) apart carry the subcarrier with opposite sign, so their mean cancels the colour and leaves luma. The footprint is only 7 samples, so a one-dot (8-sample) black pixel stays nearly black. The following 3-sample mean rounds the edges slightly. The price is a thin vertical striping at colour boundaries.
- The prototype used a 12-sample moving average (one full cycle) followed by a 5-sample mean (`mean(sig[i-6 .. i+5])` then `box(·, 2)`). Isolated black pixels floated up to grey (mean luma of 60 isolated black pixels 46.8 → 35.3 with the notch), so the notch became the default on 2026-10-04. The reference keeps the old filter as `LUMA_MEAN12`.
- Chroma is recovered by multiplying with the subcarrier and low-pass filtered with the double box averages. At the sampling rate of 8 samples per dot (≈ 42.95 MHz) their −3 dB points are about 0.81 MHz (I) and 0.47 MHz (Q), first zeros 2.53 MHz and 1.48 MHz; the widths were chosen by eye and are narrower than the nominal NTSC I/Q bandwidths (1.3 / 0.6 MHz). Horizontal colour bleed and the rainbow on fine patterns (cross-colour) arise here naturally.
- `rot` is the angle at which `$16` is reddest, `$1A` greenest and `$12` bluest (§4.3).
- The RGB coefficients are derived from the standard definition (6 decimals): Y = 0.299R + 0.587G + 0.114B, U = 0.492111(B − Y), V = 0.877283(R − Y), I = −U sin33° + V cos33°, Q = U cos33° + V sin33°, inverted.
- The saturation 1.6, the notch luma filter and the double-box band limits are a simple construction chosen by eye in the project's prototype and sample tests.

### 4.3 Determining the hue rotation

For each of the 72 angles 0°, 5°, …, 355°, compute the score below and take the angle with the highest score; on a tie, the smaller angle.

- Three colours: `$16` (target component R), `$1A` (G), `$12` (B).
- For each, encode and decode a 64-pixel row of that colour alone with phase0 = 0 (phase0 given directly), take column 32 with cols = 64, and use **the integer RGB after rounding and clamping to 0..255**.
- Score = sum over the three colours of `target component − mean of the other two`.

Result: 350°. Scoring on un-rounded floating-point values can pick a different angle, so always score the rounded values. Redo this procedure whenever the coefficients change.

## 5. CRT stage (normative)

Input: the signal stage's RGB (width cols, height H). Output: width cols, height kH.

Defaults: k = 12, strength s = 0.6, gap = 0.33, stripe period = 9, spot radius = 1, bloom = 0.15.

Steps:

1. **Scale vertically by k** (nearest). Output row Y comes from source row `floor(Y / k)`. Width unchanged.
2. **Beam spot**: apply a radius-1 box average (3 values) horizontally and truncate to integers; then apply the same average vertically to that integer image and truncate again (truncation per direction; the vertical pass runs over the rows of the enlarged image).
3. **Scanline**: factor for output row Y, with j = Y mod k:
   `prof[j] = 1 - s * (1 - exp(-((j + 0.5 - k/2) / (k * gap))^2))`
4. **Phosphor stripes**: factor for output column X. With m = X mod period and t = floor(3m / period), the factors applied to (R, G, B) are (1, d, d) for t = 0, (d, 1, d) for t = 1, (d, d, 1) for t = 2, where d = 1 − 0.3s.
5. **Combine**: per component, `out = min(255, floor(spot value * prof * that component's stripe factor * gain + 0.5))`, gain = 1 + 0.3s. `out` is an integer.
6. **Bloom**: take the signal stage's RGB (before enlargement), apply a radius-3 box average (7 values) horizontally and truncate, then a radius-2 box average (5 values) vertically to that integer image and truncate. Enlarge it vertically by k with bilinear interpolation (width unchanged), pixel-centre based: for output row Y let `v = (Y + 0.5)/k − 0.5`, upper row `y0 = clamp(floor(v), 0, H−1)`, lower row `y1 = min(H−1, y0 + 1)`, weight `u = clamp(v − y0, 0, 1)`, value `a*(1−u) + b*u`, rounded with `floor(x + 0.5)`.
   Finally, per component, `out = min(255, floor(out of step 5 + bloom image * bloom * s))`.

When k changes, the default stripe period is `max(3, floor(k / 1.3 + 0.5))` (9 for k = 12).

Background: the NTSC Famicom PPU (2C02) always emits 262 lines per frame (on some odd frames the pre-render line is one dot short, §3.3) and never offsets vertical sync by half a line, so the CRT traces every frame over the same scanlines (240p; no interlace). The spaces between the beam traces remain dark — that is the scanline look, represented here by a Gaussian profile over k rows per scanline: bright in the middle of the row, dark at the top and bottom; gap is the beam width. Gain compensates for the light lost to stripes and scanlines. Bloom is the faint halo around bright areas.

## 6. Afterglow stage (normative)

Input: the time series of CRT-stage outputs F[f] and each frame's phase P[f]. Weights current : previous : the one before = 6 : 3 : 1 (0.6 / 0.3 / 0.1).

Determine the **same-phase frame** S: among f−2 and f−3, the one that exists and whose P equals P[f] (both cannot match at once). If neither, S is "none".

Per pixel, per component:

```
if S exists:  d = |F[f].r - S.r| + |F[f].g - S.g| + |F[f].b - S.b|
if S exists and d > 24:  out = F[f]                       (moving pixel: no afterglow)
otherwise:               out = (6*F[f] + 3*F[f-1] + 1*F[f-2] + 5) div 10    (div = integer floor division)
```

- The blend is defined in integers (multiplying by 0.6 etc. in floating point splits results on pixels whose fraction is exactly 0.5). For other weights w0 : w1 : w2 with sum T, use `(2*(w0*a + w1*b + w2*c) + T) div (2*T)`.
- Blend the un-blended images (do not feed the output back into the next frame).
- Advance the afterglow per emulated frame. Even if the screen refreshes at 30 Hz, the presented picture is the blend of the last three frames.
- When past frames do not exist (frames 0 and 1), substitute the current frame only for the missing ones: at frame 1, F[f−1] = F[0] and F[f−2] is replaced by F[1]. S is chosen only among existing frames (none at frames 0 and 1; F[0] is a candidate at frame 2).
- When the phase sequence runs 0, 4, 0, 4 (2-frame cycle) S = F[f−2]; when it runs 0, 4, 8 (3-frame cycle, including the default fixed mode) S = F[f−3]. Keep three past frames.
- Permitted variant (lighter): apply this stage to the signal-stage images (8W×H) and run the CRT stage afterwards. The blend is linear, so the picture is almost the same, but clamping at 255 and the motion threshold act on different values; such an implementation is not expected to match the `persistence` and `area_average` vectors and must say that it uses the variant. Keeping the history at signal-stage size and recomputing the CRT stage for each past frame (§8) is not this variant: it is the normative order.

Background: the row phase changes every frame, so the rainbow pattern changes every frame. On real hardware the phosphor and the eye smooth it; an LCD has no afterglow, so the blend supplies it. Motion is detected against the same-phase frame because static pixels are identical when the phase is identical. Luma alone is not enough, since the Famicom has many colours that differ only in hue at equal brightness.

Reference: the 6 : 3 : 1 weights were chosen on the prototype's 3-frame cycle (confirmed as the default on 2026-10-04). With a 2-frame cycle only two phases exist and no weighting cancels the rainbow completely. Measured on a 1-pixel black/white checkerboard (signal-stage output, saturation = mean of max − min component): single frame 94.3; 3-frame cycle with these weights 41.1; 2-frame cycle with these weights 57.3; 2-frame cycle with 5 : 5, 47.2.

## 7. Downscale stage (normative)

Shrink the intermediate image (8W × kH) to the display size by **area averaging**: every source pixel overlapped by an output pixel contributes with the overlapped area as its weight.

- Horizontally, output column o covers the source range `[o * src_width / out_width, (o+1) * src_width / out_width)`. The overlap length of this range with each source pixel `[i, i+1)` is the horizontal weight. Same vertically.
- A source pixel's weight = horizontal × vertical weight. Per component, `weighted sum ÷ sum of weights`, rounded with `floor(x + 0.5)`.
- Two-tap bilinear interpolation must not be used when the scale factor is below 1/2 (scanlines and stripes turn into moiré).
- The host chooses the output size, the display aspect (4:3-like or square pixels) and the vertical crop (240 or 224 rows); this stage defines how to resample to the size the host chose.

## 8. Guidance per implementation form (background)

| Form | Guidance |
|---|---|
| CPU reference implementation | Write §4–§7 as they are. Match the conformance vectors pixel for pixel |
| GPU multi-pass | Split the signal stage into a pass writing Y and chroma in floating point to an 8×-wide intermediate image, and a pass that band-limits and converts to RGB. Integrate the downscale over the output pixel's footprint explicitly. **Keep the afterglow history as the small signal-stage images (8W×H) and merge the CRT stage and the afterglow into one pass that recomputes the current and past frames on the fly**; this keeps the meaning of §6 (blend after the CRT stage) without holding three large images. Frames with identical content at the same phase can skip recomputation. Measured: on an Apple GPU (Metal) about 4.9 ms/frame for a 2340×1792 window and 6.2 ms/frame at 3762×2880 (a WGSL implementation, 2026-10-04) |
| RetroArch slang shader | As above. Hold past frames with feedback plus copy passes |
| Modifying an existing emulator | Take the palette index just before the palette lookup and insert the pipeline where that emulator's video filter runs. Distributing the modified emulator follows its licence (usually GPL) |

A floating-point implementation differs from the prototype's integer rounding (truncation, round-half-up) by at most about 1/255 per stage. The tolerances in §9 allow for this.

## 9. Conformance (normative)

[conformance/vectors.json](../conformance/vectors.json) holds the reference implementation's outputs.

Test inputs (a 16×3 image with the same 16 indices in every row; cols = 128, k = 12):

```
pattern A: 0F 30 0F 30 16 16 2A 2A 12 21 30 0F 27 27 1A 0F
pattern B: 30 0F 16 21 16 16 2A 2A 12 21 30 0F 27 27 1A 0F     (only the first four pixels differ from A)
```

| Item | Content | Tolerance |
|---|---|---|
| `frame_phases` | §3.3 phase sequences (rendering on and off, 8 frames each) | exact |
| `hue_rotation_deg` | result of §4.3 | exact (350) |
| `palette64_rgb` | decoded result of each of the 64 colours (same conditions as §4.3: 64 pixels of one colour, phase0 = 0, cols = 64, column 32) | ±1 per component |
| `signal_pattern` | pattern A through the signal stage at frame phases 0, 4, 8, all pixels. Keys `p<phase>_y<row>` | ±1 per component |
| `crt_stage` | pattern A at phase 0 through the CRT stage (128×36): 12 scanline factors (stored rounded to 6 decimals), hash, first 24 pixels of rows 6, 11 and 12 | factors ±0.000001; pixels exact for integer implementations, ±2 for floating point |
| `persistence.case_motion` | rendering on (phases 0, 4, 0, 4, 0, 4); frames 0–3 pattern A, 4–5 pattern B. Each frame's input is that pattern at that phase through the signal and CRT stages. Afterglow outputs of frames 0, 1, 3, 4, 5 | exact for integer implementations, ±2 for floating point |
| `persistence.case_rendering_off` | rendering off (phases 0, 4, 8, 0, 4, 8); pattern A throughout. Afterglow output of frame 5 | same |
| `persistence.case_motion_fixed3` | the display default (fixed 3-frame cycle, phases 0, 4, 8, 0, 4, 8) with motion: frames 0–3 pattern A, 4–5 pattern B. Afterglow outputs of frames 3, 4, 5 (frame 5 in full in `frame5_output_rgb_hex`) | same |
| `moving_pixels_at_frame5` | in `case_motion`, the number of pixels of frame 5 with S (frame 3) present and d > 24. `total_pixels` is the pixel count | exact for integer implementations |
| `area_average` | the **afterglow output** of frame 3 of `case_motion` (128×36) shrunk to 50×13, all pixels (`output_rgb_hex`) | ±1 per component |

- Hashes are SHA-256 over the raw bytes, row-major, 3 bytes (R, G, B) per pixel, no header (13824 bytes for 128×36). **Verification is a separate step from reproduction**: an implementation is written from this spec alone, but checking a floating-point implementation against hash-only items needs the reference pixels, which are obtained by running the reference implementation (`reference/crt_reference.py`, `conformance/gen_vectors.py`). Running it is part of verification; reading it while implementing is not part of reproduction. Generating the expected data from the reference also lets users who modify the pipeline produce vectors that match their change.
- **Tolerances are per stage** (the difference when the stage is fed the reference implementation's output for the previous stage). End-to-end comparisons accumulate the stages' differences; the end-to-end tolerance is ±4 (measured: 2 for a WGSL implementation).
- **Motion-test boundary**: if an implementation's CRT-stage output differs from the reference by at most ε per component, its motion distance d can differ from the reference's by up to 6ε, so the test (d > 24) can flip on pixels whose reference d lies in (24 − 6ε, 24 + 6ε]. A flipped pixel can differ by up to 0.4 × 255 ≈ 102 levels (current frame alone versus the 6 : 3 : 1 blend). Exclude those pixels from the afterglow tolerance (with ε = 2: reference d from 13 to 36) and report how many were excluded. Compare stages separately (each fed the reference's previous-stage output) to keep ε small. The published vectors contain no such pixels.
- Row 6 is the middle of a source row; rows 11 and 12 straddle a source-row boundary. The vertical beam-spot average only affects boundary rows, so use them to isolate a hash mismatch.
- Vector keys vs. spec terms: `strength` = s, `mask_period` = stripe period, `spot` = spot radius, `stripe_dim` = d, `gain` = gain, `output_size` = [width, height].
- `vectors.json` carries `spec_version` = the last spec version that changed any output (currently v0.4); later spec versions that only clarify text keep the same vectors.
- `palette64_rgb` keys are two upper-case hex digits. `lines` and other `*_hex` values are the concatenated hex of 3 bytes per pixel.
- The untouched prototype's outputs (before the corrections) are kept in `conformance/vectors-v0-prototype.json`; the reference reproduces them when given the prototype's coefficients, the 12-sample luma filter and phases 0, 4, 8 (`gen_vectors.py` checks this every run). The v0.3 vectors (12-sample luma, standard coefficients) are `conformance/vectors-v0.3-mean12.json`.

Representative values: `$0F` = (0,0,0), `$00` = (98,98,98), `$10` = (171,171,171), `$20` = `$30` = (255,255,255), `$16` = (174,57,2), `$1A` = (0,147,0), `$12` = (82,52,255), `$21` = (111,164,255), `$27` = (222,169,9), `$2A` = (78,230,68).

## 10. Open items

| Tag | Item | State (v0.5) |
|---|---|---|
| D-no-same-phase | What to do when no same-phase frame exists (e.g. at the moment the phase sequence switches) | no motion test, afterglow applied (provisional) |
| D-emphasis | Support for the emphasis bits. Attenuated voltage tables exist in the source material. Observed to be always 0 in the game studied so far | not supported |
| D-noise | Whether to include the prototype's phase noise (off by default). A WGSL implementation keeps its own provisional scheme (up to 1° per row), off by default and marked experimental | not included |
| D-white-point | White point of the display. Japanese consumer TVs were commonly set to a cool white around 9300K, while the US broadcast reference is 6500K (D65). Candidate: a selectable white point (6500K / 9300K) applied after YIQ→RGB. Raised in public feedback, 2026-10-07. If added, the default stays 6500K (preferred after a 9300K test render, 2026-10-07) | not supported (the standard YIQ→RGB matrix only, i.e. 6500K) |
| D-vectors | Normative behaviour not covered by vectors: the no-same-phase case, k ≠ 12 and the automatic stripe period (including how `round` handles halves), stripe periods not divisible by 3, general cols ≠ 8W, the standard size (256×240) | not produced |

Settled: the frame phase is accumulated from the real frame length (§3.3). The YIQ→RGB coefficients are derived from the standard definition (§4.2). The default display phase mode is the fixed 3-frame cycle, the afterglow weights are 6 : 3 : 1, and the luma filter is the notch (decided 2026-10-04; switching is a future setting). The intermediate image is 8W wide (normative; with windows wider than 8W the downscale stage magnifies horizontally and a faint beat can appear in the mask), and the afterglow is applied after the CRT stage, with the lighter order allowed as a declared variant (§6) (decided 2026-10-06).

## 11. Sources

- Measured voltages (LO / HI, black, white), the 12-phase square-wave rule, and the per-row and per-frame phase shifts: NESdev Wiki, "NTSC video", https://www.nesdev.org/wiki/NTSC_video (revision 24244, as archived 2026-09-26; measurements by lidnariq). The wiki states that its content is treated as public domain.
- The frame phase (§3.3) follows from 1 dot = 8 samples and 1 cycle = 12 samples (89342 × 8 ≡ 4, 89341 × 8 ≡ 8 mod 12), consistent with the "NTSC video" page. The wiki's "PPU frame timing" page (https://www.nesdev.org/wiki/PPU_frame_timing) has a sentence that reads the other way round (3 states normally, 2 when the skipped dot is avoided), which does not match the arithmetic. Not yet verified against captures of real hardware.
- YIQ→RGB coefficients: computed from the standard definition (§4.2 background). The prototype used values from Bisqwit's published material; replaced in v0.2.
- The decoding filter structure, the CRT stage, the afterglow stage and the downscale stage: this project's own design, from its prototype.
- No code from existing shaders or libraries (GTU-famicom, patchy-ntsc, nes_ntsc, fami-rf and others) is used.

## 12. Blind reproduction tests

An agent that has never seen the prototype is given only this spec and the vectors and asked to implement; the result is compared with the vectors.

| # | Date | Scope | Result | Fed back |
|---|---|---|---|---|
| 1 | 2026-10-03 | signal and CRT stages (pure Python, spec v0) | The signal stage matched every item on the first attempt (hue rotation 350, 64 colours, 1152 pattern pixels all with error 0). The CRT stage mismatched at first (546/4608 pixels, max error 2) and matched to the hash once truncation was read as "per direction" for the spot and bloom | v0.1: truncation positions (§5 steps 2 and 6), rounding formulas, scoring of the hue rotation made normative (§4.3), edge handling and precision moved to §2, hash definition and boundary-row vectors added to §9 |
| 2 | 2026-10-03 | all stages (frame phase, signal, CRT, afterglow, downscale; pure Python, spec v0.2) | **All 38 items matched on the first run** (error 0, implementation unmodified). Sensitivity experiments showed that the afterglow blend depended on floating-point evaluation order (an integer implementation differs on 237/4608 pixels) | v0.3: the afterglow blend redefined as an integer formula and vectors regenerated (the round-2 implementation with that formula matches the new vectors 38/38); downscale weights moved to §7; substitution rule and choice of S (§6), frame numbering (§3.3), edge handling (§2), bilinear formula (§5), test inputs and item definitions (§9) made explicit |
| — | 2026-10-04 | all stages in WGSL (GPU) with a CPU check implementation, by a separate team, spec v0.4 | CPU: every hash matched, hue rotation 350, moving-pixel counts 1410/1405 matched. GPU: max error 0 (signal), 1 (CRT, afterglow), 1 (downscale) | v0.5: §8 implementation shape and performance, §9 per-stage vs end-to-end tolerance and motion-boundary exclusion, §10 notes |

Revision notes: v0.2 (2026-10-03) changed the frame phase from "always +4" to accumulation from the frame length, and the YIQ→RGB coefficients to values derived from the standard definition (64-colour change ≤ 2/255 per component; hue rotation stays 350°); the afterglow comparison frame changed from "3 frames back" to "the same-phase frame"; vectors regenerated. v0.3 (same day) made the afterglow blend an integer formula (differs from the prototype's floating-point blend by 1 on pixels whose fraction is exactly 0.5). v0.4 (2026-10-04) changed the luma filter to the notch (single colours and the 350° rotation unchanged; pattern, CRT, afterglow and downscale vectors regenerated). v0.5 (same day) added the GPU implementation shape to §8 and the per-stage/end-to-end tolerance distinction and motion-boundary exclusion to §9. v0.6 (2026-10-07) fixed points raised in an external review: frame-number hosts follow the default fixed 3-frame cycle (§3.3); the same-phase frame is stated per phase sequence (§6); the phase anchor, cropped inputs and greyscale input are defined (§3.1); the automatic stripe period uses round-half-up (§5); the chroma bandwidth is stated as measured (§4.2); the 240p note is scoped to the NTSC 2C02 (§5); verification is separated from reproduction and the motion-boundary exclusion is derived from the upstream error (§9); source URLs added (§11). Outputs for the default k = 12 are unchanged.
