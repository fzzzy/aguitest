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

declare global {
  interface HTMLElementTagNameMap {
    'tool-call': ToolCall;
    'send-button': SendButton;
    'message-input': MessageInput;
  }
}
