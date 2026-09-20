// Optional Excel view renderer; uses the Desktop bundled @oai/artifact-tool.
import fs from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { FileBlob, SpreadsheetFile } from '@oai/artifact-tool';
const root=path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const local=path.join(root,'local');
const state=JSON.parse(await fs.readFile(path.join(local,'GTM_Design_Partners_Etat.json'),'utf8'));
const target=path.join(local,'Design_partners_FR_CH_BE.xlsx');
const wb=await SpreadsheetFile.importXlsx(await FileBlob.load(target));
const render=async (sheet,suffix)=>{
  const png=await wb.render({sheetName:sheet,autoCrop:'all',scale:1,format:'png'});
  await fs.writeFile(path.join(local,'evidence',`${sheet}-${suffix}.png`),new Uint8Array(await png.arrayBuffer()));
};
await render('Reprise','before');
const patches={
  Reprise:{
    B4:`Vue locale du ${new Date().toISOString().slice(0,10)} ; journal JSON de référence.`,
    B5:`${state.preferred_sender} — signature avec téléphone obligatoire.`,
    B8:'Ouvrir le dossier local, lire AGENTS.md puis le journal JSON. Excel est une vue dérivée.',
    B11:'Aucune nouvelle vague. Réponses automatiques bloquées jusqu’à validation de la bascule.',
    B13:'Surveillance locale non activée. Ancienne tâche non modifiée ; exécution actuelle à vérifier.'
  },
  Reponses:{
    B4:'Mode local : lecture contrôlée. Aucun traitement autonome planifié démontré.',
    B5:'Réponses automatiques désactivées. Bascule de l’ancienne tâche et couverture historique à résoudre.',
    B18:'Cadence locale proposée : une heure. Activation après test planifié et bascule contrôlée.',
    B20:'JSON local = référence ; Excel = vue. Sauvegardes locales hors Git ; ancienne tâche inchangée.'
  },
  Vague_1:{
    B21:`Événement Vision PnL vérifié le 19/09/2026 : 30 min, Google Meet. Lien : ${state.calendly.selected_event_url}`,
    B23:`${state.sent.length} envois historiques. 10 relus dans Gmail personnel ; 5 fils historiques inaccessibles. ${Object.values(state.local_runtime.events).filter(e=>e.classification==='automatic').length} accusés automatiques consignés.`
  }
};
for(const [sheet,cells] of Object.entries(patches)) for(const [cell,value] of Object.entries(cells)) wb.worksheets.getItem(sheet).getRange(cell).values=[[value]];
wb.recalculate();
console.log((await wb.inspect({kind:'table',range:'Top_20!A29:B32',include:'values,formulas',tableMaxRows:4,tableMaxCols:2,maxChars:1000})).ndjson);
await render('Reprise','after');
await render('Reponses','after');
await render('Vague_1','after');
await fs.writeFile(path.join(local,'evidence','workbook-patches.json'),JSON.stringify(patches,null,2));
const output=await SpreadsheetFile.exportXlsx(wb);
await output.save(target+'.pending.xlsx');
await fs.rename(target+'.pending.xlsx',target);
console.log('Local workbook refreshed; original source preserved.');
