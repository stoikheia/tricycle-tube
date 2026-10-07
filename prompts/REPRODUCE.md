# Reproduction prompt

Hand an agent the two files and this prompt. Replace the parts in angle brackets. Earlier versions of this prompt were used, with no other material, in the blind reproduction tests recorded in the spec (§12).

---

You are implementing a display pipeline from a written specification. You have exactly two inputs:

- `SPEC.md` — the specification. Sections marked "(normative)" are binding; "Background" paragraphs explain intent.
- `vectors.json` — expected outputs produced by the reference implementation, with tolerances defined in SPEC.md §9.

Target: <describe the host — e.g. "a Rust emulator whose PPU exposes per-pixel palette indices and dots-per-frame", "a WGSL post-process in wgpu", "a RetroArch slang preset reading a raw-palette core", "pure Python">.

Rules:
1. Implement every stage in SPEC.md §3.3, §4, §5, §6 and §7. Use the defaults stated there (fixed 3-frame display phase mode, k = 12, stripe period 9, afterglow 6:3:1, notch luma) unless the target cannot express them; if so, say what you changed and why.
2. While implementing, do not look for or read any other implementation of this pipeline (including the reference implementation). Where the spec is ambiguous, choose the most literal reading and record the choice.
3. Write a checker that compares your output with every item in `vectors.json`, applying the tolerances from §9. Verification is a separate step (§9): for a floating-point implementation, the reference pixels for hash-only items may be produced by *running* `reference/crt_reference.py` / `conformance/gen_vectors.py`, without reading them. Hash items are exact for integer implementations; floating-point implementations compare pixels against the reference values with the stated tolerance and exclude motion-boundary pixels as §9 describes.
4. Run the checker on your **first complete** implementation and save that output before making any adjustment toward the vectors. Then fix mismatches, recording each interpretation you changed.
5. Report: a table of items (first run and final: match / mismatch, max absolute error, mismatching pixels / total); the interpretations you changed; every place where the spec was ambiguous, missing or wrong, with the section number; assumptions you had to make that the spec does not state; the size of your implementation. Do not report an item as matching unless the checker output shows it.

If you also integrate the pipeline into a running host, additionally report the frame time at the host's native window size and whether the host supplies real dots-per-frame (hardware-faithful mode) or only a frame counter.
