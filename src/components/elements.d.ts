export interface ToolCall extends HTMLElement {
  appendArgs(delta: string): void;
}

export interface SendButton extends HTMLElement {
  disabled: boolean;
}

export interface MessageInput extends HTMLElement {
  value: string;
  focus(): void;
}

export interface ToolToggles extends HTMLElement {
  setTools(tools: { name: string; description: string; a2ui: any[] }[]): void;
  getDisabledTools(): string[];
}

export interface ToolForm extends HTMLElement {
  setA2UI(toolName: string, messages: any[]): void;
}

declare global {
  interface HTMLElementTagNameMap {
    'tool-call': ToolCall;
    'send-button': SendButton;
    'message-input': MessageInput;

    'tool-toggles': ToolToggles;
    'tool-form': ToolForm;
  }
}
