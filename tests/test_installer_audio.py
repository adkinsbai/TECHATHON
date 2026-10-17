import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import unittest

from test_installer import ROOT, fixture


HARNESS = r'''
const fs = require('fs'), vm = require('vm');
const source = fs.readFileSync(process.argv[2], 'utf8'), page = process.argv[3];
function deferred() { let resolve, reject; const promise = new Promise((a,b) => { resolve=a; reject=b; }); return {promise, resolve, reject}; }
function setup(fetch) {
  const handlers = {}, stats = {played:0, paused:0, spoken:0, cancelled:0};
  const synth = {cancel(){ stats.cancelled++; }, getVoices(){ return []; }, speak(){ stats.spoken++; }};
  const context = {console:{warn(){}}, window:{BodyClient:{routesAudio:false}, speechSynthesis:synth,
      addEventListener(name, fn){ handlers[name] = fn; }}, speechSynthesis:synth,
    SpeechSynthesisUtterance:class {}, Avatar:{speaking(){}}, Cat:{talking:false},
    Audio:class {play(){ stats.played++; this.onplay?.(); return Promise.resolve(); } pause(){ stats.paused++; this.onpause?.(); }},
    URL:{createObjectURL(){ return 'blob:test'; }, revokeObjectURL(){}}, fetch,
    voiceOn:true, ttsMode:'glm', persona:{voice:'local'}, currentAudio:null,
    cleanForSpeech:t=>t, getVoiceOn:()=>true, $:()=>({}), setInterval(){}, streamReply(){}, busy:false};
  vm.createContext(context); vm.runInContext(source, context);
  return {context, stats, status(value){ context.window.BodyClient.routesAudio=value; handlers['body:status']({detail:{connected:value,phase:'idle'}}); }};
}
const response = () => ({ok:true, blob:async()=>({})});
(async()=>{
  const results = {};
  for (const stage of ['fetch','blob','error']) {
    const gate = deferred(), entered = deferred();
    const env = setup(stage==='blob' ? async()=>({ok:true, blob(){ entered.resolve(); return gate.promise; }}) : ()=>gate.promise);
    const pending = env.context.speak('old automatic reply');
    if (stage==='blob') await entered.promise;
    env.status(true); env.status(false);
    if (stage==='error') gate.reject(new Error('late failed synthesis'));
    else gate.resolve(stage==='fetch' ? response() : {});
    await pending;
    results[stage] = env.stats.played===0 && env.stats.spoken===0;
  }
  const active = setup(async()=>response());
  await active.context.speak('already playing'); active.status(true);
  results.active = active.stats.played===1 && active.stats.paused===1;
  const browser = setup(async()=>{ throw new Error('use browser fallback'); });
  browser.context.ttsMode='browser';
  await browser.context.speak('browser speech'); const before=browser.stats.cancelled; browser.status(true);
  results.browser = browser.stats.spoken===1 && browser.stats.cancelled>before;
  if (page==='chat') {
    const gate=deferred(), preview=setup(()=>gate.promise);
    const pending=preview.context.speak('manual preview',true);
    preview.status(true); preview.status(false); preview.status(true);
    gate.resolve(response()); await pending;
    results.preview = preview.stats.played===1 && preview.stats.paused===0;
  }
  process.stdout.write(JSON.stringify(results));
})().catch(error=>{ console.error(error); process.exitCode=1; });
'''


class AudioTakeoverTests(unittest.TestCase):
    def test_pending_and_active_browser_speech_yield_to_body(self):
        spec = importlib.util.spec_from_file_location('installer_audio', ROOT / 'install_companion.py')
        installer = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(installer)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fixture(root)
            changes = installer.build_changes(root)
            harness = root / 'audio-harness.cjs'
            harness.write_text(HARNESS, encoding='utf-8')
            for page, name in (('chat', 'static/app.js'), ('world', 'static/world.js')):
                with self.subTest(page=page):
                    target = root / name
                    target.write_bytes(changes[name])
                    result = subprocess.run(['node', str(harness), str(target), page], capture_output=True, text=True, timeout=15)
                    self.assertEqual(result.returncode, 0, result.stderr)
                    outcomes = json.loads(result.stdout)
                    self.assertTrue(all(outcomes.values()), outcomes)


if __name__ == '__main__':
    unittest.main()
