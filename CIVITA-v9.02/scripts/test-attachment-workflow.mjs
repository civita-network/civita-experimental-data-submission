import { readFileSync } from 'node:fs';
import vm from 'node:vm';
import assert from 'node:assert/strict';
import { Blob, Buffer, File } from 'node:buffer';
import { TextEncoder } from 'node:util';

const html = readFileSync(new URL('../CIVITA-ExpSubmit-v9.02.html', import.meta.url), 'utf8');
for (const match of html.matchAll(/<script(?:\s[^>]*)?>([\s\S]*?)<\/script>/g)) new vm.Script(match[1]);
function section(start, end) { return html.slice(html.indexOf(start), html.indexOf(end)); }
const context = vm.createContext({ Blob, File, TextEncoder, Uint8Array, DataView, console,
  btoa: value => Buffer.from(value, 'latin1').toString('base64'), atob: value => Buffer.from(value, 'base64').toString('latin1') });
vm.runInContext(section('const TABLE_SCHEMAS =', '// ======== FK TARGETS'), context);
vm.runInContext(section('var ATTACHMENT_FIELDS =', '// Build the ordered column list:'), context);
vm.runInContext(section('function dataTestRepeatCount(', 'function buildTestRepeatSelect('), context);
vm.runInContext(section('function sanitizeCSV(', 'function safeStr('), context);
vm.runInContext(section('// ======== ATTACHMENT IMPORT AND PACKAGE EXPORT', '// ======== END ATTACHMENT IMPORT AND PACKAGE EXPORT'), context);
vm.runInContext(section('const VOCABS =', 'const TABLE_SCHEMAS ='), context);
vm.runInContext(section('var DATA_SHARED_FIELDS =', '// File controls follow'), context);
vm.runInContext("var db = { literature_sources: [{ source_id: 'SRC1' }], tests: [{ test_id: 'TST1', source_id: 'SRC1', number_of_repeats: '2' }], data: [] };", context);
assert.equal(context.dataFieldApplies({data_type:'curve'}, 'units'), false);
assert.equal(context.DATA_TYPE_FIELDS.scalar.at(-1), 'units');
assert.ok(vm.runInContext("VOCABS.loading_control_variable_list.includes('CTOD')", context));
const parse = context.attachmentParse;
const plain = value => JSON.parse(JSON.stringify(value));
assert.deepEqual(plain(parse('\uFEFFx,y,note\r\n-1,2,"two, words"\r\n3,4,"line\nwith ""quotes"""\r\n', 'curve.csv')), {
  headers: ['x','y','note'], rows: [['-1','2','two, words'],['3','4','line\nwith "quotes"']]
});
assert.deepEqual(plain(parse('x\ty\n1\t2', 'points.tsv').rows), [['1','2']]);
assert.deepEqual(plain(parse('[{"x":1,"y":2},{"x":3,"y":4}]', 'points.json').rows), [['1','2'],['3','4']]);
assert.deepEqual(plain(parse('{"rows":[{"x":1,"y":2}]}', 'points.json').rows), [['1','2']]);
for (const [text, name] of [['x,x\n1,2','bad.csv'], ['x,y\n1','bad.csv'], ['x,y\n"1,2','bad.csv'], ['x,y','empty.csv'], ['[{"x":{"nested":1}}]','bad.json']]) assert.throws(() => parse(text, name));
const curve = parse('time,load\n0,-2.5\n1,3e2', 'curve.csv');
assert.deepEqual(plain(context.attachmentCurve(curve, 0, 1)), [[0,-2.5],[1,300]]);
assert.throws(() => context.attachmentCurve(curve,0,0));
assert.throws(() => context.attachmentCurve(parse('x,y\n1,=2+3','bad.csv'),0,1));
assert.throws(() => context.attachmentNumeric(''));
const template = {source_id:'SRC1',test_id:'TST1',test_repeat_id:'TRP0002',data_type:'scalar'};
for (const marker of ['N/A', '-', ' n/a ']) {
  const withUnits = parse(`Strain,Stress\n${marker},MPa\n0,0.24\n0.00001,0.62`, 'curve.csv');
  assert.deepEqual(plain(context.attachmentCurveUnits(withUnits,0,1)), ['-','MPa']);
  assert.deepEqual(plain(context.attachmentCurve(withUnits,0,1)), [[0,0.24],[0.00001,0.62]]);
  assert.equal(context.attachmentMappedRows(parse(`units\n${marker}`, 'values.csv'), ['units'], template)[0].units, '-');
}
assert.throws(() => context.attachmentCurve(parse('x,y\n-,MPa', 'empty.csv'),0,1), /at least one numeric/);
assert.throws(() => context.attachmentCurve(parse('x,y\n-,MPa\n0,N/A', 'bad.csv'),0,1), /Row 3/);
const mapped = context.attachmentMappedRows(parse('mean,units\n12,MPa\n13,MPa','values.csv'), ['quantity_reported_mean',''], template);
assert.equal(mapped.length,2); assert.equal(mapped[0].quantity_reported_mean,'12'); assert.equal(mapped[1].test_repeat_id,'TRP0002');
assert.throws(() => context.attachmentMappedRows(curve,['data_id',''],template));
assert.throws(() => context.attachmentMappedRows(curve,['notes','notes'],template));
assert.throws(() => context.attachmentMappedRows(curve,['notes',''],{...template,test_id:'MISSING'}));
assert.throws(() => context.attachmentMappedRows(curve,['notes',''],{...template,test_repeat_id:'TRP0003'}));
assert.throws(() => context.attachmentMappedRows(parse('type\nwrong','bad.csv'),['data_type'],template));
assert.match(context.attachmentCSV(['value'], [['=1+1'],['-2.5']]), /"'=1\+1"/);
assert.match(context.attachmentCSV(['value'], [['-2.5']]), /"-2.5"/);
assert.match(context.attachmentCSV(['units'], [['-']]), /"-"/);
assert.match(context.attachmentCSV(['value'], [['-2+3']]), /"'-2\+3"/);

