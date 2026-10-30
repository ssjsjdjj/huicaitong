import fs from 'node:fs';
import assert from 'node:assert/strict';
import path from 'node:path';
import {pathToFileURL} from 'node:url';
try {
const manifest=JSON.parse(fs.readFileSync('dist/assets.json','utf8'));
const sdk=path.resolve('dist'+manifest.runtime_base);
const {loadPyodide}=await import(pathToFileURL(path.join(sdk,'pyodide.mjs')));
const py=await loadPyodide({indexURL:sdk.replaceAll('\\','/')+'/'});
py.unpackArchive(new Uint8Array(fs.readFileSync('dist/python-app.zip')),'zip',{extractDir:'/app'});
py.runPython("import sys; sys.path.insert(0,'/app'); from browser_backend import request_json");
const dispatch=py.globals.get('request_json');
const specs=JSON.parse(fs.readFileSync('.work/online-qa-baseline.json','utf8'));
for(const [index,test] of specs.entries()){
  const actual=JSON.parse(dispatch(test.url,JSON.stringify(test.body)));
  try{assert.deepStrictEqual(actual,test.expected);}
  catch(error){console.error('Parity failed:',index,test.url);throw error;}
}
const result={scenarios:specs.length,all_equal:true,native_python:'3.12',browser_python:'3.14.2',runtime:'Pyodide 314.0.7'};
fs.writeFileSync('parity-verification.json',JSON.stringify(result,null,2)+'\n');
console.log(JSON.stringify(result));
} catch(error) {console.error(error.message.slice(0,6000));process.exitCode=1;}
