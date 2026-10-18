"""Build the offline India outline from Natural Earth's 10m India-POV country archive.

Usage: python scripts/prepare_map.py /path/to/ne_10m_admin_0_countries_ind.zip
No extra GIS package or network access is required at application runtime.
"""
import argparse
import hashlib
import json
from pathlib import Path
import struct
import zipfile

SOURCE = 'https://naciscdn.org/naturalearth/10m/cultural/ne_10m_admin_0_countries_ind.zip'
ROOT = Path(__file__).resolve().parents[1]


def simplify(points, tolerance=.012):
    # Iterative Douglas–Peucker, retaining coastline detail at dashboard scale.
    if len(points) < 4:
        return points
    keep = {0, len(points)-1}
    stack = [(0, len(points)-1)]
    while stack:
        first, last = stack.pop()
        ax, ay = points[first]; bx, by = points[last]
        dx, dy = bx-ax, by-ay
        length = dx*dx+dy*dy
        best, position = 0, None
        for index in range(first+1,last):
            px, py = points[index]
            t = max(0,min(1,((px-ax)*dx+(py-ay)*dy)/length)) if length else 0
            distance = (px-ax-t*dx)**2+(py-ay-t*dy)**2
            if distance > best:
                best,position = distance,index
        if position is not None and best > tolerance*tolerance:
            keep.add(position);stack.extend(((first,position),(position,last)))
    result = [points[i] for i in sorted(keep)]
    return result if len(result) >= 4 else points


def build(archive, output=ROOT/'app/maps/india.json'):
    archive=Path(archive)
    with zipfile.ZipFile(archive) as z:
        dbf=z.read(next(n for n in z.namelist() if n.endswith('.dbf')))
        shp=z.read(next(n for n in z.namelist() if n.endswith('.shp')))
    count=struct.unpack_from('<I',dbf,4)[0]
    header,length=struct.unpack_from('<HH',dbf,8)
    fields=[];offset=1
    for start in range(32,header-1,32):
        if dbf[start] == 13:break
        name=dbf[start:start+11].split(b'\0')[0].decode('ascii')
        width=dbf[start+16];fields.append((name,offset,width));offset+=width
    target=None
    for index in range(count):
        row=dbf[header+index*length:header+(index+1)*length]
        values={name:row[o:o+w].decode('latin1').strip(' \x00') for name,o,w in fields}
        if values.get('ADMIN')=='India':target=index;break
    if target is None:raise ValueError('No India country record in archive')
    offset=100
    for index in range(target+1):
        _,words=struct.unpack_from('>II',shp,offset)
        shape=shp[offset+8:offset+8+words*2];offset+=8+words*2
    if struct.unpack_from('<I',shape)[0] not in (5,15,25):raise ValueError('Expected polygon geometry')
    parts,points=struct.unpack_from('<II',shape,36)
    starts=list(struct.unpack_from('<'+'I'*parts,shape,44))+[points]
    coordinates=[struct.unpack_from('<dd',shape,44+4*parts+i*16) for i in range(points)]
    rings=[[[round(x,4),round(y,4)] for x,y in simplify(coordinates[a:b])] for a,b in zip(starts,starts[1:]) if b-a>=4]
    result={'name':'India','rings':rings,'source':'Natural Earth 1:10m countries, India POV, v5.1.1',
            'source_url':SOURCE,'license':'public domain','source_archive_sha256':hashlib.sha256(archive.read_bytes()).hexdigest(),
            'simplification_degrees':.012,'bounds':list(struct.unpack_from('<dddd',shape,4))}
    Path(output).write_text(json.dumps(result,separators=(',',':'))+'\n')
    return {'rings':len(rings),'points':sum(map(len,rings)),'path':str(output)}


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('archive',type=Path)
    print(json.dumps(build(parser.parse_args().archive)))
