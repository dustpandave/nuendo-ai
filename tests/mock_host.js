// Runs the generated script against a permissive fake of midiremote_api_v1
// and records every binding it makes. Usage: node tests/mock_host.js <script.js>
const fs = require('fs')
const log = { commandBindings: [], valueBindings: 0, actionBindings: 0, midi: [], sent: [] }

function anyObject(name) {
  const target = function () {}
  return new Proxy(target, {
    get(t, prop) {
      if (prop === Symbol.toPrimitive) return () => name
      if (prop === 'toString') return () => name
      if (!(prop in t)) t[prop] = anyObject(name + '.' + String(prop))
      return t[prop]
    },
    set(t, prop, v) { t[prop] = v; return true },
    apply() { return anyObject(name + '()') },
  })
}

function makeBinding(desc) {
  const b = {}
  b.setInputPort = () => b
  b.bindToControlChange = (ch, cc) => { log.midi.push(['cc', ch, cc, desc]); return b }
  b.bindToNote = (ch, n) => { log.midi.push(['note', ch, n, desc]); return b }
  return b
}
const elementsByNote = {}
function makeElement(kind) {
  const el = { mSurfaceValue: { mMidiBinding: makeBinding(kind) } }
  const orig = el.mSurfaceValue.mMidiBinding.bindToNote
  el.mSurfaceValue.mMidiBinding.bindToNote = (ch, n) => { elementsByNote[ch + ':' + n] = el; return orig(ch, n) }
  return el
}

const outputs = []
const api = {
  makeDeviceDriver() {
    const page = anyObject('page')
    page.makeCommandBinding = (sv, cat, name) => { log.commandBindings.push(cat + '/' + name); return anyObject('cb') }
    page.makeValueBinding = () => { log.valueBindings++; return anyObject('vb') }
    page.makeActionBinding = () => { log.actionBindings++; return anyObject('ab') }
    const output = { sendMidi(dev, data) { log.sent.push(data) } }
    outputs.push(output)
    return {
      mPorts: { makeMidiInput: () => ({}), makeMidiOutput: () => output },
      makeDetectionUnit: () => {
        const d = { detectPortPair: () => d, expectInputNameContains: () => d, expectOutputNameContains: () => d }
        return d
      },
      mSurface: { makeButton: () => makeElement('button'), makeKnob: () => makeElement('knob') },
      mMapping: { makePage: () => page },
      set mOnActivate(fn) { this._activate = fn },
      get mOnActivate() { return this._activate },
    }
  },
}
const src = fs.readFileSync(process.argv[2], 'utf8')
const driver = { ref: null }
const fakeRequire = (m) => {
  if (m !== 'midiremote_api_v1') throw new Error('unexpected require ' + m)
  const real = api.makeDeviceDriver
  return { makeDeviceDriver: (...a) => (driver.ref = real(...a)) }
}
new Function('require', src)(fakeRequire)
driver.ref.mOnActivate({})
const before = log.sent.length
const resync = elementsByNote[process.argv[3]]
if (resync) resync.mSurfaceValue.mOnProcessValueChange({}, 1)
const resyncSent = log.sent.length - before
// Check MIDI addresses are unique
const seen = new Set()
for (const [kind, ch, n] of log.midi) {
  const k = kind + ':' + ch + ':' + n
  if (seen.has(k)) throw new Error('duplicate MIDI binding ' + k)
  seen.add(k)
}
console.log(JSON.stringify({
  commands: log.commandBindings.length,
  firstCommands: log.commandBindings.slice(0, 3),
  valueBindings: log.valueBindings,
  actionBindings: log.actionBindings,
  midiBindings: log.midi.length,
  helloSysex: log.sent[0],
  resyncSent,
}))
