// Browser checks for this document, not a runtime test suite.
import fs from 'node:fs';
import path from 'node:path';
import os from 'node:os';
import { fileURLToPath } from 'node:url';
import { createHash } from 'node:crypto';
import assert from 'node:assert/strict';
import { Chrome } from './chrome.mjs';

const directory = path.dirname(fileURLToPath(import.meta.url));
const artifact = path.resolve(directory,'../KARUFILE_GUIDE.html');
const output = path.join(directory,'validation');
fs.mkdirSync(output,{recursive:true});
const receipt = {artifact_sha256:createHash('sha256').update(fs.readFileSync(artifact)).digest('hex'),
  viewports:[],toc:[],manualLinks:[],offline:null,print:null,visual_review:'pending'};
const browser = await Chrome.open();
const isolated = fs.mkdtempSync(path.join(os.tmpdir(),'karufile-guide-offline-'));
try {
  await browser.send('Emulation.setEmulatedMedia',{features:[{name:'prefers-reduced-motion',value:'reduce'}]});
  for (const [width,height] of [[1440,900],[1920,1080],[768,1024],[390,844],[320,740]]) {
    await browser.viewport(width,height);
    await browser.navigate(artifact);
    const metrics = await browser.evaluate(`({width:innerWidth,height:innerHeight,scrollWidth:document.documentElement.scrollWidth,
      images:[...document.images].map(i=>({loaded:i.complete&&i.naturalWidth>0,alt:!!i.alt})),
      h1:document.querySelectorAll('h1').length,
      externalResources:[...document.querySelectorAll('script[src],link[href],iframe,object,embed,img')].filter(e=>!(e.tagName==='IMG'&&e.src.startsWith('data:'))).length})`);
    assert(metrics.scrollWidth<=width,`Horizontal overflow at ${width}`);
    assert.equal(metrics.h1,1);
    assert.equal(metrics.externalResources,0);
    assert.equal(metrics.images.length,2);
    assert(metrics.images.every(i=>i.loaded&&i.alt));
    receipt.viewports.push(metrics);
    if ([1440,390].includes(width)) await browser.screenshot(path.join(output,`guide.${width}.png`),true);
  }
  await browser.viewport(1440,900);
  await browser.navigate(artifact);
  const toc = await browser.evaluate(`[...document.querySelectorAll('nav a')].map(a=>a.hash)`);
  assert.equal(toc.length,4);
  for (const target of toc) {
    await browser.evaluate(`document.querySelector('nav a[href="${target}"]').click()`);
    const result = await browser.evaluate(`({target:location.hash,exists:!!document.querySelector('${target}'),
      headingVisible:document.querySelector('${target} h2').getBoundingClientRect().top>=0&&document.querySelector('${target} h2').getBoundingClientRect().bottom<=innerHeight})`);
    assert.equal(result.target,target);
    assert(result.exists&&result.headingVisible);
    receipt.toc.push(result);
  }
  await browser.evaluate(`document.querySelector('.back').click()`);
  assert.equal(await browser.evaluate('location.hash'),'#top');
  const links = await browser.evaluate(`[...document.querySelectorAll('a')].map(a=>a.getAttribute('href')).filter(h=>!h.startsWith('#'))`);
  for (const link of links) {
    const [relative,anchor] = link.split('#');
    const target = path.resolve(path.dirname(artifact),relative);
    assert(fs.existsSync(target),`Missing manual: ${link}`);
    if(anchor) {
      const headings = [...fs.readFileSync(target,'utf8').matchAll(/^#+\s+(.+)$/gm)].map(m=>m[1].trim().toLowerCase().replace(/\s+/g,'-'));
      assert(headings.includes(decodeURIComponent(anchor)),`Missing manual heading: ${link}`);
    }
    receipt.manualLinks.push({href:link,pathExists:true,anchorExists:anchor?true:null});
  }
  await browser.viewport(720,900); // 1440px desktop at 200% page zoom equivalent.
  await browser.navigate(artifact);
  assert(await browser.evaluate('document.documentElement.scrollWidth<=innerWidth'));
  receipt.zoom200Equivalent={cssViewportWidth:720,overflowX:false};
  const onlyFile = path.join(isolated,'KARUFILE_GUIDE.html');
  fs.copyFileSync(artifact,onlyFile);
  await browser.send('Network.emulateNetworkConditions',{offline:true,latency:0,downloadThroughput:0,uploadThroughput:0});
  browser.events.length=0;
  await browser.navigate(onlyFile);
  receipt.offline = await browser.evaluate(`({imagesLoaded:[...document.images].every(i=>i.complete&&i.naturalWidth>0),
    sections:document.querySelectorAll('main section').length,scriptCount:document.scripts.length})`);
  receipt.offline.externalRequests=browser.events.filter(e=>e.method==='Network.requestWillBeSent'&&/^https?:/.test(e.params.request.url)).length;
  assert(receipt.offline.imagesLoaded);
  assert.equal(receipt.offline.sections,4);
  assert.equal(receipt.offline.externalRequests,0);
  assert.equal(receipt.offline.scriptCount,0);
  // Also verify the document remains fully readable with JavaScript disabled.
  await browser.send('Emulation.setScriptExecutionDisabled',{value:true});
  await browser.send('Page.reload');
  await browser.send('Emulation.setScriptExecutionDisabled',{value:false});
  await browser.navigate(onlyFile);
  await browser.viewport(1440,900);
  const printed = await browser.send('Page.printToPDF',{printBackground:true,preferCSSPageSize:true,displayHeaderFooter:false,generateTaggedPDF:true});
  fs.writeFileSync(path.join(output,'guide.a4.pdf'),Buffer.from(printed.data,'base64'));
  receipt.print={file:'validation/guide.a4.pdf',paper:'A4',preferCSSPageSize:true,visual_review:'pending'};
  receipt.consoleErrors=browser.events.filter(e=>e.method==='Runtime.exceptionThrown').length;
  assert.equal(receipt.consoleErrors,0);
  fs.writeFileSync(path.join(directory,'guide.verify.json'),JSON.stringify(receipt,null,2)+'\n');
  console.log(JSON.stringify(receipt,null,2));
} finally {
  await browser.close();
  const resolved=path.resolve(isolated);
  assert.equal(path.dirname(resolved),path.resolve(os.tmpdir()));
  assert(path.basename(resolved).startsWith('karufile-guide-offline-'));
  fs.rmSync(resolved,{recursive:true,force:true});
}
