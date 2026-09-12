"""English encoding assignments for Slayers Royal 2."""

from __future__ import annotations

import string


# Native Royal 2 cells that already contain these ASCII glyphs.
CHAR_TO_GLYPH = {
    "!": 0x00A6,
    "?": 0x00A7,
    **{str(value): 0x00A8 + value for value in range(10)},
    "A": 0x03F1,
    "B": 0x03F2,
    # 0x007D is globally unused in the extracted scene/global text banks.
    " ": 0x007D,
}


# These cells do not occur in any of the 7,326 currently extracted Royal 2
# scene/global records. Their original Japanese glyphs remain documented in
# the source atlas, but can be replaced without damaging untranslated text in
# those banks. Keep this list stable: its order defines the patch encoding.
REPLACEMENT_GLYPHS = (
    0x004B, 0x0081, 0x0090, 0x0091, 0x00B6, 0x00BA, 0x00BB, 0x00BD,
    0x00BF, 0x00D9, 0x00DD, 0x00FB, 0x0101, 0x010D, 0x0110, 0x0135,
    0x0148, 0x014D, 0x014F, 0x0151, 0x0157, 0x0163, 0x0168, 0x0169,
    0x016D, 0x016E, 0x0170, 0x0178, 0x017D, 0x0181, 0x018E, 0x019A,
    0x01A7, 0x01AB, 0x01B2, 0x01BF, 0x01C3, 0x01C6, 0x01D2, 0x01D8,
    0x01DA, 0x01EF, 0x01F6, 0x01F7, 0x01FA, 0x01FD, 0x01FF, 0x0200,
    0x0209, 0x020A, 0x020B, 0x0210, 0x0213, 0x021B, 0x021C, 0x021E,
    0x021F, 0x0222, 0x022A, 0x022B, 0x0236, 0x023D, 0x0242, 0x0247,
    0x024B, 0x0252, 0x0259, 0x025A, 0x025E, 0x0260, 0x0262, 0x0265,
    0x026C, 0x026F, 0x0271, 0x0275, 0x0276, 0x0278, 0x0279, 0x027A,
)


_replacement_characters = [
    character
    for character in string.printable
    if 0x20 <= ord(character) <= 0x7E and character not in CHAR_TO_GLYPH
]
if len(_replacement_characters) != len(REPLACEMENT_GLYPHS):
    raise AssertionError(
        f"ASCII assignment mismatch: {len(_replacement_characters)} characters, "
        f"{len(REPLACEMENT_GLYPHS)} cells"
    )
CHAR_TO_GLYPH.update(zip(_replacement_characters, REPLACEMENT_GLYPHS))

GLYPH_TO_CHAR = {glyph: character for character, glyph in CHAR_TO_GLYPH.items()}
if len(GLYPH_TO_CHAR) != len(CHAR_TO_GLYPH):
    raise AssertionError("English glyph assignments are not one-to-one")
if set(CHAR_TO_GLYPH) != {chr(value) for value in range(0x20, 0x7F)}:
    raise AssertionError("English glyph map must cover printable ASCII exactly")


# BATTLE.BIN's compact spell-list renderer displays at most ten 16x16 cells.
# These fifteen cells are unused by every extracted scene/global record and
# by the source BATTLE.BIN help bank.  Drawing two Latin characters in each
# cell lets all 43 spell names retain their full localized names without a
# renderer hook or abbreviations.
BATTLE_SPELL_COMPACT_GLYPHS = {
    token: glyph_id
    for token, glyph_id in zip(
        (
            " B",
            "A ",
            "AL",
            "AR",
            "DI",
            "IN",
            "LA",
            "ME",
            "ON",
            "OW",
            "RA",
            "RE",
            "ST",
            "LI",
            "NA",
        ),
        (*range(0x03F3, 0x0400), 0x03ED, 0x03EE),
        strict=True,
    )
}
if set(BATTLE_SPELL_COMPACT_GLYPHS.values()) & set(CHAR_TO_GLYPH.values()):
    raise AssertionError("compact spell glyphs overlap normal English glyphs")


