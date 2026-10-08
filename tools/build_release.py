"""Build deterministic release archives from explicit product-file allowlists."""
import argparse
import configparser
import hashlib
import json
from pathlib import Path
import zipfile

ROOT = Path(__file__).resolve().parents[1]
PLUGIN_FILES = [
    '__init__.py', 'core.py', 'plugin.py', 'metadata.txt', 'icon.svg',
    'README.md', 'LICENSE',
]
SOURCE_FILES = [
    '.gitignore', '.github/workflows/check.yml', 'README.md', 'LICENSE',
    'CHANGELOG.md', 'tools/build_release.py', 'tests/test_core.py',
    'docs/demo-profile.jpg', 'docs/demo-report.html', 'docs/demo-report.json',
    'docs/validation.md',
] + ['upgrade_check/' + name for name in PLUGIN_FILES]


def write_archive(destination, entries):
    with zipfile.ZipFile(destination, 'w', zipfile.ZIP_DEFLATED) as archive:
        for relative, source in sorted(entries):
            payload = source.read_bytes()
            if source.suffix != '.jpg':
                lower = payload.lower()
                for private in (b'/' + b'users' + b'/',
                                b'/' + b'private' + b'/' + b'tmp' + b'/'):
                    if private in lower:
                        raise ValueError('Private path/identifier in ' + relative)
            entry = zipfile.ZipInfo(relative, (2026, 10, 9, 0, 0, 0))
            entry.compress_type = zipfile.ZIP_DEFLATED
            entry.create_system = 3
            entry.external_attr = 0o100644 << 16
            archive.writestr(entry, payload)
    with zipfile.ZipFile(destination) as archive:
        if archive.testzip() is not None:
            raise ValueError('Archive integrity check failed')


def build(output):
    metadata = configparser.ConfigParser(interpolation=None)
    metadata.read(ROOT / 'upgrade_check/metadata.txt', encoding='utf-8')
    version = metadata['general']['version']
    output.mkdir(parents=True, exist_ok=True)
    package = output / ('upgrade-check-' + version + '.zip')
    source = output / ('upgrade-check-' + version + '-source.zip')
    write_archive(package, [('upgrade_check/' + name, ROOT / 'upgrade_check' / name)
                            for name in PLUGIN_FILES])
    write_archive(source, [('upgrade-check/' + name, ROOT / name)
                           for name in SOURCE_FILES])
    artifacts = {}
    for path in (package, source):
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        artifacts[path.name] = {'sha256': digest, 'bytes': path.stat().st_size}
        (output / (path.name + '.sha256')).write_text(
            digest + '  ' + path.name + '\n', encoding='utf-8')
    manifest = {
        'version': version,
        'scope': 'Experimental GitHub release; official QGIS catalogue pending',
        'artifacts': artifacts,
        'plugin_files': {name: hashlib.sha256((ROOT / 'upgrade_check' / name).read_bytes()).hexdigest()
                         for name in PLUGIN_FILES},
        'source_files': SOURCE_FILES,
    }
    (output / 'package-manifest.json').write_text(
        json.dumps(manifest, indent=2) + '\n', encoding='utf-8')
    return manifest


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT / 'dist')
    print(json.dumps(build(parser.parse_args().output), indent=2))
