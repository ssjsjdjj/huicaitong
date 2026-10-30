import fs from 'node:fs';
import path from 'node:path';
import {pathToFileURL} from 'node:url';
const manifest=JSON.parse(fs.readFileSync('dist/assets.json','utf8'));
const sdk=path.resolve('dist'+manifest.runtime_base);
const {loadPyodide}=await import(pathToFileURL(path.join(sdk,'pyodide.mjs')));
const py=await loadPyodide({indexURL:sdk.replaceAll('\\','/')+'/'});
console.log(py.runPython("import sqlite3, hashlib, ssl, subprocess; str((sqlite3.sqlite_version, hashlib.sha256(b'test').hexdigest()))"));
