# Localization toolkit verification — 2026-09-12

The new `localize.py` workflow is additive; the packaged English XOR parts,
release manifest and canonical disc files are unchanged.

- Exported 7,122 entries from the verified original disc, with English
  reference text reconstructed from the release patch.
- An empty catalog with English fallback reproduces the canonical English BIN
  SHA-256 exactly: `972a2f9d7c9d3ae57d6d6ade21e813d5168d5abc96d453e07940a4aaa84e0783`.
- A partial Cyrillic build exercises actual localized text and font generation.
  Royal 2's opening uses the compressed-scene path, with unedited records
  expanded/recompressed and pointers checked on readback.
- Complete synthetic Cyrillic catalogs exercise every supported record and
  preserve untouched resources/code/control data. Synthetic strings test the
  compiler; they are not translations or evidence of a full playthrough.
- Independent PCSX-Redux C EDC/ECC regeneration agrees on every modified or
  appended sector. The Python writer is not its own only checksum oracle.
- Russian, French, Spanish and German authoring presets compile with their
  complete reserved alphabets and representative accented text. Glyph proof
  sheets are generated for visual review; font lookup/allocation is bounded.
- Focused tests cover source/ID/control changes, duplicates, fuzzy entries,
  Unicode/layout rejection, output-path containment, fixed extents and Form 2
  write rejection. Game-specific tests exercise relocation/dictionaries/font
  compression (Royal 2) or ELS offsets/carrier encoding (Wonderful).

These tests establish build/readback coverage, not emulator playability of a
finished localization. No complete target-language catalog exists yet. Newly
localized text, accents and scene layouts require emulator review before
publishing a language patch. The toolkit README lists excluded text/art domains.
Private evidence and generated catalogs are in `qa/localization_20260912/` in
the Slayers workspace; original-disc text and test disc images are not committed.

# Validation — 2026-09-11.1

The Status correction changes two call sites and installs two three-instruction
thunks inside an existing reserved allocation. The compressed input moves from
`0x80140000` to `0x80138000`; decoded output remains at `0x80100000`. Its new
footprint is contained in the original Status routine's memory footprint.
Native instruction replay checks every output write against unread input and
produces the same 295,680 decoded bytes. The build rejects unsafe input growth,
unsafe input/output overlap, changed caller instructions, and occupied thunk
storage. Six focused regression tests pass.

The completed full disc verifier passes, and comparison with 2026-09-07.1
shows changes in only raw sectors 292 and 412. Every other sector, including
all translated graphics/text, FMV, audio, and battle code, is identical.

A fresh isolated PCSX-Redux process booted the full rebuilt disc and started a
new game. The correction was read back from the loaded code without injecting
RAM or loading an old savestate. Normal Camp > Status entry, Lina/Gourry page
switching, and exit preserved every byte of the complete AREA window; the
previous release changed 4,591 bytes. Subsequent Move navigation opened the
town map. These checks address this regression; they do not certify a full
playthrough or resolve the separate original-disc timing/card issues.

The release candidate passes source hashes, translation/control/layout checks,
all fixed allocations and relocated pointers, and complete patched-resource
disc readback. This includes the existing 7,092 scene records, 203 global text
records, 88 battle text records, battle spell and HUD assets, save/load assets,
travel maps, status screens, and all ten subtitle patches with unchanged XA
sectors.

The new BASYO coverage includes 58 exploration conversations/tutorials and
383 additional static records (including 43 placeholders and 32 empty slots).
The additional banks contain equipment/item/food names, item-use results,
haggling choices and dialogue, purchases/sales, restaurant conversations, and
inn dialogue. Nineteen fixed TITLE card-message copies, seventeen fixed
shop/meal/inn labels, currency inserts, and the five time-of-day pointers are
also checked. All 468 previously outstanding source fragments are covered.

The assembled MIPS decoder is exercised against every word of all 441 embedded
records with R3000 load and branch delays modeled, randomized temporary
registers, interrupted message owners, and the existing AREA/global dictionary
paths. Literal names and choices remain uncompressed for their secondary
consumers. All 477 additional absolute data pointers are checked.

Focused PCSX-Redux tests run in a separate emulator with copied memory cards
and a copied fatigue checkpoint. They verify the item-use message, its dynamic
character name and result page, and haggling-choice text. Shop/inn dynamic-text
previews omit only the initial shopkeeper portrait control, because that
portrait is unavailable in the street checkpoint. They exercise relocated item
names and the maximum-width English currency/time fields. These previews are
not a cold-disc traversal of those shops or proof of every portrait/voice.

The packaged consumer patch is applied to the supported original BIN/CUE and
both reconstructed outputs must match the verified candidate byte for byte.
See `release_manifest.json` for the exact source, target, and patch-part hashes.
