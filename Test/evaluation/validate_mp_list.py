"""Checks the German MP list served by the backend against the official Bundestag master data.

Downloads MdB-Stammdaten from bundestag.de, rebuilds the list of current members of one
electoral period with full detail, and compares it with GET /api/german-members.

    python validate_mp_list.py                  # compare with the backend on port 8000
    python validate_mp_list.py --no-backend     # only analyse the official data
    python validate_mp_list.py --xml MDB_STAMMDATEN.XML --period 21

Writes mp_list_official.csv next to this script and prints a report.
"""
import argparse
import collections
import csv
import io
import json
import unicodedata
import urllib.request
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

BUNDESTAG_URL = 'https://www.bundestag.de/resource/blob/472878/MdB-Stammdaten.zip'
BACKEND_URL = 'http://127.0.0.1:8000/api/german-members?limit=1000'
HERE = Path(__file__).resolve().parent


def text(node, tag):
    child = node.find(tag) if node is not None else None
    return (child.text or '').strip() if child is not None else ''


def load_root(xml_path):
    if xml_path:
        return ET.parse(xml_path).getroot()
    request = urllib.request.Request(BUNDESTAG_URL, headers={'User-Agent': 'MetaAvatar/2.2'})
    with urllib.request.urlopen(request, timeout=60) as response:
        data = response.read()
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        name = next(n for n in archive.namelist() if n.lower().endswith('.xml') and not n.startswith('__MACOSX'))
        return ET.fromstring(archive.read(name))


def current_name(mdb):
    """The name entry without an end date, as the backend picks it."""
    names = mdb.findall('NAMEN/NAME')
    open_names = [n for n in names if not text(n, 'HISTORIE_BIS')]
    return (open_names or names)[-1], len(names)


def backend_style(name):
    """First name, nobility particle, prefix and surname, as the backend joins them."""
    parts = (text(name, 'VORNAME'), text(name, 'ADEL'), text(name, 'PRAEFIX'), text(name, 'NACHNAME'))
    return ' '.join(' '.join(p for p in parts if p).split())


def plausible(name):
    """Same rule as is_plausible_person_name in backend_python/main.py."""
    allowed = {' ', '-', "'", '’', '.'}
    return any(c.isalpha() for c in name) and all(
        c.isalpha() or unicodedata.category(c).startswith('M') or c in allowed for c in name)


def read_members(root, period):
    current, left = [], []
    for mdb in root.iter('MDB'):
        wps = [wp for wp in mdb.findall('WAHLPERIODEN/WAHLPERIODE') if text(wp, 'WP') == period]
        if not wps:
            continue
        wp = wps[-1]
        name, name_count = current_name(mdb)
        groups = sorted({text(i, 'INS_LANG') for i in wp.findall('INSTITUTIONEN/INSTITUTION')
                         if text(i, 'INSART_LANG') == 'Fraktion/Gruppe' and not text(i, 'MDBINS_BIS')})
        row = {
            'id': text(mdb, 'ID'),
            'backend_name': backend_style(name),
            'vorname': text(name, 'VORNAME'), 'adel': text(name, 'ADEL'), 'praefix': text(name, 'PRAEFIX'),
            'nachname': text(name, 'NACHNAME'), 'ortszusatz': text(name, 'ORTSZUSATZ'),
            'akad_titel': text(name, 'AKAD_TITEL'), 'name_changes': name_count - 1,
            'partei': text(mdb.find('BIOGRAFISCHE_ANGABEN'), 'PARTEI_KURZ'),
            'fraktion': '; '.join(groups),
            'mandat_von': text(wp, 'MDBWP_VON'), 'mandat_bis': text(wp, 'MDBWP_BIS'),
            'mandatsart': text(wp, 'MANDATSART'), 'wkr_land': text(wp, 'WKR_LAND'),
        }
        (left if row['mandat_bis'] else current).append(row)
    return current, left


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--xml', help='use a local MDB_STAMMDATEN.XML instead of downloading it')
    parser.add_argument('--period', default='21', help='electoral period (Wahlperiode)')
    parser.add_argument('--backend', default=BACKEND_URL, help='backend endpoint to compare with')
    parser.add_argument('--no-backend', action='store_true', help='skip the comparison with the backend')
    args = parser.parse_args()

    root = load_root(args.xml)
    current, left = read_members(root, args.period)
    version = root.findtext('VERSION', '')

    out = HERE / 'mp_list_official.csv'
    with open(out, 'w', newline='', encoding='utf-8-sig') as f:
        writer = csv.DictWriter(f, fieldnames=list(current[0]))
        writer.writeheader()
        writer.writerows(sorted(current + left, key=lambda r: r['backend_name'].casefold()))

    print(f'Official data (VERSION {version}): {len(current) + len(left)} people with a mandate in period {args.period}')
    print(f'  still in office: {len(current)}   left during the period: {len(left)}')

    expected = [r['backend_name'] for r in current if plausible(r['backend_name'])]
    duplicates = [n for n, c in collections.Counter(expected).items() if c > 1]
    rejected = [r['backend_name'] for r in current if not plausible(r['backend_name'])]
    print(f'  same displayed name for different MPs: {len(duplicates)} {duplicates}')
    print(f'  rejected by the name filter: {len(rejected)} {rejected}')

    if not args.no_backend:
        backend = json.load(urllib.request.urlopen(args.backend, timeout=120))
        served = backend['names']
        missing = sorted(set(expected) - set(served))
        extra = sorted(set(served) - set(expected))
        print(f"Backend: period {backend['period']}, total {backend['total']}, returned {len(served)}")
        print(f'  in official data but not served: {len(missing)} {missing[:10]}')
        print(f'  served but not in official data: {len(extra)} {extra[:10]}')
        print('  RESULT:', 'identical' if not missing and not extra and len(served) == len(set(expected)) else 'DIFFERENT')

    def examples(rows, n=5):
        return [r['backend_name'] for r in rows][:n]

    print('\nName structure of current MPs:')
    checks = [
        ('nobility particle (ADEL)', [r for r in current if r['adel']]),
        ('name prefix (PRAEFIX)', [r for r in current if r['praefix']]),
        ('place suffix (ORTSZUSATZ, dropped)', [r for r in current if r['ortszusatz']]),
        ('academic title (dropped)', [r for r in current if r['akad_titel']]),
        ('hyphenated name', [r for r in current if '-' in r['backend_name']]),
        ('non-ASCII letters', [r for r in current if not r['backend_name'].isascii()]),
        ('more than one first name', [r for r in current if ' ' in r['vorname']]),
        ('name changed during career', [r for r in current if r['name_changes']]),
    ]
    for label, rows in checks:
        print(f'  {label:36s} {len(rows):4d}  e.g. {examples(rows)}')

    print('\nCurrent MPs by parliamentary group:')
    for group, count in collections.Counter(r['fraktion'] or '(none)' for r in current).most_common():
        print(f'  {count:4d}  {group}')
    print('Mandate type:', dict(collections.Counter(r['mandatsart'] for r in current)))
    print('\nLeft during the period (excluded):')
    for r in left:
        print(f"  {r['backend_name']} ({r['partei']}) until {r['mandat_bis']}")
    print(f'\nWrote {out}')


if __name__ == '__main__':
    main()
