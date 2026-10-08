"""Pure, read-only comparison of installed metadata and official index entries.

Copyright 2026 Attempts. SPDX-License-Identifier: GPL-3.0-or-later
No fuzzy matching, plugin imports, file writes or network access in this module.
"""
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from html import escape
import json
import re
from urllib.parse import urlparse
import xml.etree.ElementTree as ET

MAX_INDEX_BYTES = 20 * 1024 * 1024
INDEX_BASE = 'https://plugins.qgis.org/plugins/plugins.xml'
STATUSES = {
    'DECLARED': 'Target release listed',
    'EXPERIMENTAL': 'Experimental only',
    'DEPRECATED': 'Deprecated listing',
    'NO_RELEASE': 'No target release listed',
    'UNKNOWN': 'Not identified / other repository',
    'BUNDLED': 'Bundled now — target not checked',
    'MISSING': 'Saved reference — not installed',
    'UNVERIFIED': 'Incomplete metadata',
}


def qgis_version(value):
    match = re.fullmatch(r'(\d{1,2})\.(\d{1,2})(?:\.(\d{1,3}))?(?:-ltr)?', value.strip())
    if not match:
        raise ValueError('Use a QGIS version such as 4.2 or 4.2.3.')
    return tuple(int(v or 0) for v in match.groups())


def target_version(value):
    version = qgis_version(value)
    if version[0] < 3:
        raise ValueError('Choose QGIS 3 or later.')
    # Indexes are served by major.minor; keep patch for range comparisons.
    return '.'.join(str(x) for x in version[:2]) + (f'.{version[2]}' if version[2] else '')


def index_url(version):
    v = qgis_version(version)
    return f'{INDEX_BASE}?qgis={v[0]}.{v[1]}'


def release_key(version):
    """Order common numeric versions; uncertainty is surfaced for other schemes."""
    match = re.fullmatch(r'v?(\d+(?:\.\d+)*)(?:(a|alpha|b|beta|rc|dev)[.-]?(\d*))?', version, re.I)
    if not match:
        return None
    nums = tuple(int(n) for n in match[1].split('.'))
    nums += (0,) * max(0, 6-len(nums))
    return nums, 1 if not match[2] else 0, int(match[3] or 0)


@dataclass
class Installed:
    folder: str
    name: str
    version: str = ''
    minimum: str = ''
    maximum: str = ''
    bundled: bool = False
    present: bool = True
    error: str = ''


@dataclass
class Release:
    package: str
    name: str
    version: str
    minimum: str
    maximum: str
    experimental: bool
    deprecated: bool

    def supports(self, target):
        try:
            return qgis_version(self.minimum) <= target <= qgis_version(self.maximum)
        except ValueError:
            return None


def parse_index(raw):
    if len(raw) > MAX_INDEX_BYTES:
        raise ValueError('Repository response exceeded the 20 MiB limit.')
    # Accept UTF-8 only. Reject DTD/entity declarations before the stdlib parser;
    # this also rejects UTF-16 bypasses rather than changing parser settings.
    text = raw.decode('utf-8-sig')
    if '\x00' in text or re.search(r'<!\s*(?:DOCTYPE|ENTITY)\b', text, re.I):
        raise ValueError('Unsupported XML declarations in repository response.')
    root = ET.fromstring(text)  # nosec B314: UTF-8, size limit, no DTD/entities
    if root.tag != 'plugins':
        raise ValueError('Response is not a QGIS plugin index.')
    result = {}
    for node in root.findall('pyqgis_plugin'):
        address = urlparse(node.findtext('download_url') or '')
        match = re.fullmatch(r'/plugins/([A-Za-z0-9_.-]+)/version/[^/]+/download/?', address.path)
        if address.scheme != 'https' or address.netloc != 'plugins.qgis.org' or not match:
            raise ValueError('Unexpected package URL in official repository response.')
        version = node.get('version') or ''
        if not version or not node.get('name'):
            raise ValueError('Missing name or version in repository entry.')
        entry = Release(match[1], node.get('name'), version,
                        node.findtext('qgis_minimum_version') or '',
                        node.findtext('qgis_maximum_version') or '',
                        (node.findtext('experimental') or '').lower() in ('true','1','yes'),
                        (node.findtext('deprecated') or '').lower() in ('true','1','yes'))
        result.setdefault(entry.package, []).append(entry)
    if not result:
        raise ValueError('Repository returned an empty index; no compatibility conclusion was made.')
    return result


@dataclass
class Row:
    package: str
    name: str
    installed: str
    status: str
    target_release: str = ''
    notes: list = field(default_factory=list)
    source: str = ''


