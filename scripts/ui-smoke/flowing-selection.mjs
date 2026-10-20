import assert from 'node:assert/strict';
import fs from 'node:fs';
import { createHash } from 'node:crypto';
import { pathToFileURL } from 'node:url';
import { chromium } from 'playwright';
const serverModule = process.env.WEBCODEX_UI_SERVER_MODULE
  ? pathToFileURL(process.env.WEBCODEX_UI_SERVER_MODULE).href : new URL('./server.mjs', import.meta.url).href;
const { startFixtureServer } = await import(serverModule);
const theme=process.env.WEBCODEX_MOTION_THEME ?? 'light';
assert(['light','dark'].includes(theme),'Use light or dark for WEBCODEX_MOTION_THEME');
const output = new URL(`../../artifacts/flowing-selection/${theme}/`, import.meta.url);
fs.mkdirSync(output, { recursive: true });
const report = { theme, fixture: true, nativeBackend: false, checks: [], errors: [], limitations: ['Production Chromium renderers with synthetic loopback fixtures; no live Runtime or native WebView.'] };
const buildRoot = new URL('../../', serverModule);
report.bundles = ['frontend/dist/app.js','frontend/dist/styles.css','apps/desktop/dist/index.html'].map(file=>{
  const bytes=fs.readFileSync(new URL(file,buildRoot));return {file,sha256:createHash('sha256').update(bytes).digest('hex')};
});
const fixture = await startFixtureServer();
const browser = await chromium.launch({ headless: true });
let context;
async function frames(page, count = 2) { await page.evaluate(count => new Promise(resolve => { const tick = () => --count ? requestAnimationFrame(tick) : resolve(); requestAnimationFrame(tick); }), count); }
async function shot(page, name) { await page.screenshot({ path: new URL(name + '.png', output).pathname, caret: 'hide' }); }
async function settle(page) {
  await page.evaluate(() => { for (const a of document.getAnimations()) if (a.effect?.target?.matches('[data-selection-motion-overlay]')) a.finish(); });
  await frames(page);
}
async function exercise(page, selector, name) {
  const group = page.locator(selector).first();
  await group.waitFor();
  await group.locator('[data-selection-motion-plate]').waitFor({ state: 'attached' });
  await settle(page);
  const result = await group.evaluate(async (group) => {
    const raf = () => new Promise(resolve => requestAnimationFrame(resolve));
    const plate = group.querySelector('[data-selection-motion-plate]');
    const items = [...group.querySelectorAll('[data-selection-motion-item]')];
    const selected = () => items.find(item => item.hasAttribute('data-selection-motion-selected'));
    const box = node => { const b = node.getBoundingClientRect(),o=node.closest('[data-selection-motion]').getBoundingClientRect(); return { x:b.x-o.x,y:b.y-o.y,width:b.width,height:b.height }; };
    const near = (a,b) => ['x','y','width','height'].every(key => Math.abs(a[key]-b[key]) < 1.1);
    const click = item => (item.querySelector('input') || item).click();
    const textBoxes = node => {
      const walker=document.createTreeWalker(node,NodeFilter.SHOW_TEXT), result=[];
      while(walker.nextNode()){const text=walker.currentNode;if(!text.textContent.trim())continue;const range=document.createRange();range.selectNodeContents(text);const b=range.getBoundingClientRect();result.push({text:text.textContent,x:b.x,y:b.y,width:b.width,height:b.height});}return result;
    };
    const first = selected(), target = items.find(item => item !== first);
    if (!target) throw Error('Expected at least two items');
    const before = box(plate);
    const other = [...document.querySelectorAll('[data-selection-motion-plate]')].filter(node => node !== plate).map(node => [node, node.closest('[data-selection-motion]').querySelector('[data-selection-motion-selected]')]);
    click(target); await Promise.resolve(); const immediateAnimations=plate.getAnimations().length; await raf();
    const animations = plate.getAnimations();
    if (!animations.length) return {missingAnimation:true,connected:plate.isConnected,immediateAnimations,before,end:target.isConnected?box(target):null,actual:plate.isConnected?box(plate):null,selected: selected()?.textContent,items:items.map(item=>({text:item.textContent,selected:item.hasAttribute('data-selection-motion-selected'),checked:item.querySelector('input')?.checked}))};
    const animation = animations[0]; animation.pause();
    const duration = animation.effect.getTiming().duration;
    const end = box(target), samples = [];
    for (const time of [0, 65, 130, 187.2, 230, 259]) {
      animation.currentTime = time; await raf();
      const actual = box(plate); samples.push({ time, ...actual });
      if (actual.width > Math.max(before.width,end.width)*1.0301+.1 || actual.height > Math.max(before.height,end.height)*1.0301+.1) throw Error('Stretch exceeds 3%');
    }
    const intermediate = samples.some(sample => !near(sample,before) && !near(sample,end));
    animation.finish(); await raf();
    const aligned = near(box(plate), box(target));
    // A reversal starts at the actual visible intermediate geometry, not the old target.
    click(first); await Promise.resolve(); await raf();
    let reversing = plate.getAnimations()[0]; reversing?.pause(); if (reversing) reversing.currentTime=90; await raf();
    const interrupted = box(plate);
    const skip = items.at(-1) === first ? target : items.at(-1);
    click(skip); await Promise.resolve();
    const nextAnimation = plate.getAnimations()[0]; nextAnimation?.pause(); if (nextAnimation) nextAnimation.currentTime=0;
    const resumed=box(plate); const continuous = near(resumed, interrupted);
    for (const a of group.getAnimations({subtree:true})) a.finish(); await raf();
    const mirrors=[...group.querySelectorAll('[data-selection-motion-label]')];
    const textGeometry=items.map((item,index)=>({original:textBoxes(item),mirror:textBoxes(mirrors[index])}));
    const iconGeometry=items.map((item,index)=>({original:[...item.querySelectorAll('svg')].map(box),mirror:[...mirrors[index].querySelectorAll('svg')].map(box)}));
    const stationaryIcons=iconGeometry.every(({original,mirror})=>original.length===mirror.length&&original.every((icon,index)=>near(icon,mirror[index])));
    const stationaryText=textGeometry.every(({original,mirror})=>original.length===mirror.length&&original.every((text,index)=>text.text===mirror[index].text&&near(text,mirror[index])));
    return { duration, intermediate, aligned, continuous, interrupted, resumed, stationaryText, textGeometry, stationaryIcons, iconGeometry, persistent: plate===group.querySelector('[data-selection-motion-plate]'),
      finalAligned:near(box(plate),box(selected())), count:group.querySelectorAll('[data-selection-motion-plate]').length,
      stationaryLabels:[...items,...group.querySelectorAll('[data-selection-motion-label]')].every(item=>getComputedStyle(item).transform==='none'),
      isolated:other.filter(([node])=>node.isConnected).every(([node,old])=>node.closest('[data-selection-motion]').querySelector('[data-selection-motion-selected]')===old), samples };
  });
  if(result.missingAnimation){(report.failures??=[]).push({name,...result});return;}
  assert.equal(result.duration,260,name); for (const key of ['intermediate','aligned','continuous','persistent','finalAligned','stationaryLabels','isolated']) assert(result[key],`${name}: ${key} ${JSON.stringify(result)}`);
  if(!result.stationaryIcons)(report.failures??=[]).push({name,stationaryIcons:false,iconGeometry:result.iconGeometry});
  if(!result.stationaryText)(report.failures??=[]).push({name,stationaryText:false,textGeometry:result.textGeometry});
  assert.equal(result.count,1,name); report.checks.push({ name, ...result });
}
async function midpoint(page, selector, name) {
  await page.locator(selector).first().evaluate(async group=>{
    const target=[...group.querySelectorAll('[data-selection-motion-item]')].find(item=>!item.hasAttribute('data-selection-motion-selected'));
    (target.querySelector('input')||target).click();await Promise.resolve();await new Promise(resolve=>requestAnimationFrame(resolve));
    for(const animation of group.getAnimations({subtree:true})) {animation.pause();animation.currentTime=90;}
    await new Promise(resolve=>requestAnimationFrame(resolve));
  });
  await shot(page,name+'-mid-motion');
  await page.locator(selector).first().screenshot({path:new URL(name+'-selection.png',output).pathname});
  await settle(page);
}
async function resize(page, selector, name) {
  for (const width of [1400,1024,780]) {
    await page.setViewportSize({width,height:1000}); await frames(page,3); await settle(page);
    const result=await page.locator(selector).first().evaluate(group=>{
      const a=group.querySelector('[data-selection-motion-plate]').getBoundingClientRect(),b=group.querySelector('[data-selection-motion-selected]').getBoundingClientRect();
      return { plate:{x:a.x,y:a.y,width:a.width,height:a.height},target:{x:b.x,y:b.y,width:b.width,height:b.height}, aligned:['x','y','width','height'].every(key=>Math.abs(a[key]-b[key])<1.1), rows:new Set([...group.querySelectorAll('[data-selection-motion-item]')].map(item=>Math.round(item.getBoundingClientRect().y))).size };
    });
    if(!result.aligned)(report.failures??=[]).push({name:`${name} resize ${width}`, ...result}); report.checks.push({name:`${name} resize`,width,...result}); await shot(page,`${name}-${width}`);
  }
  await page.setViewportSize({width:1400,height:1000}); await frames(page,3);
  const restored=await page.locator(selector).first().evaluate(node=>getComputedStyle(node).position); assert.equal(restored,'sticky',`${name} restores sticky desktop position`); report.checks.push({name:`${name} restores sticky`,position:restored});
}
async function accessibility(page, selector, name) {
  const group=page.locator(selector).first();
  const radios=group.locator('input[type=radio]');
  const start=await radios.count()?radios.first():group.locator('[data-selection-motion-item]').first(); await start.focus();
  const before=await start.getAttribute('aria-selected');
  await page.keyboard.press('ArrowRight'); await frames(page);
  // Desktop vertical categories use ArrowDown as their navigation axis.
  if (await start.evaluate(node=>node.closest('[aria-orientation="vertical"]')!==null)) await page.keyboard.press('ArrowDown');
  const keyboard=await group.evaluate(group=>group.contains(document.activeElement)&&(document.activeElement.matches('[data-selection-motion-selected]')||(document.activeElement.checked&&[...document.activeElement.labels].some(label=>label.matches('[data-selection-motion-selected]')))));
  assert(keyboard,`${name} keyboard state/focus`); report.checks.push({name:`${name} keyboard state/focus`,before});
  await page.emulateMedia({reducedMotion:'reduce'}); await page.waitForFunction(()=>matchMedia('(prefers-reduced-motion: reduce)').matches); await frames(page);
  await group.evaluate(async group=>{ const items=[...group.querySelectorAll('[data-selection-motion-item]')],next=items.find(item=>!item.hasAttribute('data-selection-motion-selected'));(next.querySelector('input')||next).click();await Promise.resolve(); });
  await frames(page); const reducedState=await group.locator('[data-selection-motion-plate]').evaluate(node=>({matches:matchMedia('(prefers-reduced-motion: reduce)').matches,animations:node.getAnimations().map(a=>({type:a.constructor.name,state:a.playState,timing:a.effect.getTiming(),frames:a.effect.getKeyframes()}))})); assert.equal(reducedState.animations.length,0,`${name} reduced motion ${JSON.stringify(reducedState)}`);
  await shot(page,`${name}-reduced-motion`);
  await page.emulateMedia({forcedColors:'active',reducedMotion:'no-preference'}); await frames(page);
  assert.equal(await group.locator('[data-selection-motion-plate]').evaluate(node=>getComputedStyle(node).display),'none');
  const color=await group.locator('[data-selection-motion-selected]').evaluate(node=>({background:getComputedStyle(node).backgroundColor,color:getComputedStyle(node).color}));
  assert.notEqual(color.background,'rgba(0, 0, 0, 0)',`${name} forced colors selection`); await shot(page,`${name}-forced-colors`);
  report.checks.push({name:`${name} reduced motion and forced colors`,color}); await page.emulateMedia({forcedColors:'none',reducedMotion:'no-preference'}); await frames(page);
}
try {
  context=await browser.newContext({viewport:{width:1400,height:1000},colorScheme:theme,recordVideo:{dir:output.pathname,size:{width:1400,height:1000}}});
  await context.addInitScript(theme=>{localStorage.setItem('webcodex.desktop.appearance.v1',theme);localStorage.setItem('webcodex.runtime.appearance.v1',theme);},theme);
  const desktop=await context.newPage(); desktop.setDefaultTimeout(10000); desktop.on('pageerror',error=>report.errors.push(error.message));
  await desktop.goto(fixture.url+'/desktop/');
  await desktop.waitForFunction(theme=>document.documentElement.dataset.theme===theme,theme);
  for(const [destination,selector] of [['activity','.workspace-tabs'],['settings','.settings-navigation'],['extensions','.extensions-navigation']]) {
    await desktop.locator(`[data-webcodex-action="navigate-${destination}"]`).click();
    await exercise(desktop,selector,`desktop-${destination}`);
    if(destination==='settings'){await midpoint(desktop,selector,'desktop-settings');await resize(desktop,selector,'desktop-settings');await accessibility(desktop,selector,'desktop-settings');}
    await shot(desktop,`desktop-${destination}`);
  }
  report.desktopFixtureWarnings=await desktop.locator('.app-error').allTextContents();
  const runtime=await context.newPage(); runtime.setDefaultTimeout(10000); runtime.on('pageerror',error=>report.errors.push(error.message));
  await runtime.route('**/api/runtime-console/communication/**',route=>{
    const name=route.request().url().split('/communication/')[1];
    const agent={agent_id:'reviewer',handle:'reviewer',display_name:'Motion reviewer',description:'Fixture only',profile_revision:1,active_endpoint_count:0,queued_delivery_count:0};
    return route.fulfill({json:name==='agents'?{agents:[agent]}:name==='conversations'?{conversations:[]}:{}});
  });
  await runtime.goto(fixture.url+'/runtime/');
  await runtime.waitForFunction(theme=>document.documentElement.dataset.resolvedTheme===theme,theme);
  await exercise(runtime,'.work-surface-control','runtime-work-surface');
  await accessibility(runtime,'.work-surface-control','runtime-work-surface');
  await runtime.getByRole('radio',{name:/Activity/}).evaluate(node=>node.click());
  await exercise(runtime,'.window-center-tabs','runtime-window-views');
  await runtime.locator('#window-activity-tab').click();
  await exercise(runtime,'.window-activity-order','runtime-activity-order');
  await accessibility(runtime,'.window-activity-order','runtime-activity-order');
  await shot(runtime,'runtime-window');
  await runtime.locator('.app-nav').getByRole('button',{name:/^Runtime/}).click();
  await exercise(runtime,'.runtime-view-tabs','runtime-overview-agents');
  await runtime.getByRole('tab',{name:'Agents',exact:true}).click();
  await runtime.getByRole('heading',{name:'Motion reviewer',exact:true}).waitFor();
  await exercise(runtime,'.agent-tabs','runtime-agent-sections');
  await shot(runtime,'runtime-agents');
  // The public Session record action reaches retained Session, inspector and composer groups.
  await runtime.locator('.app-nav').getByRole('button',{name:/^Work/}).click();
  await runtime.getByRole('radio',{name:/Activity/}).evaluate(node=>node.click());
  await runtime.locator('#window-activity-tab').click();
  await runtime.getByRole('combobox',{name:'Session filter'}).selectOption({index:1});
  await runtime.getByRole('button',{name:'View Session record',exact:true}).click();
  await exercise(runtime,'.session-main > .session-view-tabs','runtime-session-views');
  await exercise(runtime,'.inspector .segmented','runtime-inspector');
  await runtime.locator('#collaboration-tab').click();
  await exercise(runtime,'.composer-kind-tabs','runtime-message-kinds');
  await midpoint(runtime,'.composer-kind-tabs','runtime-message-kinds');
  await shot(runtime,'runtime-session');
  await accessibility(runtime,'.inspector .segmented','runtime-inspector');
  assert.deepEqual(report.errors,[]); assert.deepEqual(report.failures??[],[]);
} catch(error) { report.failure=error.stack; throw error; }
finally {
  const videos=context?.pages().map(page=>page.video())??[];
  if(context) await context.close();
  report.videos=[];for(let i=0;i<videos.length;i++){const name=i===0?'desktop-motion.webm':'runtime-motion.webm';await videos[i].saveAs(new URL(name,output).pathname);report.videos.push(name);} await browser.close(); await new Promise(resolve=>fixture.server.close(resolve));
  fs.writeFileSync(new URL('report.json',output),JSON.stringify(report,null,2));
  console.log(JSON.stringify({checks:report.checks.length,errors:report.errors,failure:report.failure,output:output.pathname}));
}