// Decode the generated archive independently enough to verify names, bytes, and CRCs.
function crc32(bytes) {
  let crc = 0xffffffff;
  for (const b of bytes) { crc ^= b; for(let k=0;k<8;k++) crc = (crc>>>1) ^ (crc&1 ? 0xedb88320 : 0); }
  return (crc ^ 0xffffffff) >>> 0;
}
function unzipStored(buffer) {
  const result = new Map(); let offset = 0;
  while (buffer.readUInt32LE(offset) === 0x04034b50) {
    const length = buffer.readUInt32LE(offset+18), nameLength = buffer.readUInt16LE(offset+26), extraLength = buffer.readUInt16LE(offset+28);
    const name = buffer.subarray(offset+30,offset+30+nameLength).toString('utf8');
    const start = offset+30+nameLength+extraLength, bytes = buffer.subarray(start,start+length);
    assert.equal(crc32(bytes),buffer.readUInt32LE(offset+14)); assert.ok(!result.has(name)); result.set(name,bytes); offset = start+length;
  }
  assert.equal(buffer.readUInt32LE(offset),0x02014b50);
  assert.equal(buffer.readUInt32LE(buffer.length-22),0x06054b50);
  assert.equal(buffer.readUInt16LE(buffer.length-12),result.size);
  return result;
}
const store = new Map();
const row = {data_id:'DAT1',source_id:'SRC1',test_id:'TST1',data_type:'curve',file_name:'../curve.csv'};
const key = context.recordFileKey('data',row,'file_name');
const file = new Blob(['time,load\n0,-2.5\n1,300']); file.name = '../curve.csv';
store.set(key,file); store.set(key+':import',{kind:'curve',headers:['time','load'],rows:[[0,-2.5],[1,300]],x_units:'s',y_units:'N'});
const geo = {geometry_id:'GEO1',specimen_geometry_file_name:'missing.stl'};
assert.equal(context.recordFileKey('geometries',geo,'specimen_geometry_file_name'),'GEO1');
assert.notEqual(context.recordFileKey('data',row,'file_name'),context.recordFileKey('data',row,'filename'));
const snapshot = {db:{data:[row],geometries:[geo]}};
const built = await context.buildAttachmentPackage(snapshot,async(action,key)=>store.get(key));
const zipped = unzipStored(Buffer.from(await built.blob.arrayBuffer()));
const manifest = JSON.parse(zipped.get('manifest.json'));
assert.equal(manifest.attachments.length,1); assert.equal(manifest.missing_files.length,1);
const link = manifest.attachments[0]; assert.equal(link.record_id,'DAT1'); assert.ok(!link.path.includes('../'));
assert.equal(zipped.get(link.path).toString(),await file.text());
assert.equal(JSON.parse(zipped.get(link.imported_json)).rows.length,2);
assert.equal(JSON.parse(zipped.get('concrete_database.json')).db.data[0].data_id,'DAT1');
assert.ok(zipped.has('tables/data.csv')); assert.ok(zipped.has('README.txt'));
const embedded = JSON.parse(zipped.get('concrete_database.json'));
assert.equal(embedded.attachment_format_version, 1);
assert.equal(embedded.attachments[0].file.name, file.name);
assert.equal(Buffer.from(embedded.attachments[0].file.content_base64, 'base64').toString(), await file.text());
assert.equal(embedded.attachments[0].imported_data.rows.length, 2);
assert.equal(embedded.missing_attachments.length, 1);
const decoded = context.decodeEmbeddedAttachments(embedded);
assert.equal(await decoded[0].file.text(), await file.text());
assert.equal(decoded[0].key, key);
const restorePlan = await context.planEmbeddedRestore(decoded, async()=>undefined);
assert.equal(restorePlan.size, 2);
const noOpPlan = await context.planEmbeddedRestore(decoded, async(a,k)=>restorePlan.get(k));
assert.equal(noOpPlan.size, 0);
await assert.rejects(()=>context.planEmbeddedRestore(decoded, async(a,k)=>k.endsWith(':import') ? {headers:[],rows:[]} : restorePlan.get(k)), /different attachment/);
const broken = plain(embedded); broken.attachments[0].file.size++;
assert.throws(()=>context.decodeEmbeddedAttachments(broken),/size does not match/);
const orphan = plain(embedded); orphan.attachments[0].record_id='missing';
assert.throws(()=>context.decodeEmbeddedAttachments(orphan),/no matching record/);
assert.equal(context.decodeEmbeddedAttachments({db:{}}).length,0);
const again = await context.buildSelfContainedJSON(snapshot, async(a,k)=>restorePlan.get(k));
assert.equal(again.attachments[0].file.content_base64,embedded.attachments[0].file.content_base64);
assert.deepEqual(plain(again.attachments[0].imported_data),embedded.attachments[0].imported_data);
const binary = new File([Uint8Array.from([0,255,128,10,13])], 'binary.dat');
assert.deepEqual([...Buffer.from(await context.attachmentBase64(binary),'base64')],[0,255,128,10,13]);
await assert.rejects(()=>context.buildAttachmentPackage(snapshot,async()=>{throw Error('storage unavailable');}),/storage unavailable/);

