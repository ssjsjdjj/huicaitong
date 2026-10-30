from pathlib import Path
from html.parser import HTMLParser
import hashlib
import json

root=Path(__file__).resolve().parent.parent/'dist'
manifest=json.loads((root/'assets.json').read_text(encoding='utf-8'))
for item in [manifest['bootstrap'],*manifest['cached_assets']]:
    path=(root/item['url'].lstrip('/')).resolve()
    assert path.is_relative_to(root.resolve())
    data=path.read_bytes()
    assert len(data)==item['bytes'] and hashlib.sha256(data).hexdigest()==item['sha256']
    assert not item['url'].startswith('/api/')
class CheckHTML(HTMLParser):
    def __init__(self):super().__init__();self.ids=set();self.scripts=[]
    def handle_starttag(self,tag,attrs):
        values=dict(attrs)
        if 'id' in values:
            assert values['id'] not in self.ids,'Duplicate id: '+values['id']
            self.ids.add(values['id'])
        if tag=='script' and 'src' in values:self.scripts.append(values['src'])
parser=CheckHTML();parser.feed((root/'index.html').read_text(encoding='utf-8'))
assert 'online-loading' not in parser.ids
for url in parser.scripts:
    assert '?v='+manifest['build_id'] in url
    assert (root/url.split('?')[0].lstrip('/')).is_file()
for name in ('online.js','runtime-worker.mjs','asset-cache.mjs','import-recovery.mjs','review-recovery.mjs','review-workbench.js'):
    assert '__HCT_BUILD__' not in (root/name).read_text(encoding='utf-8')
assert manifest['core']['bytes']<250000 and manifest['bootstrap']['bytes']<100000
print('Asset hashes, cache scope, unique DOM IDs, versioned scripts and split loading verified.')
