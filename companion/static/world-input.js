// Embedded browsers and IMEs can deliver an empty or Unidentified `code`.
// Keep physical-key controls and a key-name fallback, independent of focus UI.
const aliases={w:'KeyW',a:'KeyA',s:'KeyS',d:'KeyD',e:'KeyE',f:'KeyF',h:'KeyH',v:'KeyV',
  ' ':'Space',spacebar:'Space',escape:'Escape',esc:'Escape',shift:'ShiftLeft',
  arrowup:'ArrowUp',arrowdown:'ArrowDown',arrowleft:'ArrowLeft',arrowright:'ArrowRight'};
export function inputCode(event){
  if(event.code&&event.code!=='Unidentified')return event.code;
  return aliases[String(event.key||'').toLowerCase()]||'';
}
