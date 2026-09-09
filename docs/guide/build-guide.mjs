// Run after Archify validate/deliver/visual-check. Never edits delivered diagrams.
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { createHash } from 'node:crypto';
import { Chrome } from './chrome.mjs';

const directory = path.dirname(fileURLToPath(import.meta.url));
const hash = bytes => createHash('sha256').update(bytes).digest('hex');
let html = fs.readFileSync(path.join(directory,'guide.template.html'),'utf8');
const browser = await Chrome.open();
const receipt = {diagrams:[],html:null};
try {
  await browser.viewport(1440,900);
  for (const [name,token] of [['copies','@@COPIES_IMAGE@@'],['pdf-choices','@@PDF_IMAGE@@']]) {
    const artifact = path.join(directory,`${name}.html`);
    const delivery = JSON.parse(fs.readFileSync(path.join(directory,`${name}.delivery.json`),'utf8').replace(/^\uFEFF/,''));
    const visual = JSON.parse(fs.readFileSync(path.join(directory,`${name}.visual-check.json`),'utf8'));
    if (!delivery.ok || delivery.validation.checksPassed!==9 || !visual.ok ||
        delivery.artifact.sha256!==hash(fs.readFileSync(artifact)) ||
        visual.artifact.sha256!==delivery.artifact.sha256 ||
        delivery.specification.sha256!==hash(fs.readFileSync(path.join(directory,`${name}.architecture.json`))))
      throw new Error(`Unverified or stale diagram: ${name}`);
    await browser.navigate(artifact,'?theme=light');
    // Capture the canonical PNG produced by the actual export menu. Suppress
    // only the download click; do not change the SVG or export implementation.
    const exported = await browser.evaluate(`(async () => {
      let exportedBlob;
      const makeURL = URL.createObjectURL.bind(URL);
      URL.createObjectURL = blob => { if(blob.type==='image/png') exportedBlob=blob; return makeURL(blob); };
      const click = HTMLAnchorElement.prototype.click;
      HTMLAnchorElement.prototype.click = function(){ if(!this.download) return click.call(this); };
      document.querySelector('button[data-format="png"]').click();
      const deadline = Date.now()+15000;
      while((!exportedBlob || document.documentElement.getAttribute('data-last-export-canonical')!=='true') && Date.now()<deadline)
        await new Promise(r=>setTimeout(r,40));
      if(!exportedBlob || document.documentElement.getAttribute('data-last-export-canonical')!=='true')
        throw new Error('Canonical PNG export failed');
      const data = await new Promise((resolve,reject) => { const reader=new FileReader(); reader.onload=()=>resolve(reader.result); reader.onerror=reject; reader.readAsDataURL(exportedBlob); });
      return {data,theme:document.documentElement.dataset.theme,canonical:true};
    })()`);
    if(exported.theme!=='light' || !exported.data.startsWith('data:image/png;base64,')) throw new Error('Unexpected export format');
    const png = Buffer.from(exported.data.split(',')[1],'base64');
    fs.writeFileSync(path.join(directory,`${name}.png`),png);
    html = html.replace(token,exported.data);
    receipt.diagrams.push({name,specification:delivery.specification,artifact:delivery.artifact,
      export:{sha256:hash(png),bytes:png.length,canonical:true,theme:exported.theme,
        width:png.readUInt32BE(16),height:png.readUInt32BE(20)}});
  }
  if (html.includes('@@')) throw new Error('Unresolved template token');
  const output = path.resolve(directory,'../KARUFILE_GUIDE.html');
  fs.writeFileSync(output,html);
  receipt.html = {file:'../KARUFILE_GUIDE.html',sha256:hash(Buffer.from(html)),bytes:Buffer.byteLength(html)};
  fs.writeFileSync(path.join(directory,'guide.build.json'),JSON.stringify(receipt,null,2)+'\n');
  console.log(JSON.stringify(receipt,null,2));
} finally { await browser.close(); }
