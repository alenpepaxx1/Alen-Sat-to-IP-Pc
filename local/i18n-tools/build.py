# Copyright © 2026 Alen Pepa.
"""Build deterministic, dependency-free language catalogs."""
import json
from pathlib import Path
root = Path(__file__).resolve().parents[2]
entries = {}
for line in Path(__file__).with_name('catalog.tsv').read_text().splitlines():
    if not line.strip(): continue
    parts = line.split('\t')
    if len(parts) != 3 or any(not p for p in parts): raise ValueError('Invalid catalog row: ' + line)
    key, sq, de = parts
    if key in entries: raise ValueError('Duplicate translation: ' + key)
    entries[key] = {'en': key, 'sq': sq, 'de': de}
(root/'dist/translations.js').write_text('/* Copyright © 2026 Alen Pepa. */\n/* Generated from local/i18n-tools/catalog.tsv. */\n'+'globalThis.AlenTranslations = '+json.dumps(entries, ensure_ascii=False, indent=1)+';\n')
print(f'Built {len(entries)} complete English/Albanian/German entries.')

for language in ['en','sq','de']:
    folder=root/'companion/ios/AlenCalls'/f'{language}.lproj'
    folder.mkdir(parents=True,exist_ok=True)
    def quoted(value): return json.dumps(value,ensure_ascii=False)
    (folder/'Localizable.strings').write_text('/* Copyright © 2026 Alen Pepa. */\n'+'\n'.join(quoted(key)+' = '+quoted(value[language])+';' for key,value in entries.items())+'\n')
    (folder/'InfoPlist.strings').write_text('/* Copyright © 2026 Alen Pepa. */\n"NSLocalNetworkUsageDescription" = '+quoted(entries['Sends incoming call state to your Alen STB bridge on your local network.'][language])+';\n')
