export type ContentBlock =
  | { id: string; type: 'text'; data: { text: string }; annotations?: Record<string, unknown> }
  | { id: string; type: 'table'; data: { columns: string[]; rows: (string | number)[][] }; annotations?: Record<string, unknown> }
  | { id: string; type: 'image'; data: { url: string; alt?: string }; annotations?: Record<string, unknown> }
  | { id: string; type: 'code'; data: { language: string; text: string }; annotations?: Record<string, unknown> }
  | {
      id: string;
      type: 'chart';
      data: {
        kind: 'bar' | 'line' | 'area' | 'pie';
        x: string;
        y: string[];
        title?: string;
        rows: Record<string, string | number>[];
      };
      annotations?: Record<string, unknown>;
    };

export type RenderPart =
  | { type: 'text'; id: string; content: string }
  | { type: 'block-ref'; id: string };

export interface RenderState {
  parts: RenderPart[];
  contentBlocks: Record<string, ContentBlock>;
}

export interface ChatMessage {
  id: string;
  role: 'user' | 'assistant';
  // For assistant messages, content is a live renderState; for user messages, plain text.
  text?: string;
  renderState?: RenderState;
  loading?: boolean;
  loadingMessage?: string;
  error?: string;
  // The question that produced this answer, so it can be retried from the message itself.
  prompt?: string;
}

export interface Conversation {
  conversationId: string;
  title: string;
  createdAt: string;
  updatedAt: string;
  messageCount: number;
}

export interface TranscriptMessage {
  role: 'user' | 'assistant';
  content: string;
  renderState: RenderState | null;
  createdAt: string;
}

export interface ConversationDetail {
  conversationId: string;
  title: string;
  createdAt: string;
  updatedAt: string;
  messages: TranscriptMessage[];
}
