"""Read source files without changing them; stdlib-only XLSX inspection."""
import hashlib
import json
from pathlib import Path
import xml.etree.ElementTree as ET
from zipfile import ZipFile

NS = {'s': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}

def read_xlsx(path):
    with ZipFile(path) as z:
        strings = []
        if 'xl/sharedStrings.xml' in z.namelist():
            strings = [''.join(e.itertext()) for e in ET.fromstring(z.read('xl/sharedStrings.xml'))]
        rels = {e.attrib['Id']: e.attrib['Target'] for e in ET.fromstring(z.read('xl/_rels/workbook.xml.rels'))}
        result = {}
        for sheet in ET.fromstring(z.read('xl/workbook.xml')).find('s:sheets', NS):
            rid = sheet.attrib['{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id']
            target = rels[rid]
            target = target.lstrip('/') if target.startswith('/') else 'xl/' + target
            cells = {}
            for cell in ET.fromstring(z.read(target)).findall('.//s:c', NS):
                value = cell.find('s:v', NS)
                text = value.text if value is not None else ''
                if cell.get('t') == 's':
                    text = strings[int(text)]
                elif cell.get('t') == 'inlineStr':
                    text = ''.join(e.text or '' for e in cell.findall('.//s:t', NS))
                formula = cell.find('s:f', NS)
                if text or formula is not None:
                    cells[cell.get('r')] = {'value': text, 'formula': formula.text if formula is not None else None}
            result[sheet.attrib['name']] = cells
        return result

if __name__ == '__main__':
    import sys
    path = Path(sys.argv[1])
    content = read_xlsx(path)
    out = Path(sys.argv[2])
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(content, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'sha256': hashlib.sha256(path.read_bytes()).hexdigest(), 'sheets': {k: len(v) for k,v in content.items()}}, ensure_ascii=False))
