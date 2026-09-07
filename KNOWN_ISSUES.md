# Known issues — 2026-09-07.1

- Broad route, audible voice/music, and full-game regression testing remain
  incomplete. All known text in the audited banks is translated; this is not
  a claim that every possible screen has been reached in a playthrough.
- PCSX-Redux can stall during battle effects with its current VBlank cadence.
  This also reproduces with the original Japanese disc. A permanent timing
  correction is pending. The rejected phase-10 completion guard is excluded
  from this build.
- Old emulator savestates contain the previous executable and text in RAM.
  Start the updated disc and load an in-game memory-card save to receive the
  new text. Loading an old savestate can restore old Japanese text and old code.
- The compact currency inserts use G (gold), S (silver), and C (copper).
  One gold coin equals 20 silver coins or 400 copper coins.
