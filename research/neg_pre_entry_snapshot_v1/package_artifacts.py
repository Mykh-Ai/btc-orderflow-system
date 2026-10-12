"""Lossless audit packaging and SHA-256 verification. No historical inputs mutated."""
import gzip,json,hashlib
from pathlib import Path
HERE=Path(__file__).resolve().parent
def sha(b):return hashlib.sha256(b).hexdigest()
def run():
    manifest=HERE/'archives.json'
    archives=json.loads(manifest.read_text()) if manifest.exists() else []
    for p in sorted((HERE/'evidence').glob('*.txt')):
        if p.stat().st_size<=500_000:continue
        original=p.read_bytes();packed=gzip.compress(original,mtime=0);target=p.with_suffix(p.suffix+'.gz')
        target.write_bytes(packed)
        archives.append(dict(original_path=str(p.relative_to(HERE)),stored_path=str(target.relative_to(HERE)),
            original_bytes=len(original),stored_bytes=len(packed),original_sha256=sha(original),stored_sha256=sha(packed)))
        p.unlink()
    for row in archives:
        data=(HERE/row['stored_path']).read_bytes()
        assert sha(data)==row['stored_sha256'] and sha(gzip.decompress(data))==row['original_sha256']
    manifest.write_text(json.dumps(archives,indent=2)+'\n')
    files=[dict(path=str(p.relative_to(HERE)),bytes=p.stat().st_size,sha256=sha(p.read_bytes()))
        for p in sorted(HERE.rglob('*')) if p.is_file() and '__pycache__' not in p.parts
        and p.name!='artifact_manifest.json' and not p.name.endswith('.pyc')]
    (HERE/'artifact_manifest.json').write_text(json.dumps(dict(files=files),indent=2)+'\n')
    print('VERIFIED',len(files),'files;',len(archives),'lossless audit archives')
if __name__=='__main__':run()
