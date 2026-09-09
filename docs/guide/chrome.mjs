// Local documentation rendering only. No npm packages or running Chrome profile.
import { spawn } from 'node:child_process';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { pathToFileURL } from 'node:url';

export class Chrome {
  static async open() {
    const executable = [process.env.GUIDE_CHROME,
      'C:/Program Files/Google/Chrome/Application/chrome.exe',
      'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe']
      .find(p => p && fs.existsSync(p));
    if (!executable) throw new Error('Set GUIDE_CHROME to a local Chromium executable.');
    const browser = new Chrome(executable);
    try {
      const { targetId } = await browser.send('Target.createTarget', { url:'about:blank' });
      browser.session = (await browser.send('Target.attachToTarget', { targetId, flatten:true })).sessionId;
      await browser.send('Page.enable');
      await browser.send('Runtime.enable');
      await browser.send('Network.enable');
      return browser;
    } catch (error) { await browser.close(); throw error; }
  }
  constructor(executable) {
    this.profile = fs.mkdtempSync(path.join(os.tmpdir(), 'karufile-guide-chrome-'));
    this.nextId = 1;
    this.pending = new Map();
    this.events = [];
    this.buffer = '';
    this.child = spawn(executable, ['--headless=new','--remote-debugging-pipe',
      '--disable-background-networking','--disable-component-update','--disable-sync',
      '--no-first-run','--no-default-browser-check',`--user-data-dir=${this.profile}`],
      { windowsHide:true, stdio:['ignore','ignore','ignore','pipe','pipe'] });
    this.child.stdio[4].setEncoding('utf8');
    this.child.stdio[4].on('data', chunk => {
      this.buffer += chunk;
      let index;
      while ((index = this.buffer.indexOf('\0')) !== -1) {
        const raw = this.buffer.slice(0,index);
        this.buffer = this.buffer.slice(index+1);
        if (!raw) continue;
        const message = JSON.parse(raw);
        if (!message.id) { this.events.push(message); continue; }
        const pending = this.pending.get(message.id);
        if (!pending) continue;
        clearTimeout(pending.timer);
        this.pending.delete(message.id);
        if (message.error) pending.reject(new Error(`${pending.method}: ${message.error.message}`));
        else pending.resolve(message.result);
      }
    });
    const fail = error => {
      for (const p of this.pending.values()) { clearTimeout(p.timer); p.reject(error); }
      this.pending.clear();
    };
    this.child.on('error', fail);
    this.child.on('exit', code => fail(new Error(`Chrome exited (${code})`)));
  }
  send(method, params = {}) {
    const id = this.nextId++;
    return new Promise((resolve,reject) => {
      const timer = setTimeout(() => { this.pending.delete(id); reject(new Error(`${method} timed out`)); },20000);
      this.pending.set(id,{method,resolve,reject,timer});
      this.child.stdio[3].write(JSON.stringify({id,method,params,...(this.session?{sessionId:this.session}:{})})+'\0');
    });
  }
  async evaluate(expression) {
    const result = await this.send('Runtime.evaluate', {expression,awaitPromise:true,returnByValue:true});
    if (result.exceptionDetails) throw new Error(result.exceptionDetails.exception?.description || result.exceptionDetails.text);
    return result.result?.value;
  }
  async viewport(width,height,scale=1) {
    await this.send('Emulation.setDeviceMetricsOverride',{width,height,deviceScaleFactor:scale,mobile:false});
  }
  async navigate(file, query='') {
    const result = await this.send('Page.navigate', {url:pathToFileURL(path.resolve(file)).href+query});
    if (result.errorText) throw new Error(result.errorText);
    await this.evaluate(`new Promise((resolve,reject) => {
      const deadline=Date.now()+10000;
      function ready(){
        if(document.readyState==='complete') document.fonts.ready.then(() => requestAnimationFrame(() => requestAnimationFrame(resolve)));
        else if(Date.now()>deadline) reject(new Error('Page did not load'));
        else setTimeout(ready,30);
      } ready();
    })`);
  }
  async screenshot(file,fullPage=false) {
    const params = {format:'png',captureBeyondViewport:fullPage};
    if (fullPage) {
      const size = await this.evaluate('({width:document.documentElement.clientWidth,height:document.documentElement.scrollHeight})');
      params.clip = {x:0,y:0,...size,scale:1};
    }
    const result = await this.send('Page.captureScreenshot',params);
    fs.writeFileSync(file,Buffer.from(result.data,'base64'));
  }
  async close() {
    if (this.child.exitCode===null) {
      const exited = new Promise(resolve => this.child.once('exit',resolve));
      this.child.kill();
      await Promise.race([exited,new Promise(resolve=>setTimeout(resolve,1500))]);
    }
    const resolved = path.resolve(this.profile);
    if (path.dirname(resolved)!==path.resolve(os.tmpdir()) || !path.basename(resolved).startsWith('karufile-guide-chrome-'))
      throw new Error('Unexpected browser profile cleanup path');
    try { fs.rmSync(resolved,{recursive:true,force:true}); } catch { /* Chrome may retain its temporary profile briefly. */ }
  }
}