// Exercise confirmation/cancellation and persistence failure without a browser session.
function element(tag) {
  return {tag,children:[],style:{},value:'',disabled:false,textContent:'',listeners:{},
    appendChild(child){ this.children.push(child); return child; }, setAttribute(){},
    addEventListener(name, fn){this.listeners[name]=fn;},showModal(){this.open=true;},
    close(){this.open=false;this.listeners.close?.();},remove(){this.removed=true;},
    set innerHTML(value){this.children=[];}
  };
}
const body = element('body'); let id=0, saveOK=true;
Object.assign(context,{document:{createElement:element,body},alert:()=>{},humanizeLabel:s=>s,nextId:()=>`DAT${++id}`,saveState:()=>saveOK,renderTable:()=>{},recordFileStore:async(a,k,f)=>{if(a==='put')store.set(k,f); return store.get(k);}});
const parent = vm.runInContext("({data_id:'PARENT',source_id:'SRC1',test_id:'TST1',data_type:'table'})",context);
context.db.data.push(parent);
const importedFile = new Blob(['quantity_reported_mean\n42']); importedFile.name='values.csv';
await context.openAttachmentImport('data',parent,'filename',importedFile);
let dialog=body.children.at(-1);
function descendants(node){return [node,...node.children.flatMap(descendants)];}
let nodes=descendants(dialog);
const selects=nodes.filter(n=>n.tag==='select');
selects[0].value='records'; selects[0].onchange();
nodes=descendants(dialog); nodes.filter(n=>n.tag==='select').at(-1).value='quantity_reported_mean';
await nodes.find(n=>n.textContent==='Confirm import').onclick();
assert.equal(context.db.data.length,2); assert.equal(context.db.data[1].quantity_reported_mean,'42'); assert.equal(context.db.data[1].data_type,'scalar'); assert.equal(parent.quantity_reported_mean,undefined);
await context.openAttachmentImport('data',parent,'filename',importedFile);
dialog=body.children.at(-1); nodes=descendants(dialog);
const modeSelect=nodes.find(n=>n.tag==='select'); modeSelect.value='records'; modeSelect.onchange();
nodes=descendants(dialog); nodes.filter(n=>n.tag==='select').at(-1).value='quantity_reported_mean';
saveOK=false; await nodes.find(n=>n.textContent==='Confirm import').onclick();
assert.equal(context.db.data.length,2); assert.equal(dialog.open,true);
nodes.find(n=>n.textContent==='Cancel').onclick(); assert.equal(context.db.data.length,2);
console.log('PASS: script syntax, CSV/TSV/JSON parsing, mapping/validation, curves, safe CSVs, ZIP bytes/CRCs/links, embedded JSON file/value round-trip, restore conflicts/legacy loading, missing-file reporting, import confirmation/cancellation, and storage-failure rollback.');
