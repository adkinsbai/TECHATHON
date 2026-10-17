import type { ActionName, Interaction } from '../types';

export function selectAction(event: Interaction): ActionName {
  if (!Number.isFinite(event.intensity) || event.intensity < 0 || event.intensity > 1) throw new Error('互动强度必须在 0 到 1 之间。');
  if (event.type === 'motion') return 'react_to_shake';
  if (event.type === 'speech') return event.gesture === 'greet' ? 'greet' : 'listen';
  if (event.region === 'head') return 'enjoy_head_pat';
  if (event.gesture === 'hug') return 'hug';
  return 'greet';
}

export function makeInteraction(action: ActionName, intensity: number): Interaction {
  return {
    type: action === 'react_to_shake' ? 'motion' : ['greet', 'listen'].includes(action) ? 'speech' : 'touch',
    region: action === 'enjoy_head_pat' ? 'head' : 'body',
    gesture: ({ idle: 'rest', greet: 'greet', enjoy_head_pat: 'stroke', hug: 'hug', react_to_shake: 'shake', listen: 'talk' })[action],
    intensity, source: 'simulator', timestamp: new Date().toISOString()
  };
}
