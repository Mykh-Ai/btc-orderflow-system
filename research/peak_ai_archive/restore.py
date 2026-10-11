"""Restore archived Peak AI data to the repository root. Standard library only."""
from pathlib import Path
import hashlib, io, json, zipfile
root = Path(__file__).resolve().parents[2]
manifest = json.loads(Path(__file__).with_name('manifest.json').read_text())
data = b''.join((root / p).read_bytes() for p in manifest['parts'])
assert hashlib.sha256(data).hexdigest() == manifest['archive_sha256'], 'Archive checksum mismatch'
with zipfile.ZipFile(io.BytesIO(data)) as archive:
    for item in manifest['files']:
        path = root / item['path']
        assert path.resolve().is_relative_to(root), 'Unsafe archive path'
        content = archive.read(item['path'])
        assert hashlib.sha256(content).hexdigest() == item['sha256'], item['path']
        if path.exists() and path.read_bytes() != content:
            raise RuntimeError(f'Refusing to overwrite modified file: {path}')
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
print(f"Restored and verified {len(manifest['files'])} files.")
