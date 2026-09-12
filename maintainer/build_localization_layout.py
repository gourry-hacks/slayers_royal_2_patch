"""Capture checked ranges from the production scene compiler, without script bytes."""
from pathlib import Path
import argparse, os, sys, json, hashlib, re
REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
import patch
from localization.disc import Disc
from localization.inventory import build_inventory
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--workspace', type=Path, required=True, help='private Slayers workspace containing tools/ and royal2/')
parser.add_argument('--english-bin', type=Path, required=True, help='disc reconstructed by the current consumer patcher')
args = parser.parse_args()
manifest = patch.load_manifest()
english_path = args.english_bin.resolve()
patch.verify_file('English base', english_path, manifest['target']['bin'])
os.chdir(args.workspace.resolve())
sys.path.insert(0, str(Path('tools').resolve()))
disc = Disc(english_path)
english_eve = disc.file('/EVE_DATA.ST2')
english_basyo = disc.file('/BASYO.BIN')
english_resources = {r['name']: r for r in build_inventory(english_basyo, english_eve, disc.files['/EVE_DATA.ST2']['lba'])['resources']}
import build_sr2_text_patch as b
from repack_sr2_scene_area import OffsetMap
basyo = Path('royal2/extracted/BASYO.BIN').read_bytes()
eve = Path('royal2/extracted/EVE_DATA.ST2').read_bytes()
dump = json.loads(Path('royal2/script_dump/scene_scripts.json').read_text())
layout = json.loads(Path('royal2/reverse/scene_module_layout.json').read_text())
translations = b.load_scene_translations(Path('royal2/translations/scenes/full'))
original = b.transform_area
captured = []

def capture(area, edits):
    captured[:] = edits
    return original(area, edits)
b.transform_area = capture
out = []
for i, r in enumerate(b.scene_resources(basyo, eve)):
    start = r['start_offset']
    size = r['declared_size']
    area = eve[start:start + size]
    patched, report = b.patch_scene_resource(area, start, dump['modules'][i], layout['modules'][i], translations[i], 36, 3, False)
    er = english_resources[r['name']]
    assert patched == english_eve[er['start_offset']:er['start_offset'] + er['declared_size']], f'module {i}: compiler output does not match release'
    mapping = OffsetMap(len(area), captured)
    legacy = {x['id']: x for x in dump['modules'][i]['records']}
    records = []
    for e in sorted(captured, key=lambda e: e.start):
        records.append(dict(id=e.label, source_start=e.start, source_end=e.end, english_start=mapping.map_offset(e.start, 'start'), english_end=mapping.map_offset(e.end, 'end'), terminated=e.label in legacy, voice=legacy.get(e.label, {}).get('voice_control') is not None, anchors=e.anchors))
    out.append(dict(index=i, name=r['name'], source_sha256=hashlib.sha256(area).hexdigest(), english_sha256=report['sha256'], records=records))
    print(i, len(records), flush=True)
p = REPO / 'localization/layout.json'
document = dict(schema=1, english_bin_sha256=manifest['target']['bin']['sha256'], modules=out)
text = json.dumps(document, indent=2)
text = re.sub(r'(?m)^        (\{\n(?:.*\n)*?        \})(,?)$', lambda m: '        ' + json.dumps(json.loads(m[1]), separators=(',', ':')) + m[2], text)
assert json.loads(text) == json.loads(json.dumps(document))
p.write_text(text + '\n')
