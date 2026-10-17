import test from 'node:test';
import assert from 'node:assert/strict';
import { buildGenerationForm, migrateGenerationPrompt, referenceSignature } from '../src/lib/generation-input.ts';

const image = () => new File(['reference-bytes'], 'reference.png', { type: 'image/png' });
test('style is forwarded and changing it invalidates the confirmed reference, while old preserve signatures remain compatible', () => {
  assert.equal(buildGenerationForm('rabbit', [], true, 'plush').get('style'), 'plush');
  assert.notEqual(referenceSignature('rabbit', [], true, 'plush'), referenceSignature('rabbit', [], true, 'clay'));
  assert.equal(referenceSignature('rabbit', [], true), JSON.stringify({ prompt: 'rabbit', images: [], taPose: true }));
});

test('empty and whitespace-only inputs cannot create a generation request', () => {
  assert.throws(() => buildGenerationForm('', [], true), /至少/);
  assert.throws(() => buildGenerationForm(' \n ', [], true), /至少/);
});
test('text alone is valid and does not accidentally send image fields', () => {
  const form = buildGenerationForm('  a little capybara  ', [], false);
  assert.equal(form.get('prompt'), 'a little capybara');
  assert.equal(form.getAll('images').length, 0);
  assert.equal(form.get('TAPose'), 'false');
});
test('image alone is valid and does not inject the old default character description', () => {
  const form = buildGenerationForm('  ', [image()], true);
  assert.equal(form.has('prompt'), false);
  assert.equal(form.getAll('images').length, 1);
});
test('mixed input preserves the exact entered guidance and the reference image', async () => {
  const text = '保留水豚的外形，穿热带衬衫与沙滩裤，戴墨镜。';
  const form = buildGenerationForm(text, [image()], true);
  assert.equal(form.get('prompt'), text);
  assert.equal(await form.get('images').text(), 'reference-bytes');
  assert.equal(form.get('images').name, 'reference.png');
});
test('merged legacy drafts are preserved and deduplicated instead of dropping a modality prompt', () => {
  assert.equal(migrateGenerationPrompt({ description: '水豚', referencePrompt: '穿沙滩装' }), '水豚\n\n穿沙滩装');
  assert.equal(migrateGenerationPrompt({ description: '水豚', referencePrompt: '水豚' }), '水豚');
  assert.equal(migrateGenerationPrompt(null), '');
});
test('cleared unified input stays empty and cannot resurrect the removed reference-only field', () => {
  assert.equal(migrateGenerationPrompt({ inputVersion: 2, description: '', referencePrompt: 'stale text' }), '');
});
test('oversize merged drafts are not truncated silently, but must be edited before submission', () => {
  const text = migrateGenerationPrompt({ description: 'a'.repeat(600), referencePrompt: 'b'.repeat(600) });
  assert.equal(text.length, 1202);
  assert.throws(() => buildGenerationForm(text, [], true), /1024/);
});
