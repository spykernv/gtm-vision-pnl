// Optional dated Excel view. The local journal remains authoritative.
import fs from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { execFileSync } from 'node:child_process';
import { FileBlob, SpreadsheetFile } from '@oai/artifact-tool';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const local = path.join(root, 'local');
const statePath = path.join(local, 'GTM_Design_Partners_Etat.json');
const originalState = await fs.readFile(statePath, 'utf8');
const view = JSON.parse(execFileSync(process.env.GTM_PYTHON || 'python',
  ['-B', '-X', 'utf8', path.join(root, 'scripts', 'status_view.py'), ...process.argv.slice(2)],
  { encoding: 'utf8' }));
const target = path.join(local, 'Design_partners_FR_CH_BE.xlsx');
const evidence = path.join(local, 'evidence', `workbook-${new Date().toISOString().replace(/[:.]/g, '-')}`);
await fs.mkdir(evidence);
await fs.copyFile(target, path.join(evidence, 'before.xlsx'));
const wb = await SpreadsheetFile.importXlsx(await FileBlob.load(target));
for (const [sheet, cells] of Object.entries(view.patches)) {
  for (const [cell, value] of Object.entries(cells)) wb.worksheets.getItem(sheet).getRange(cell).values = [[value]];
}
wb.recalculate();
for (const sheetName of Object.keys(view.patches)) {
  const png = await wb.render({ sheetName, autoCrop: 'all', scale: 1, format: 'png' });
  await fs.writeFile(path.join(evidence, `${sheetName}.png`), new Uint8Array(await png.arrayBuffer()));
}
await fs.writeFile(path.join(evidence, 'patches.json'), JSON.stringify(view.patches, null, 2));
await fs.writeFile(path.join(evidence, 'status.json'), JSON.stringify(view, null, 2));
const output = await SpreadsheetFile.exportXlsx(wb);
const pending = path.join(evidence, 'pending.xlsx');
await output.save(pending);
if (await fs.readFile(statePath, 'utf8') !== originalState) throw new Error('Journal changed during rendering; workbook was not replaced.');
await fs.rename(pending, target);
console.log(JSON.stringify({ workbook: target, evidence, revision: view.revision }));
