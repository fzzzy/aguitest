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

export interface PingIndicator extends HTMLElement {}

declare global {
  interface HTMLElementTagNameMap {
    'tool-call': ToolCall;
    'send-button': SendButton;
    'message-input': MessageInput;
    'ping-indicator': PingIndicator;
  }
}
