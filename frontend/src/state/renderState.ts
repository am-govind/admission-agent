import { applyPatch, type Operation } from 'fast-json-patch';
import type { RenderState } from '../types';

export function emptyRenderState(): RenderState {
  return { parts: [], contentBlocks: {} };
}

/** Apply one parsed SSE event to a renderState, returning a new object. */
export function reduceEvent(state: RenderState, evt: any): RenderState {
  const next: RenderState = {
    parts: [...state.parts],
    contentBlocks: { ...state.contentBlocks },
  };

  switch (evt.type) {
    case 'text-message-start': {
      if (!next.parts.find((p) => p.type === 'text' && p.id === evt.partId)) {
        next.parts.push({ type: 'text', id: evt.partId, content: '' });
      }
      return next;
    }
    case 'text-message-content': {
      next.parts = next.parts.map((p) =>
        p.type === 'text' && p.id === evt.partId
          ? { ...p, content: p.content + (evt.delta ?? '') }
          : p,
      );
      return next;
    }
    case 'state-delta': {
      // RFC-6902 JSON Patch applied to the root of renderState.
      const doc = applyPatch(
        { parts: next.parts, contentBlocks: next.contentBlocks },
        evt.delta as Operation[],
        false,
        false,
      ).newDocument as RenderState;
      return { parts: doc.parts, contentBlocks: doc.contentBlocks };
    }
    default:
      return next;
  }
}
