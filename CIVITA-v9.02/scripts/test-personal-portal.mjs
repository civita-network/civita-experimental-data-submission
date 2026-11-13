import fs from 'node:fs';
import vm from 'node:vm';
import assert from 'node:assert/strict';
const html=fs.readFileSync(new URL('../CIVITA-ExpSubmit-v9.02.html',import.meta.url),'utf8');
const scripts=[...html.matchAll(/<script\b[^>]*>([\s\S]*?)<\/script>/gi)].map(m=>m[1]);
for(const script of scripts)new vm.Script(script);
function declaration(name){const a=html.indexOf('const '+name+' = ');return html.slice(a,html.indexOf('\n};',a)+3);}
function fn(name){const a=html.indexOf('function '+name+'(');assert(a>=0);return html.slice(a,html.indexOf('\n}',a)+2);}
const context=vm.createContext({});
for(const name of ['TABLE_SCHEMAS','VOCABS','FK_TARGETS'])vm.runInContext(declaration(name),context);
vm.runInContext('var db={sentinel:true},validationResults={sentinel:true};',context);
for(const name of ['migratePrintingRow','migratePrintingDb','personalNormalize','cdbTablePrimaryKeys','cdbForeignKeyMap','cdbValidateForeignKeys','cdbSanitizeImportedDb','validate','personalCheck'])vm.runInContext(fn(name),context);
const valid={db:{
  literature_sources:[{source_id:'S1'}],
  material_batches:[{batch_id:'B1',source_id:'S1',batch_label:'Mix 1',material_class:'cement_paste'}],
  geometries:[{geometry_id:'G1',source_id:'S1'}],
  specimens:[{specimen_id:'SP1',source_id:'S1',batch_id:'B1',geometry_id:'G1'}],
  tests:[{test_id:'T1',source_id:'S1',specimen_id:'SP1'}]
}};
function check(value){context.input=value;return vm.runInContext('personalCheck(input)',context);}
assert.equal(check(valid).errors.length,0);
assert(check(valid).warnings.length>0);
for(const value of [null,[],{}, {db:[]},{db:{}},{db:{unknown:[]}}, {db:{literature_sources:[null]}}, {db:{literature_sources:[{}]}}, {db:{literature_sources:[{source_id:'S1',title:{nested:true}}]}}])assert(check(value).errors.length>0);
const duplicate=structuredClone(valid);duplicate.db.tests.push({...duplicate.db.tests[0]});assert(check(duplicate).errors.some(e=>e.includes('duplicate ID')));
const broken=structuredClone(valid);broken.db.tests[0].specimen_id='missing';assert(check(broken).errors.some(e=>e.includes('missing')));
const required=structuredClone(valid);required.db.material_batches[0].batch_label='';assert(check(required).errors.some(e=>e.includes('batch_label')));
assert.equal(JSON.stringify(context.db),'{"sentinel":true}');assert.equal(JSON.stringify(context.validationResults),'{"sentinel":true}');
assert.equal(valid.db.literature_sources[0].title,undefined);
assert.equal((html.match(/class="ml-card" data-mode=/g)||[]).length,4);
assert(html.includes("if (mode === 'json') personalOpen();"));
console.log('PASS: JavaScript syntax, four cards, valid data, warnings, malformed shapes, duplicate IDs, broken links, required fields, and workspace isolation.');

const legacy=structuredClone(valid);
legacy.db.printing_variables=[{printing_id:'P1',source_id:'S1',geometry_id:'G1',volumetric_flow_rate_m3_h:'0.0036',hose_length_m:'2',nozzle_size_mm:'20',nozzle_orientation_angle_deg:'90',deliver_method:'pump'}];
assert.equal(check(legacy).errors.length,0);
context.input=legacy;
const upgraded=vm.runInContext('personalNormalize(input)',context);
assert.equal(upgraded.db.printing_variables[0].volumetric_flow_rate_mm3_sec,'1000');
assert.equal(upgraded.db.printing_variables[0].hose_length_mm,'2000');
assert.equal(upgraded.db.printing_variables[0].nozzle_diameter_mm,'20');
assert.equal(upgraded.db.printing_variables[0].nozzle_orientation,'90 deg');
assert.equal(upgraded.db.printing_variables[0]._legacy_printing_fields.deliver_method,'pump');
assert.equal(legacy.db.printing_variables[0].hose_length_m,'2');
const uncertain=structuredClone(legacy);uncertain.db.printing_variables[0].hose_length_m='2 to 3 m';
assert(check(uncertain).warnings.some(e=>e.includes('hose_length_mm')));
context.input=upgraded;
assert.equal(JSON.stringify(vm.runInContext('personalNormalize(input)',context)),JSON.stringify(upgraded));
console.log('PASS: legacy printing conversion, preserved metadata, migration warnings, and idempotent normalization.');
