"""Royal 2 scene relocation, dictionary compression and locale fonts."""
from __future__ import annotations
import hashlib
import json
import re
import struct
from pathlib import Path
from .common import Entry, CONTROL, font_path, raster, proof_sheet
from .disc import Disc
from .inventory import build_inventory
from .area import Edit, OffsetMap, transform_area
from .tokens import AREA_LOCAL_CAPACITY, read_area_dictionary, expand_token_words, build_token_dictionary, append_area_dictionary
from .english import CHAR_TO_GLYPH, GLYPH_TO_CHAR, BATTLE_SPELL_COMPACT_GLYPHS, PLACARD_COMPACT_GLYPHS
from .charmap import CHARMAP
from .lzss import compress, decompress
from .repack import repack
TITLE = 'Slayers Royal 2'
EVE = '/EVE_DATA.ST2'
BASYO = '/BASYO.BIN'

def digest(data):
    return hashlib.sha256(data).hexdigest()

def unpack(data):
    if len(data) % 2:
        raise ValueError('unaligned script words')
    return list(struct.unpack(f'<{len(data) // 2}H', data))

def pack(words):
    return struct.pack(f'<{len(words)}H', *words)

def control(w):
    return w >= 0x8000 or w in (0, 0xfd, 0xff)

def decode(words, charmap):
    return ''.join(('\n' if w == 0xfe else f'<C:{w:04X}>' if control(w) else charmap.get(w, f'<G:{w:04X}>') for w in words))

def encode_text(text, charmap, columns, terminated):
    words = []
    lines = text.split('\n')
    for n, line in enumerate(lines):
        if n:
            words.append(0xfd if terminated and n % 3 == 0 else 0xfe)
        offset = 0
        for match in CONTROL.finditer(line):
            words.extend((charmap[c] for c in line[offset:match.start()]))
            words.append(int(match.group()[3:7], 16))
            offset = match.end()
        words.extend((charmap[c] for c in line[offset:]))
    return words

def tim_info(tim):
    if tim[:8] != bytes.fromhex('1000000008000000'):
        raise ValueError('locale font is not a 4bpp TIM')
    clut = struct.unpack_from('<I', tim, 8)[0]
    image = 8 + clut
    _, _, _, w, h = struct.unpack_from('<IHHHH', tim, image)
    if image + 12 + w * 2 * h != len(tim):
        raise ValueError('font TIM payload bounds changed')
    return (image + 12, w * 4, h)