# The battle Magic menu does not consume the normal FONT.CHR glyph IDs above.
# It indexes a dedicated sequence of 51 small TIMs in BATTLE.ST2:GOUR006.
# Reserve the first 27 cells for A-Z and space, followed by the same compact
# pairs used to keep every localized spell name within ten visible cells.
BATTLE_SPELL_MENU_GLYPHS = {
    token: index
    for index, token in enumerate(
        (*string.ascii_uppercase, " ", *BATTLE_SPELL_COMPACT_GLYPHS)
    )
}
if len(BATTLE_SPELL_MENU_GLYPHS) > 51:
    raise AssertionError("battle spell menu glyph assignments exceed GOUR006")


# Long exploration placards must fit the retail ten-sprite text allocation.
# These source-unused cells hold two 8x16 English letters in FONT.CHR only.
# Keep assignments stable; the font builder checks all known source owners.
PLACARD_COMPACT_GLYPHS = {
    ' A': 0x027C,
    ' C': 0x0285,
    ' D': 0x0286,
    ' E': 0x028B,
    ' G': 0x028C,
    ' H': 0x028D,
    ' N': 0x028E,
    ' R': 0x028F,
    ' S': 0x0295,
    ' T': 0x0296,
    ' W': 0x0299,
    '/N': 0x029F,
    'A ': 0x02A1,
    'AL': 0x02B1,
    'AR': 0x02B4,
    'AS': 0x02B6,
    'AV': 0x02B7,
    'AZ': 0x02BA,
    'BA': 0x02BC,
    'CA': 0x02C0,
    'CE': 0x02C1,
    'CI': 0x02C2,
    'CT': 0x02C3,
    'D ': 0x02CA,
    'DO': 0x02CF,
    'E ': 0x02D5,
    'ED': 0x02D7,
    'EG': 0x02D9,
    'EO': 0x02DB,
    'ER': 0x02DC,
    'ES': 0x02DD,
    'FO': 0x02DE,
    'GE': 0x02DF,
    'GR': 0x02E1,
    'GU': 0x02E2,
    'HE': 0x02E4,
    'HO': 0x02E6,
    'ID': 0x02EB,
    'IM': 0x02ED,
    'IN': 0x02EE,
    'IR': 0x02F4,
    'IT': 0x02F9,
    'KE': 0x02FC,
    'L ': 0x02FD,
    'LA': 0x0302,
    'LD': 0x0303,
    'LN': 0x030E,
    'MA': 0x0316,
    'MI': 0x031A,
    'MO': 0x031E,
    'MP': 0x0320,
    'MT': 0x0323,
    'N ': 0x0324,
    'NC': 0x0328,
    'ND': 0x032E,
    'NG': 0x0330,
    'NI': 0x0332,
    'NT': 0x0333,
    'OL': 0x0334,
    'OM': 0x0339,
    'ON': 0x033D,
    'OW': 0x0340,
    'PL': 0x034D,
    'R ': 0x034F,
    'RA': 0x0350,
    'RD': 0x0352,
    'RE': 0x0354,
    'RO': 0x0357,
    'RP': 0x0358,
    'RT': 0x035A,
    'S ': 0x035B,
    'SE': 0x035C,
    'SI': 0x0361,
    'ST': 0x0366,
    'T ': 0x0367,
    'TA': 0x0369,
    'TE': 0x036B,
    'TO': 0x0379,
    'TY': 0x037A,
    'UI': 0x037D,
    'UN': 0x037F,
    'US': 0x0382,
    'UT': 0x0383,
    'VA': 0x0384,
    'VE': 0x0385,
    'WE': 0x0388,
    'YN': 0x038A,
}
if set(PLACARD_COMPACT_GLYPHS.values()) & (
    set(CHAR_TO_GLYPH.values()) | set(BATTLE_SPELL_COMPACT_GLYPHS.values())
):
    raise AssertionError("placard glyph assignments overlap another English font owner")


def encode_placard(text: str) -> list[int]:
    if len(text) <= 9:
        return encode(text)
    try:
        result = [PLACARD_COMPACT_GLYPHS[text[i:i + 2].ljust(2)]
                  for i in range(0, len(text), 2)]
    except KeyError as error:
        raise ValueError(f"unassigned compact placard pair: {error.args[0]!r}") from error
    if len(result) > 10:
        raise ValueError(f"placard exceeds ten native glyph cells: {text!r}")
    return result


def encode(text: str) -> list[int]:
    try:
        return [CHAR_TO_GLYPH[character] for character in text]
    except KeyError as error:
        character = str(error.args[0])
        raise ValueError(
            f"unsupported English character {character!r} (U+{ord(character):04X})"
        ) from error