def compare(installed, current_index, target_index, target):
    wanted = qgis_version(target)
    rows = []
    for local in installed:
        row = Row(local.folder, local.name or local.folder, local.version, 'UNKNOWN')
        rows.append(row)
        if local.error:
            row.status = 'UNVERIFIED'
            row.notes.append('Installed metadata could not be read. No compatibility conclusion.')
            continue
        if not local.present:
            row.status = 'MISSING'
            row.notes.append('An old profile setting refers to this name, but no installed package was found. Review manually.')
            continue
        if local.bundled:
            row.status = 'BUNDLED'
            row.notes.append('Part of this QGIS installation. Inclusion and behaviour in the target release were not checked.')
            continue
        current = current_index.get(local.folder, [])
        candidates = target_index.get(local.folder, [])
        if not current and not candidates:
            row.notes.append('Exact package name not found in these official indexes. Private, renamed or other-repository plugins need a separate check.')
            continue
        row.source = f'https://plugins.qgis.org/plugins/{local.folder}/'
        usable = [r for r in candidates if r.supports(wanted) is True]
        uncertain = [r for r in candidates if r.supports(wanted) is None]
        active = [r for r in usable if not r.deprecated]
        stable = [r for r in active if not r.experimental]
        choices = stable or active or usable
        if choices:
            keys = [release_key(r.version) for r in choices]
            if all(k is not None for k in keys):
                chosen = max(choices, key=lambda r: release_key(r.version))
            else:
                chosen = choices[0]
                row.notes.append('Version ordering is unclear; this is a listed candidate, not a latest-version recommendation.')
            row.target_release = chosen.version
            row.status = 'DECLARED' if stable else ('EXPERIMENTAL' if active else 'DEPRECATED')
            if row.status == 'EXPERIMENTAL':
                row.notes.append('Only an experimental release is listed for this target.')
            if row.status == 'DEPRECATED':
                row.notes.append('Only deprecated releases match this target. Review the author’s guidance.')
            before, after = release_key(local.version), release_key(chosen.version)
            if before is not None and after is not None and after < before:
                row.notes.append('The target candidate has an older version number. Do not downgrade automatically; consult the author for a successor.')
        elif uncertain:
            row.status = 'UNVERIFIED'
            row.notes.append('Target entries have missing or unreadable version bounds.')
        else:
            row.status = 'NO_RELEASE'
            row.notes.append('No release with explicit matching bounds was found in the target index. This does not prove the plugin cannot run.')
        if uncertain and choices:
            row.notes.append('Some additional index entries have incomplete bounds.')
        # Compare only the *same* installed release, not its newer replacement.
        same = [r for r in current+candidates if r.version == local.version]
        if same:
            indexed = {(r.minimum, r.maximum) for r in same}
            if not local.maximum:
                row.notes.append('Installed metadata has no maximum QGIS version. The index bounds were used; absence is not proof of compatibility.')
            elif local.minimum:
                try:
                    bounds = (qgis_version(local.minimum), qgis_version(local.maximum))
                    normalized = {(qgis_version(a),qgis_version(b)) for a,b in indexed}
                    if bounds not in normalized:
                        row.notes.append('Installed metadata and official index bounds differ. Review the source before migrating.')
                except ValueError:
                    row.notes.append('Installed/index bounds could not be compared reliably.')
        row.notes.append('Read the author’s page for migration notes or a replacement. Declared availability is not a runtime test.')
    return sorted(rows, key=lambda r: (r.name.casefold(),r.package))


def make_report(rows, current, target, fetched_at=None):
    return {'tool':'Upgrade Check','version':'0.1.0','current_qgis':current,
            'target_qgis':target,'fetched_at':fetched_at or datetime.now(timezone.utc).isoformat(),
            'scope':'Official repository declarations only. No plugin was installed, changed or executed by this check.',
            'sources':list(dict.fromkeys([index_url(current),index_url(target)])),
            'rows':[asdict(r) for r in rows]}


def plain_report(report):
    lines = ['Upgrade Check', f"QGIS {report['current_qgis']} → {report['target_qgis']}",
             f"Index fetched: {report['fetched_at']}", report['scope'], '']
    for row in report['rows']:
        lines += [f"{row['name']} ({row['package']})", f"  {STATUSES[row['status']]} | installed {row['installed'] or 'unknown'} | target {row['target_release'] or '—'}"]
        lines += ['  '+note for note in row['notes']]
        if row['source']: lines.append('  '+row['source'])
        lines.append('')
    lines += ['Sources:'] + report['sources']
    return '\n'.join(lines)


def html_report(report):
    e = lambda x: escape(str(x), quote=True)
    body = []
    for r in report['rows']:
        source = f'<a href="{e(r["source"])}">Author’s page</a>' if r['source'] else ''
        body.append('<tr>'+''.join('<td>'+v+'</td>' for v in [
            f'<strong>{e(r["name"])}</strong><br><small>{e(r["package"])}</small>',
            e(r['installed'] or 'Unknown'),e(STATUSES[r['status']]),e(r['target_release'] or '—'),
            '<ul>'+''.join('<li>'+e(n)+'</li>' for n in r['notes'])+'</ul>'+source])+'</tr>')
    return '''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width">
<title>Upgrade Check report</title><style>body{font:16px system-ui,sans-serif;color:#172b3a;background:#f6f8fb;margin:0;padding:32px}main{max-width:1200px;margin:auto}h1{margin-bottom:6px}p{line-height:1.5}.scroll{overflow:auto}table{border-collapse:collapse;background:white;width:100%}th,td{text-align:left;vertical-align:top;padding:14px;border-bottom:1px solid #d6e0e8}th{background:#e8eef4}td ul{padding-left:18px;margin-top:0}small{color:#516271}a{color:#155b9a}footer{margin-top:24px;font-size:14px}</style><main>'''+f'''
<h1>Upgrade Check</h1><p>QGIS {e(report['current_qgis'])} → <strong>{e(report['target_qgis'])}</strong><br>Index fetched: {e(report['fetched_at'])}</p>
<p>{e(report['scope'])}</p><div class="scroll"><table><thead><tr><th>Plugin</th><th>Installed</th><th>Status</th><th>Target release</th><th>Review notes</th></tr></thead><tbody>{''.join(body)}</tbody></table></div>
<footer>Repository sources: {' · '.join('<a href="'+e(u)+'">'+e(u)+'</a>' for u in report['sources'])}<br>Official repository metadata: QGIS plugin authors / plugins.qgis.org (CC BY-SA 3.0). Your report may contain private plugin names; review it before sharing.</footer></main></html>'''


def json_report(report):
    return json.dumps(report,ensure_ascii=False,indent=2)+'\n'
