# Royal 2 localization toolkit

This follows Royal 1's export → PO translation → validation → disc-build
workflow. Version 0.1 covers 7,122 records across all 21 AREA modules: 7,092 established records and 30 recovered spans.
Japanese text and the English reference are extracted from the contributor's
own verified disc and the packaged English XOR patch. No source script or
font artwork is bundled with this toolkit.

The compiler relocates scene pointers, preserves voice/portrait/effect controls,
compresses large scenes using the existing runtime dictionary, and refuses
anything beyond the proven `0x2FEC4` AREA allocation. It updates all three
compressed fonts and the EVE resource directory. Font dimensions stay fixed,
and compressed input stays within the original Japanese/English font budget. The localized EVE archive is
appended to the output disc, with ISO and BASYO locations updated together.
Unchanged resources are checked byte for byte. The global text bank, embedded
shop/inn text, battle text, bitmap UI, credits and FMVs retain English.

## Requirements

- Python 3.10 or newer and the complete patcher repository, including `patches/`.
- Pillow: `python3 -m pip install -r localization/requirements.txt`.
- The exact original Japanese BIN supported by the English patcher. No CUE is
  needed for localization, regardless of the consumer English patcher's CUE policy.
- About 1.2 GiB free for a staged disc, output, and extracted resources.
- A font covering the chosen language. DejaVu Sans Condensed Bold, Windows
  Arial Bold, and macOS Arial Bold are detected; pass `--font /path/to/font.ttf`
  to `validate` and `build` to select another font.

## Export

Run from this repository:

```sh
python3 localize.py export --bin /path/to/sr2.bin --locale ru --output localization-work/ru
```

This creates `dialogue.po`, `language.json`, and `source_inventory.json`.
`msgctxt` is the stable ID and `msgid` is Japanese source text: leave both
unchanged. Write the target language in `msgstr`. Each entry includes its
English reference and layout limits in comments. New workspaces have empty
translations; none of the bundled language presets claims a translated game.
Existing catalogs are protected unless `--force` is explicitly supplied.

Use explicit `\n` line breaks. Follow each entry's column/line limits; the
compiler does not silently wrap or truncate text. Royal 2 control placeholders
such as `<C:9100>` must remain in their original order. They preserve game
presentation/effects and do not count toward visible line width. Wonderful
entries have no such placeholders. Do not introduce raw game control bytes.

## Validate and build

```sh
python3 localize.py validate --bin /path/to/sr2.bin --locale ru --workspace localization-work/ru --allow-incomplete
python3 localize.py build --bin /path/to/sr2.bin --locale ru --workspace localization-work/ru --allow-incomplete --output-dir localization-output/ru
```

Remove `--allow-incomplete` when the catalog is ready for a complete release.
With it, empty entries keep the canonical English text. Without it, even one
missing translation fails. An entirely empty diagnostic catalog reproduces
the canonical English BIN exactly. Fuzzy PO entries are rejected until reviewed.

Validation also compiles in memory: it checks controls, font capacity, Unicode
normalization, bank/runtime limits and script readback. Both commands verify
the original disc and reconstruct the pinned English base in temporary space.
This costs more than a text-only lint pass but validates the actual build.

Builds generate `slayers_royal2_ru.bin` and `.cue`. Open the CUE in a PlayStation
emulator. The canonical English files and source disc are never the build
location. Existing outputs require `--force`; never use a source disc directory
as the output directory. All modified/appended Form 1 sectors receive EDC/ECC.

`localization-work/ru/build/build_report.json` records coverage, glyph mapping,
capacity/pointer results and output hash. `locale_glyphs.png` is an enlarged
font review sheet. Generated workspaces/discs/proofs are ignored by Git.

## Other languages and limits

Russian (`ru`), French (`fr`), Spanish (`es`) and German (`de`) definitions are
included. Add a JSON file modeled on those definitions and supply it with
`export --locale CODE --language /path/to/CODE.json`. Its `required_characters`
reserves an alphabet; the compiler also allocates characters actually used by
translations. Output names must contain only ASCII letters, digits, `_` or `-`.

This adapter supports separate, left-to-right glyph cells. RTL shaping,
combining marks and fonts missing required glyphs fail validation. Larger
alphabets may exhaust the available cells. A successful build establishes
structural safety, not linguistic quality or that every line looks good.
Test the translated scenes, menu choices and font accents in an emulator
before distributing a language patch; do not reuse old emulator savestates.

Only the domains listed above are localized in this version. Additional
system/menu, graphics and FMV adapters remain future work, as in Royal 1's
initial toolkit. The Linux-native game is not modified by this tool.

## Maintainer checks

```sh
python3 -m unittest discover -s localization/tests -v
```

The adapter pins the English base and fails closed on a new release until its
layout/font assumptions are reviewed. Keep original-disc extraction local;
commit intentional target-language catalogs separately, not generated source
inventories or disc images. See the repository `QA.md` for tested coverage.

Maintainers can regenerate the source/English range index from the private
production workspace and a BIN reconstructed by the current consumer patcher:

```sh
python3 maintainer/build_localization_layout.py --workspace /path/to/slayers --english-bin /path/to/sr2_patched.bin
```

This replays the production scene compiler and requires every rebuilt AREA to
match the packaged English disc before recording offsets. The index contains
only IDs, ranges, anchors and hashes, not source dialogue or bytecode.
