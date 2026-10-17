import test from 'node:test';
import assert from 'node:assert/strict';
import {inputCode} from '../companion/static/world-input.js';
test('physical movement keys survive IME key names',()=>{assert.equal(inputCode({code:'KeyW',key:'Process'}),'KeyW');});
test('embedded webview key-only events move and release the same key',()=>{for(const key of ['w','W'])assert.equal(inputCode({code:'Unidentified',key}),'KeyW');assert.equal(inputCode({code:'',key:'d'}),'KeyD');});
test('jump, turn, shift and pause normalize without a code',()=>{for(const [key,code] of [[' ','Space'],['ArrowLeft','ArrowLeft'],['Shift','ShiftLeft'],['Escape','Escape']])assert.equal(inputCode({key}),code);});
test('unknown composition events do not become stuck movement keys',()=>{assert.equal(inputCode({code:'Unidentified',key:'Process'}),'');});
