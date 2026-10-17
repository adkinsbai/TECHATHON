/** One input contract shared by the form and its regression tests. */
export function buildGenerationForm(prompt: string, images: File[], taPose: boolean, style = 'preserve'): FormData {
  const text = prompt.trim();
  if (!text && images.length === 0) throw new Error('请至少填写文字描述或上传一张参考图，也可以同时提供两者。');
  if (text.length > 1024) throw new Error('文字描述不能超过 1024 个字符。');
  if (images.length > 5) throw new Error('最多上传 5 张参考图。');
  const form = new FormData();
  if (text) form.set('prompt', text);
  for (const image of images) form.append('images', image, image.name);
  form.set('TAPose', String(taPose));
  form.set('style', style);
  return form;
}

export function migrateGenerationPrompt(saved: { inputVersion?: number; description?: string; referencePrompt?: string } | null): string {
  if (!saved) return '';
  if (saved.inputVersion === 2) return saved.description || '';
  const previousDemo = '一只住在森林里的薄荷绿小伙伴，圆圆的脑袋，柔软的长耳朵，穿着奶油色的小围兜。性格温柔，好奇，喜欢被摸摸头。';
  const parts = [saved.description || '', saved.referencePrompt || ''].map(s => s.trim()).filter(s => s && s !== previousDemo);
  // Preserve both legacy drafts without silently discarding or truncating user text.
  return [...new Set(parts)].join('\n\n');
}

export function referenceSignature(prompt: string, images: File[], taPose: boolean, style = 'preserve'): string {
  return JSON.stringify({ prompt: prompt.trim(), images: images.map(file => [file.name, file.size, file.lastModified]), taPose, ...(style === 'preserve' ? {} : { style }) });
}
