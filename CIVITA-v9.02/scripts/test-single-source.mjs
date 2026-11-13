import { readFileSync } from 'node:fs';
import vm from 'node:vm';
import assert from 'node:assert/strict';

const html = readFileSync(new URL('../CIVITA-ExpSubmit-v9.02.html', import.meta.url), 'utf8');
for (const match of html.matchAll(/<script(?:\s[^>]*)?>([\s\S]*?)<\/script>/g)) new vm.Script(match[1]);
for (const id of ['fileInput', 'digitizeInput', 'mergeInput', 'fdpReloadInput']) {
  const input = html.match(new RegExp('<input[^>]*id="'+id+'"[^>]*>'))[0];
  assert.ok(!input.includes('multiple'));
}
assert.ok(html.indexOf('id="fdpStep0"') < html.indexOf('id="fdpStep1"'));
function section(start,end){return html.slice(html.indexOf(start),html.indexOf(end));}
const notices=[];
const fig={figure_id:'FIG1',source_id:'SRC1',physical_page:2,curve_data:'saved points',calibration_json:'saved calibration'};
const elements={fdpReloadStatus:{textContent:''},fdpReloadPdf:{disabled:false}};
let persisted=0,reopened=0,cached=0;
const ctx=vm.createContext({
  alert:m=>notices.push(m),confirm:()=>true,
  db:{literature_sources:[{source_id:'SRC1'}],figures:[fig]},
  fdpState:{figureId:'FIG1',openGen:1},busy:false,
  pdfStore:new Map(),figureImageStore:new Map([['FIG1','old image']]),
  document:{getElementById:id=>elements[id]},
  fdpResolveFig:()=>fig,fdpFigurePhysPage:()=>2,
  fileToBase64:async()=> 'pdf-bytes',decodePdfBase64:x=>x,
  pdfGetDocument:async()=>({numPages:3,destroy:async()=>{}}),
  fdpPersist:()=>persisted++,saveState:()=>true,
  pdfIdbPut:async()=>cached++,openDigitizer:async()=>reopened++,logMsg:()=>{}
});
vm.runInContext(section('function singleSourceError(', 'async function loadPdfForDigitize('),ctx);
vm.runInContext(section('function fdpUpdateReloadStatus(', 'async function openDigitizer('),ctx);
assert.equal(ctx.singleSourceError({literature_sources:[]},{literature_sources:[{source_id:'A'}]}),'');
assert.equal(ctx.singleSourceError({literature_sources:[{source_id:'A'}]},{literature_sources:[{source_id:'A'}]}),'');
assert.ok(ctx.singleSourceError({literature_sources:[{source_id:'A'}]},{literature_sources:[{source_id:'B'}]}));
assert.ok(ctx.singleSourceError({literature_sources:[]},{literature_sources:[{source_id:'A'},{source_id:'B'}]}));
assert.ok(ctx.singleSourceError({literature_sources:[{source_id:'A'},{source_id:'B'}]}));
assert.equal(ctx.canLoadNewSource([{name:'paper.pdf'}]),false);
const mintGuard=section('function nextId(prefix) {','  // Enforcement boundary');
vm.runInContext(mintGuard+'\n}',ctx);
assert.throws(()=>ctx.nextId('SRC'),/Only one source/);
ctx.db.literature_sources=[];
assert.equal(ctx.canLoadNewSource([{name:'paper.pdf'}]),true);
assert.equal(ctx.canLoadNewSource([{},{ }]),false);
ctx.db.literature_sources=[{source_id:'SRC1'}];

await ctx.fdpReloadPdf([{name:'paper.pdf',type:'application/pdf'}]);
assert.equal(ctx.pdfStore.get('SRC1').base64,'pdf-bytes');
assert.equal(ctx.db.literature_sources.length,1);
assert.equal(fig.curve_data,'saved points');
assert.equal(fig.calibration_json,'saved calibration');
assert.equal(persisted,1);assert.equal(cached,1);assert.equal(reopened,1);assert.equal(ctx.busy,false);
ctx.fileToBase64=async()=> 'different-pdf';
ctx.confirm=()=>false;
await ctx.fdpReloadPdf([{name:'replacement.pdf'}]);
assert.equal(ctx.pdfStore.get('SRC1').base64,'pdf-bytes');
ctx.confirm=()=>true;
await ctx.fdpReloadPdf([{name:'replacement.pdf'}]);
assert.equal(fig.calibration_json,'');assert.equal(fig.curve_data,'saved points');
const before=ctx.pdfStore.get('SRC1');
ctx.pdfGetDocument=async()=>{throw Error('invalid PDF');};
await ctx.fdpReloadPdf([{name:'broken.pdf'}]);
assert.equal(ctx.pdfStore.get('SRC1'),before);assert.equal(ctx.busy,false);
ctx.pdfGetDocument=async()=>({numPages:1,destroy:async()=>{}});
await ctx.fdpReloadPdf([{name:'short.pdf'}]);
assert.equal(ctx.pdfStore.get('SRC1'),before);
ctx.pdfGetDocument=async()=>({numPages:3,destroy:async()=>{}});
ctx.fileToBase64=async()=>{ctx.fdpState.openGen++;return 'stale';};
await ctx.fdpReloadPdf([{name:'stale.pdf'}]);
assert.equal(ctx.pdfStore.get('SRC1'),before);assert.equal(ctx.busy,false);
console.log('PASS: syntax, single-file pickers, one-source guards, same-source import, reload preservation, replacement/cancel, invalid PDF, page bounds, and stale-figure protection.');
