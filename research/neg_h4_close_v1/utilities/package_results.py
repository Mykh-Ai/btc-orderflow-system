"""Lossless publication packaging, after execution and reporting are complete."""
from pathlib import Path
import gzip, hashlib, json
HERE=Path(__file__).resolve().parents[1]
manifest=[]
for folder in ['results','baseline_parity']:
    for path in sorted((HERE/folder).rglob('*')):
        if not path.is_file():continue
        data=path.read_bytes();original=str(path.relative_to(HERE))
        sha=hashlib.sha256(data).hexdigest()
        if path.suffix=='.csv' and len(data)>500000:
            target=path.with_suffix('.csv.gz');compressed=gzip.compress(data,compresslevel=6,mtime=0)
            assert gzip.decompress(compressed)==data
            target.write_bytes(compressed);path.unlink();path=target
        manifest.append(dict(original_path=original,path=str(path.relative_to(HERE)),
            original_sha256=sha,original_bytes=len(data),stored_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
            stored_bytes=path.stat().st_size))
(HERE/'artifact_manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
print('Verified and packaged',len(manifest),'artifacts',sum(x['stored_bytes'] for x in manifest),'bytes')
