import struct
import unittest
from localization.area import Edit, OffsetMap, transform_area
from localization.tokens import build_token_dictionary, expand_token_words, append_area_dictionary, read_area_dictionary, AREA_LOCAL_CAPACITY
from localization.english import CHAR_TO_GLYPH
from localization.lzss import compress, decompress

class Royal2Tests(unittest.TestCase):

    def test_relocation_and_unsafe_interior_anchor(self):
        area = bytearray(32)
        struct.pack_into('<I', area, 0, 2148860218 + 16)
        edit = Edit(8, 12, b'abcdefgh', 'text')
        output, report = transform_area(bytes(area), [edit])
        self.assertEqual(struct.unpack_from('<I', output, 0)[0], 2148860218 + 20)
        self.assertEqual(report['relocated_pointer_count'], 1)
        struct.pack_into('<I', area, 0, 2148860218 + 10)
        with self.assertRaises(ValueError):
            transform_area(bytes(area), [edit])
        edit = Edit(8, 12, b'abcdefgh', 'text', {2: 2})
        output, _ = transform_area(bytes(area), [edit])
        self.assertEqual(struct.unpack_from('<I', output, 0)[0], 2148860218 + 10)

    def test_dictionary_roundtrip_and_runtime_guard(self):
        body = [1, 2, 3, 4, 5, 254, 37120] * 50
        result = build_token_dictionary([body] * 10, CHAR_TO_GLYPH[' '])
        area, _ = append_area_dictionary(b'\x00' * 16, result.blob)
        entries, _ = read_area_dictionary(area)
        for words in result.encoded_bodies:
            self.assertEqual(expand_token_words(words, entries), body)
        with self.assertRaises(ValueError):
            append_area_dictionary(b'\x00' * AREA_LOCAL_CAPACITY, result.blob)

    def test_font_compression_roundtrip(self):
        source = bytes(range(256)) * 20 + b'\x00' * 100
        self.assertEqual(decompress(compress(source)), source)
if __name__ == '__main__':
    unittest.main()