def cell(tim, glyph, width, height, base=0):
    pos, w, h = tim_info(tim)
    i = glyph - base
    x = i % 32 * width
    y = i // 32 * height
    if i < 0 or y + height > h:
        raise ValueError('glyph outside font')
    return b''.join((tim[pos + (y + r) * (w // 2) + x // 2:pos + (y + r) * (w // 2) + x // 2 + width // 2] for r in range(height)))

def paint(tim, glyph, width, height, base, mask):
    pos, w, h = tim_info(tim)
    i = glyph - base
    x = i % 32 * width
    y = i // 32 * height
    if i < 0 or y + height > h:
        raise ValueError('glyph outside font')
    palette = struct.unpack_from('<16H', tim, 20)
    foreground = max(range(16), key=lambda n: sum((palette[n] >> k & 31 for k in (0, 5, 10))))
    background = 0
    for yy in range(height):
        for xx in range(width):
            value = foreground if mask.getpixel((xx, yy)) else background
            at = pos + (y + yy) * (w // 2) + (x + xx) // 2
            shift = (x + xx) % 2 * 4
            tim[at] = tim[at] & ~(15 << shift) | value << shift

class Project:
    scope = 'All 21 AREA scene modules, including recovered spans. Global/system/battle text, bitmap labels and FMVs retain English.'

    def __init__(self, source, english, manifest):
        self.layout = json.loads((Path(__file__).parent / 'layout.json').read_text())
        if manifest['target']['bin']['sha256'] != self.layout['english_bin_sha256']:
            raise ValueError('layout index needs regeneration for this English base')
        self.disc = Disc(english)
        source = Disc(source)
        self.basyo = self.disc.file(BASYO)
        self.eve = self.disc.file(EVE)
        self.eve_lba = self.disc.files[EVE]['lba']
        self.source_eve = source.file(EVE)
        self.source_basyo = source.file(BASYO)
        self.resources = {r['name']: r for r in build_inventory(self.basyo, self.eve, self.eve_lba)['resources']}
        self.source_resources = {r['name']: r for r in build_inventory(self.source_basyo, self.source_eve, source.files[EVE]['lba'])['resources']}
        self.catalog = []
        self.records = {}
        self.areas = {}
        self.occupied = set(CHAR_TO_GLYPH.values()) | set(BATTLE_SPELL_COMPACT_GLYPHS.values()) | set(PLACARD_COMPACT_GLYPHS.values()) | {0, 0xfd, 0xfe, 0xff}
        for module in self.layout['modules']:
            name = module['name']
            src = self.resource(name, True)
            eng = self.resource(name)
            if digest(src) != module['source_sha256'] or digest(eng) != module['english_sha256']:
                raise ValueError(f'{name}: scene layout hash mismatch')
            self.areas[name] = src
            dictionary = read_area_dictionary(eng)[0] if eng[-4:] == b'SR2T' else []
            for row in module['records']:
                s = unpack(src[row['source_start']:row['source_end']])
                e = expand_token_words(unpack(eng[row['english_start']:row['english_end']]), dictionary)
                prefix = 1 if row['voice'] else 0
                end = -1 if row['terminated'] else len(s)
                body = s[prefix:end]
                ebody = e[prefix:-1 if row['terminated'] else len(e)]
                if prefix and s[0] != e[0] or (row['terminated'] and s[-1] != e[-1]):
                    raise ValueError('English record framing changed')
                controls = tuple((f'<C:{w:04X}>' for w in body if control(w)))
                source_text = decode(body, CHARMAP)
                english_text = decode(ebody, GLYPH_TO_CHAR)
                english_text = english_text.replace('<C:00FD>', '\n')
                key = 'dialogue/' + row['id']
                limit = max(3, english_text.count('\n') + 1) if row['terminated'] and s[-1] == 0xfd else max(1, english_text.count('\n') + 1)
                self.catalog.append(Entry(key, source_text, english_text, 36, limit, controls))
                self.records[key] = dict(meta=row, module=name, source=s, english=e)
                self.occupied.update((w for w in e if 0 < w < 0x400))
        self.replacements = {}
        self.output_basyo = None

    def entries(self):
        return self.catalog

    def resource(self, name, source=False):
        r = (self.source_resources if source else self.resources)[name]
        data = self.source_eve if source else self.eve
        return data[r['start_offset']:r['start_offset'] + r['declared_size']]

    def compile(self, translations, language, font, proof_dir):
        if not translations:
            return dict(changed_scenes=0, new_glyphs=0, scope=self.scope)
        rawfont = decompress(self.resource('FONT.CHR'))
        original = decompress(self.resource('FONT.CHR', True))
        occupied = set(self.occupied)
        occupied.update((g for g in range(0x400) if cell(rawfont, g, 16, 16) != cell(original, g, 16, 16)))
        text = ''.join((CONTROL.sub('', v) for v in translations.values())) + language['required_characters']
        chars = sorted(set(text) - set(CHAR_TO_GLYPH) - {'\n'})
        donors = [g for g in range(1, 0x3f3) if g not in occupied]
        if len(chars) > len(donors):
            raise ValueError(f'locale needs {len(chars)} glyphs; only {len(donors)} safe cells available')
        newmap = dict(zip(chars, donors))
        charmap = {**CHAR_TO_GLYPH, **newmap}
        proof = []
        fontfile = font_path(font) if chars else None
        for name, width, height, base in [('FONT.CHR', 16, 16, 0), ('FONT1.CHR', 8, 16, 0), ('FONT2.CHR', 8, 16, 0x200)]:
            tim = bytearray(decompress(self.resource(name)))
            before = bytes(tim)
            for char, glyph in newmap.items():
                if name != 'FONT.CHR' and (not base <= glyph < base + 0x200):
                    continue
                mask = raster(char, width, height, fontfile)
                paint(tim, glyph, width, height, base, mask)
                if name != 'FONT.CHR':
                    proof.append((char, mask))
            if bytes(tim) != before:
                encoded = compress(bytes(tim))
                if decompress(encoded) != bytes(tim):
                    raise ValueError('locale font compression roundtrip failed')
                # The stock loader already accepts the Japanese font's packed
                # size; keep both decoded and compressed data within proven bounds.
                capacity = max(len(self.resource(name)), len(self.resource(name, True)))
                if len(encoded) > capacity:
                    raise ValueError(f'{name}: compressed font needs {len(encoded)} bytes; proven input allocation is {capacity}')
                self.replacements[name] = encoded.ljust(capacity, b'\x00')
        reports = []
        changed = {self.records[k]['module'] for k in translations}
        for module in self.layout['modules']:
            name = module['name']
            if name not in changed:
                continue
            items = []
            for row in module['records']:
                key = 'dialogue/' + row['id']
                r = self.records[key]
                s = r['source']
                prefix = s[:1] if row['voice'] else []
                if key in translations:
                    body = encode_text(translations[key], charmap, 36, row['terminated'])
                    end = s[-1:] if row['terminated'] else []
                    words = prefix + body + end
                else:
                    words = r['english']
                items.append((row, words[:1] if row['voice'] else [], words[1 if row['voice'] else 0:-1 if row['terminated'] else len(words)], words[-1:] if row['terminated'] else []))
            area = self.areas[name]

            def edits_for(bodies):
                edits = [Edit(row['source_start'], row['source_end'], pack(prefix + body + ending), row['id'], {int(k): v for k, v in row['anchors'].items()}) for (row, prefix, _, ending), body in zip(items, bodies)]
                growth = sum((len(e.replacement) - (e.end - e.start) for e in edits))
                if growth % 4:
                    index = max((i for i, (row, _, _, _) in enumerate(items) if row['terminated']))
                    e = edits[index]
                    edits[index] = Edit(e.start, e.end, e.replacement[:-2] + pack([charmap[' ']]) + e.replacement[-2:], e.label, e.anchors)
                return edits
            bodies = [x[2] for x in items]
            edits = edits_for(bodies)
            projected = OffsetMap(len(area), edits).output_size
            dictionary = None
            if projected > AREA_LOCAL_CAPACITY:
                dictionary = build_token_dictionary(bodies, charmap[' '])
                edits = edits_for(dictionary.encoded_bodies)
            output, report = transform_area(area, edits)
            if dictionary:
                output, extra = append_area_dictionary(output, dictionary.blob)
            if len(output) > AREA_LOCAL_CAPACITY:
                raise ValueError(f'{name}: scene exceeds runtime allocation')
            positions = OffsetMap(len(area), edits)
            tokens = read_area_dictionary(output)[0] if dictionary else []
            for edit, item in zip(edits, items):
                begin = positions.map_offset(edit.start, 'readback')
                words = expand_token_words(unpack(output[begin:begin + len(edit.replacement)]), tokens)
                expected = item[1] + item[2] + item[3]
                if words != expected and words != expected[:-1] + [charmap[' ']] + expected[-1:]:
                    raise ValueError(f'{edit.label}: script readback failed')
            for old in range(0, len(area) - 3, 4):
                value = struct.unpack_from('<I', area, old)[0]
                target = value - 0x8015013a
                if 0x80150000 <= value < 0x80180000 and 0 <= target < len(area):
                    got = struct.unpack_from('<I', output, positions.map_offset(old, 'pointer'))[0]
                    if got != 0x8015013a + positions.map_offset(target, 'target'):
                        raise ValueError('pointer readback failed')
            self.replacements[name] = output
            reports.append(dict(name=name, size=len(output), tokenized=bool(dictionary), pointers=report['runtime_pointer_count']))
        proof_sheet(proof, proof_dir / 'locale_glyphs.png')
        return dict(changed_scenes=len(changed), new_glyphs=len(newmap), glyph_map={c: f'{g:04X}' for c, g in newmap.items()}, scenes=reports, scope=self.scope)

    def install(self, path):
        if not self.replacements:
            return
        lba = path.stat().st_size // 0x930
        eve, basyo, changes = repack(self.basyo, self.eve, self.replacements, lba, self.eve_lba)
        resources = build_inventory(basyo, eve, lba)['resources']
        for r in resources:
            actual = eve[r['start_offset']:r['start_offset'] + r['declared_size']]
            expected = self.replacements.get(r['name'], self.resource(r['name']))
            if actual != expected:
                raise ValueError(f"{r['name']}: resource repack mismatch")
        if len(basyo) != len(self.basyo):
            raise ValueError('BASYO runtime allocation changed')
        self.disc.append(EVE, eve)
        self.disc.replace(BASYO, basyo)
