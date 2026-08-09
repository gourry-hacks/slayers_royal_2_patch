# Slayers Royal 2 English Patch

## TL;DR

1. Provide your own supported `sr2.bin` and prepare the exact `sr2.cue`
   described below. The required BIN SHA-256 is
   `f3c307b4ba5fd5687da6a24338df2d214a680670239ed93488285007431503e9`.
2. Run:

   ```bash
   python3 patch.py --bin "/path/to/sr2.bin" --cue "/path/to/sr2.cue"
   ```

3. Load `output/sr2_patched.cue` in a PlayStation emulator.

This repository patches the Japanese PlayStation release of *Slayers Royal 2*
(`SLPS-02115`) into English.

It does **not** include the game. You must provide your own matching BIN/CUE
dump of the original disc. The patcher checks the complete source hashes and
refuses incompatible images.

## Patch Scope

The current patch includes:

- all 7,092 story, interaction, choice, notification, and location records;
- all 203 textual item, equipment, food, help, and configuration records;
- all 88 textual battle-overlay records;
- English fonts, wrapping, pagination, and runtime support for oversized
  translated scene modules;
- one-row layout fixes for all audited selection menus, cursor-preserving
  joined-dialogue fixes, and corrected period/ellipsis placement;
- translated title, route, warning, ending-credit, exploration-placard, and
  travel-map graphics;
- reviewed burned-in English subtitles for all ten FMV clips.

The complete disc is rebuilt and independently checked for pointers, packed
resources, selected FMV sectors, and unchanged XA audio sectors. The opening
and local travel map have also been smoke-tested from a clean disc in
PCSX-Redux. Broader route and full-playthrough QA are ongoing.

## What You Need

- A legal copy of the Japanese PlayStation game
- A matching raw `MODE2/2352` BIN dump
- Python 3.10 or newer
- About 900 MiB of free disk space
- This complete repository, including every file under `patches/`

No Python packages or external patching programs are required.

## 1. Prepare The Original Files

Name the original files:

```text
sr2.bin
sr2.cue
```

The supported BIN must be exactly:

| Property | Expected value |
| --- | --- |
| Size | `717101280` bytes |
| SHA-256 | `f3c307b4ba5fd5687da6a24338df2d214a680670239ed93488285007431503e9` |

The BIN hash is the authoritative check that you have the supported disc dump.

The required `sr2.cue` is 69 bytes, uses CRLF line endings, and contains:

```cue
FILE "sr2.bin" BINARY
  TRACK 01 MODE2/2352
    INDEX 01 00:00:00
```

Its SHA-256 is:

```text
b7748ac4657613a78ee5a2be6e931004d38bc185130edeefe68505e8d5ec17c0
```

If your dumping software created an equivalent CUE with a different BIN
filename or line endings, place `sr2.bin` in a working directory and generate
the exact supported CUE there.

Linux or macOS:

```bash
python3 -c 'from pathlib import Path; Path("sr2.cue").write_bytes(b"FILE \"sr2.bin\" BINARY\r\n  TRACK 01 MODE2/2352\r\n    INDEX 01 00:00:00\r\n")'
```

Windows:

```powershell
$cue = "FILE `"sr2.bin`" BINARY`r`n  TRACK 01 MODE2/2352`r`n    INDEX 01 00:00:00`r`n"
[System.IO.File]::WriteAllBytes("sr2.cue", [System.Text.Encoding]::ASCII.GetBytes($cue))
```

Creating this descriptor does not modify the BIN or any game data.

## 2. Verify The Source

From the repository directory, run the patcher's verification mode.

Linux or macOS:

```bash
python3 patch.py \
  --bin "/path/to/sr2.bin" \
  --cue "/path/to/sr2.cue" \
  --verify-only
```

Windows:

```powershell
py -3 patch.py --bin "C:\path\to\sr2.bin" --cue "C:\path\to\sr2.cue" --verify-only
```

Successful verification ends with:

```text
source and patch files are valid
```

If verification reports a source hash mismatch, do not continue. Redump the
disc or correct the CUE descriptor. A different game revision cannot be safely
patched.

## 3. Apply The Patch

Linux or macOS:

```bash
python3 patch.py \
  --bin "/path/to/sr2.bin" \
  --cue "/path/to/sr2.cue"
```

Windows:

```powershell
py -3 patch.py --bin "C:\path\to\sr2.bin" --cue "C:\path\to\sr2.cue"
```

By default, the patcher creates an `output/` directory beside `patch.py`. To
choose another directory, add:

```text
--output-dir "/path/to/output"
```

The patcher never modifies the original files. Existing output files are not
replaced unless you add `--force`.

## 4. Run The Patched Game

A successful patch creates:

```text
output/
  sr2_patched.bin
  sr2_patched.cue
```

Expected results:

| File | Size | SHA-256 |
| --- | ---: | --- |
| `sr2_patched.bin` | 737,086,224 bytes | `6af42d766bc5aaa3a695f602feea00fb85d1f611f705c40e85a2ec06cfd09f1a` |
| `sr2_patched.cue` | 77 bytes | `7e0a6c027d263fa572337c7043d0aafabb7211333580699114e6544b65e5fabb` |

Load `sr2_patched.cue`, not the BIN directly, in a PlayStation emulator.

## Troubleshooting

### `source BIN is not the supported source file`

The BIN is a different revision, dump format, or incomplete copy. The patch
requires the exact 717,101,280-byte `MODE2/2352` image listed above.

### `source CUE is not the supported source file`

The CUE probably has a different referenced filename or line-ending format.
Regenerate the 69-byte CUE using the command in step 1.

### `patch part ... does not exist` or a patch hash mismatch

The repository download is incomplete or corrupted. Download the complete
repository again. All numbered files under `patches/` are required.

### `output already exists`

Move the previous output elsewhere, choose another `--output-dir`, or rerun
with `--force` if replacing it is intentional.

### `not enough free space`

Choose an output directory on a filesystem with at least 900 MiB free.

## How The Patch Works

The project-specific `SLRXOR1` format compares the source and translated files
in 64 KiB blocks. It stores only nonzero `source XOR target` blocks, compresses
the container with XZ, and splits it into files below GitHub's large-file
warning threshold.

Applying the patch begins with the verified source and XORs the stored changes
back into their original offsets. The patch data does not contain a playable
disc image, and it cannot reconstruct the translated game without the matching
source files.

The machine-readable source, patch-part, and output hashes are recorded in
`release_manifest.json`.

## Maintainer Rebuild

This section is for translation maintainers, not ordinary users.

With the repository at `royal2/slayers_royal_2/`, the original files at
`royal2/sr2.bin` and `royal2/sr2.cue`, and canonical translated files under
`royal2/patched/`, regenerate the release with:

```bash
python3 royal2/slayers_royal_2/maintainer/build_release.py
```

Use `--help` to override those paths. Building the highly compressed release
requires approximately 1 GiB of RAM. Always run the consumer patcher afterward
and byte-compare its output with the canonical BIN/CUE before publishing.

## Legal Notice

The game, characters, audiovisual material, and other original assets remain
the property of their respective rights holders. This repository distributes
only patching code and source-dependent binary differences.
