
import { HttpAgent, type Message, type AgentSubscriber } from "@ag-ui/client";
import { marked } from "marked";
import { v4 as uuidv4 } from "uuid";
import { initSpeechRecognition } from "./speech";
import type { ToolCall, SendButton, MessageInput, ToolToggles, ToolForm } from "./components/elements";

import AttachButton from "./components/attach-button.sfc.html";
import AttachmentChip from "./components/attachment-chip.sfc.html";
import AttachmentPreview from "./components/attachment-preview.sfc.html";
import AttachmentsContainer from "./components/attachments-container.sfc.html";
import ChatContainer from "./components/chat-container.sfc.html";
import ChatHeader from "./components/chat-header.sfc.html";
import ChatInputContainer from "./components/chat-input-container.sfc.html";
import ChatMessage from "./components/chat-message.sfc.html";
import ChatMessages from "./components/chat-messages.sfc.html";
import CustomEventDisplay from "./components/custom-event-display.sfc.html";
import DebugMessage from "./components/debug-message.sfc.html";
import ErrorMessage from "./components/error-message.sfc.html";
import MessageInputComponent from "./components/message-input.sfc.html";
import MicButton from "./components/mic-button.sfc.html";
import PingIndicator from "./components/ping-indicator.sfc.html";
import ScrollAnchor from "./components/scroll-anchor.sfc.html";
import SendButtonComponent from "./components/send-button.sfc.html";
import ToolApproval from "./components/tool-approval.sfc.html";
import ToolApprovalItem from "./components/tool-approval-item.sfc.html";
import ToolCallComponent from "./components/tool-call.sfc.html";
import ToolFormComponent from "./components/tool-form.sfc.html";
import ToolResult from "./components/tool-result.sfc.html";
import ToolTogglesComponent from "./components/tool-toggles.sfc.html";
import TypingIndicator from "./components/typing-indicator.sfc.html";

customElements.define("attach-button", AttachButton);
customElements.define("attachment-chip", AttachmentChip);
customElements.define("attachment-preview", AttachmentPreview);
customElements.define("attachments-container", AttachmentsContainer);
customElements.define("chat-container", ChatContainer);
customElements.define("chat-header", ChatHeader);
customElements.define("chat-input-container", ChatInputContainer);
customElements.define("chat-message", ChatMessage);
customElements.define("chat-messages", ChatMessages);
customElements.define("custom-event-display", CustomEventDisplay);
customElements.define("debug-message", DebugMessage);
customElements.define("error-message", ErrorMessage);
customElements.define("message-input", MessageInputComponent);
customElements.define("mic-button", MicButton);
customElements.define("ping-indicator", PingIndicator);
customElements.define("scroll-anchor", ScrollAnchor);
customElements.define("send-button", SendButtonComponent);
customElements.define("tool-approval", ToolApproval);
customElements.define("tool-approval-item", ToolApprovalItem);
customElements.define("tool-call", ToolCallComponent);
customElements.define("tool-form", ToolFormComponent);
customElements.define("tool-result", ToolResult);
customElements.define("tool-toggles", ToolTogglesComponent);
customElements.define("typing-indicator", TypingIndicator);


const DEBUG = false;

function debugLog(message: string): void {
  if (!DEBUG) return;
  const messagesDiv = document.getElementById("messages");
  if (!messagesDiv) {
    console.log("[DEBUG]", message);
    return;
  }

  const debugEl = document.createElement("debug-message");
  debugEl.textContent = message;
  messagesDiv.appendChild(debugEl);
  scrollToBottom();
}


const messages: Message[] = [];
let currentAssistantMessage: HTMLElement | null = null;
let currentAssistantRawText = "";
const toolCallsMap: Record<string, ToolCall> = {};
let currentToolCall: ToolCall | null = null;
let isProcessing = false;
let streamingScrollInterval: ReturnType<typeof setInterval> | null = null;
let shouldStreamScroll = false;

let agent: HttpAgent;


async function connectToEvents(): Promise<{ agentUrl: string; availableTools: { name: string; description: string }[] }> {
  const response = await fetch("/events", { method: "POST" });
  if (!response.ok) {
    throw new Error(`Failed to connect to events: ${response.status}`);
  }

  const reader = response.body!.getReader();
  const decoder = new TextDecoder();

  // Read the first event to get the agent URL
  let buffer = "";
  while (true) {
    const { value, done } = await reader.read();
    if (done) throw new Error("Events stream closed before receiving agent URL");

    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split("\n");

    for (const line of lines) {
      if (line.startsWith("data: ")) {
        const data = JSON.parse(line.slice(6));
        if (data.agent) {
          // Start listening for pings in background
          listenForPings(reader, decoder, buffer.slice(buffer.indexOf("\n\n") + 2));
          return { agentUrl: data.agent, availableTools: data.available_tools || [] };
        }
      }
    }
  }
}


function listenForPings(
  reader: ReadableStreamDefaultReader<Uint8Array>,
  decoder: TextDecoder,
  initialBuffer: string
): void {
  let buffer = initialBuffer;

  async function processStream() {
    try {
      while (true) {
        const { value, done } = await reader.read();
        if (done) {
          console.log("[Client] Events stream closed");
          break;
        }

        buffer += decoder.decode(value, { stream: true });

        // Process complete SSE messages
        let newlineIndex;
        while ((newlineIndex = buffer.indexOf("\n\n")) !== -1) {
          const message = buffer.slice(0, newlineIndex);
          buffer = buffer.slice(newlineIndex + 2);

          if (message.startsWith("data: ")) {
            const data = JSON.parse(message.slice(6));
            if (data.ping) {
              addPingIndicator();
            }
          }
        }
      }
    } catch (error) {
      console.error("[Client] Error reading events stream:", error);
    }
  }

  processStream();
}


function addPingIndicator(): void {
  const pingEl = document.getElementById("pingIndicator") as any;
  if (pingEl?.ping) pingEl.ping();
}


interface SubscriberOptions {
  logPrefix?: string;
  onFinished?: () => void;
  includeToolCallHandlers?: boolean;
  includeCustomEventHandler?: boolean;
}


function createSubscriber(options: SubscriberOptions = {}): AgentSubscriber {
  const {
    logPrefix = "",
    onFinished,
    includeToolCallHandlers = true,
    includeCustomEventHandler = true,
  } = options;

  const input = document.getElementById("messageInput") as MessageInput;
  const sendButton = document.getElementById("sendButton") as SendButton;

  const subscriber: AgentSubscriber = {
    onRunStartedEvent: (_params) => {
      console.log(`[Client] Run started${logPrefix}`);
    },

    onTextMessageStartEvent: (_params) => {
      console.log("[Client] Starting assistant message");
      removeTypingIndicator();
      shouldStreamScroll = isNearBottom();
      currentAssistantMessage = addMessage("assistant", "");
      currentAssistantRawText = "";
      if (shouldStreamScroll) {
        streamingScrollInterval = setInterval(() => {
          if (shouldStreamScroll) forceScrollToBottom();
        }, 1000);
      }
    },

    onTextMessageContentEvent: (params) => {
      if (currentAssistantMessage && params.event.delta) {
        currentAssistantRawText += params.event.delta;
        currentAssistantMessage.innerHTML = marked.parse(currentAssistantRawText, { async: false }) as string;
      }
    },

    onTextMessageEndEvent: (params) => {
      console.log("[Client] Message ended");
      if (streamingScrollInterval) {
        clearInterval(streamingScrollInterval);
        streamingScrollInterval = null;
      }
      if (currentAssistantMessage) {
        messages.push({
          id: params.event.messageId,
          role: "assistant",
          content: currentAssistantRawText,
        });
      }
      if (shouldStreamScroll) forceScrollToBottom();
      shouldStreamScroll = false;
      currentAssistantMessage = null;
      currentAssistantRawText = "";
    },

    onRunErrorEvent: (params) => {
      console.error("[Client] Run error:", params.event);
      showError(
        `Agent error: ${params.event.message || "Unknown error occurred"}`
      );
      isProcessing = false;
      sendButton.disabled = false;
      input.focus();
    },

    onRunFinishedEvent: (_params) => {
      console.log(`[Client] Run finished${logPrefix}`);
      removeTypingIndicator();
      isProcessing = false;
      sendButton.disabled = false;
      input.focus();
      // Clear attachments from state after successful send
      if (agent.state?.attachments) {
        agent.state.attachments = {};
      }
      renderAttachmentChips();
      onFinished?.();
    },
  };

  if (includeToolCallHandlers) {
    subscriber.onToolCallStartEvent = (params) => {
      console.log("[Client] Tool call started:", params.event.toolCallName);
      const messagesDiv = document.getElementById("messages")!;
    
      const toolCall = document.createElement("tool-call");
      toolCall.setAttribute("name", params.event.toolCallName);
      messagesDiv.appendChild(toolCall);
      scrollToBottom();
      currentToolCall = toolCall;
      toolCallsMap[params.event.toolCallId] = toolCall;
    };

    subscriber.onToolCallArgsEvent = (params) => {
      const toolCallId = params.event.toolCallId;
      if (toolCallId in toolCallsMap && params.event.delta) {
        console.log("[Client] Tool call args delta:", params.event.delta);
        toolCallsMap[toolCallId].appendArgs(params.event.delta);
        scrollToBottom();
      }
    };

    subscriber.onToolCallEndEvent = (params) => {
      console.log("[Client] Tool call ended:", params.event.toolCallId);
      currentToolCall = null;
    };

    subscriber.onToolCallResultEvent = (params) => {
      console.log("[Client] Tool call result:", params.event.toolCallId);
      const messagesDiv = document.getElementById("messages")!;
    
      const toolResult = document.createElement("tool-result");
      toolResult.setAttribute("content", params.event.content || "No result");
      messagesDiv.appendChild(toolResult);
      scrollToBottom();
    };

    subscriber.onStepStartedEvent = (params) => {
      console.log("[Client] Step started:", params.event.stepName);
    };

    subscriber.onStepFinishedEvent = (_params) => {
      console.log("[Client] Step finished");
    };
  }

  if (includeCustomEventHandler) {
    subscriber.onCustomEvent = (params) => {
      console.log("[Client] Custom event:", params.event);

      // Handle instructions event - insert at the beginning (before user message)
      if (params.event.name === "instructions") {
        const eventEl = document.createElement("custom-event-display");
        eventEl.setAttribute("name", `📜 ${params.event.name}`);
        eventEl.textContent = typeof params.event.value === 'string' ? params.event.value : JSON.stringify(params.event.value, null, 2);
        const messagesDiv = document.getElementById("messages")!;
        messagesDiv.insertBefore(eventEl, messagesDiv.firstChild);
        scrollToBottom();
        return;
      }

      // Handle attachments event - render expanding sections with iframe previews
      if (params.event.name === "attachments") {
        const attachments = params.event.value as Record<string, string>;
        if (!attachments || Object.keys(attachments).length === 0) {
          return;
        }

        const messagesDiv = document.getElementById("messages")!;
      

        for (const [filename, dataUrl] of Object.entries(attachments)) {
          const preview = document.createElement("attachment-preview");
          preview.setAttribute("filename", filename);
          preview.setAttribute("src", dataUrl);
          messagesDiv.appendChild(preview);
        }

        scrollToBottom();
        return;
      }

      if (params.event.name === "deferred_tool_requests") {
        if (!params.event.value || Object.keys(params.event.value).length === 0) {
          return;
        }

        removeTypingIndicator();

        const approvalContainer = document.createElement("tool-approval");
        const approvals: Record<string, boolean> = {};
        const totalTools = Object.keys(params.event.value as Record<string, any>).length;
        let approvedCount = 0;

        for (const [callId, callInfo] of Object.entries(params.event.value as Record<string, any>)) {
          const args = typeof callInfo.args === 'string' ? callInfo.args : JSON.stringify(callInfo.args);
          const item = document.createElement("tool-approval-item");
          item.setAttribute("tool-name", callInfo.tool_name);
          item.setAttribute("args", args);

          item.addEventListener("approve", async () => {
            approvals[callId] = true;
            approvedCount++;
            if (approvedCount === totalTools) {
              await continueWithApprovals(approvals);
            }
          });

          item.addEventListener("reject", async () => {
            approvals[callId] = false;
            approvedCount++;
            if (approvedCount === totalTools) {
              await continueWithApprovals(approvals);
            }
          });

          approvalContainer.appendChild(item);
        }

        const messagesDiv = document.getElementById("messages")!;
      
        messagesDiv.appendChild(approvalContainer);
        scrollToBottom();

        return;
      }

      const eventEl = document.createElement("custom-event-display");
      eventEl.setAttribute("name", `📌 ${params.event.name}`);
      eventEl.textContent = typeof params.event.value === 'string' ? params.event.value : JSON.stringify(params.event.value, null, 2);
      const messagesDiv = document.getElementById("messages")!;
    
      messagesDiv.appendChild(eventEl);
      scrollToBottom();
    };
  }

  return subscriber;
}


async function continueWithApprovals(approvals: Record<string, boolean>): Promise<void> {
  console.log("All tools processed, approvals:", approvals);

  if (!agent.state) {
    agent.state = {};
  }
  agent.state.deferred_tool_approvals = approvals;

  addTypingIndicator();

  try {
    await agent.runAgent({}, createSubscriber({
      logPrefix: " (with approvals)",
      onFinished: () => {
        delete agent.state!.deferred_tool_approvals;
      },
    }));
  } catch (error: any) {
    console.error("[Client] Error continuing with approvals:", error);
    showError(error.message || "Failed to continue with approvals");
    const input = document.getElementById("messageInput") as MessageInput;
    const sendButton = document.getElementById("sendButton") as SendButton;
    isProcessing = false;
    sendButton.disabled = false;
    input.focus();
  }
}


function isNearBottom(): boolean {
  const threshold = 150;
  return (window.innerHeight + window.scrollY) >= (document.body.scrollHeight - threshold);
}

function forceScrollToBottom(): void {
  const anchor = document.getElementById("scroll-anchor");
  if (anchor) {
    anchor.scrollIntoView({ behavior: "auto", block: "end" });
  }
}

function scrollToBottom(): void {
  if (!isNearBottom()) return;
  forceScrollToBottom();
}


function addMessage(role: "user" | "assistant", content: string): HTMLElement {
  const messagesDiv = document.getElementById("messages")!;

  const messageEl = document.createElement("chat-message");
  messageEl.setAttribute("role", role);
  messageEl.textContent = content;
  messagesDiv.appendChild(messageEl);
  scrollToBottom();
  return messageEl;
}


function addTypingIndicator(): void {
  const messagesDiv = document.getElementById("messages")!;
  const indicator = document.createElement("typing-indicator");
  indicator.id = "typing-indicator";
  messagesDiv.appendChild(indicator);
  scrollToBottom();
}


function removeTypingIndicator(): void {
  const indicator = document.getElementById("typing-indicator");
  if (indicator) {
    indicator.remove();
  }
}


function showError(message: string): void {
  const messagesDiv = document.getElementById("messages")!;

  const errorEl = document.createElement("error-message");
  errorEl.textContent = "Error: " + message;
  messagesDiv.appendChild(errorEl);
  scrollToBottom();
}



async function sendMessage(): Promise<void> {
  debugLog("sendMessage() called");

  const input = document.getElementById("messageInput") as MessageInput;
  const sendButton = document.getElementById("sendButton") as SendButton;
  const messageText = input.value.trim();

  if (!messageText || isProcessing) return;

  console.log("[Client] Sending message:", messageText);
  isProcessing = true;
  sendButton.disabled = true;
  input.value = "";

  addMessage("user", messageText);
  messages.push({
    id: uuidv4(),
    role: "user",
    content: messageText,
  });

  addTypingIndicator();

  try {
    agent.messages = messages;

    await agent.runAgent({}, createSubscriber());
  } catch (error: any) {
    console.error("[Client] Error in sendMessage:", error);
    removeTypingIndicator();
    const errorMsg = error?.message || String(error) || "Unknown error";
    const errorStack = error?.stack ? `\n${error.stack}` : "";
    showError(`sendMessage error: ${errorMsg}${errorStack}`);
    isProcessing = false;
    sendButton.disabled = false;
    input.focus();
  }
}


function handleKeyPress(event: KeyboardEvent): void {
  if (event.key === "Enter" && !event.shiftKey) {
    debugLog("Enter key pressed");
    event.preventDefault();
    sendMessage();
  }
}


function renderAttachmentChips(): void {
  const container = document.getElementById("attachments-container")!;
  container.innerHTML = "";

  const attachments = agent.state?.attachments as Record<string, string> | undefined;
  if (!attachments || Object.keys(attachments).length === 0) return;

  for (const filename of Object.keys(attachments)) {
    const chip = document.createElement("attachment-chip");
    chip.setAttribute("filename", filename);
    chip.addEventListener("remove", () => removeAttachment(filename));
    container.appendChild(chip);
  }
}


function removeAttachment(filename: string): void {
  const attachments = agent.state?.attachments as Record<string, string> | undefined;
  if (attachments) {
    delete attachments[filename];
    console.log(`[Client] Removed attachment: ${filename}`);
    renderAttachmentChips();
  }
}


function handleFileSelect(event: Event): void {
  const fileInput = event.target as HTMLInputElement;
  const file = fileInput.files?.[0];
  if (!file) return;

  const reader = new FileReader();
  reader.onload = () => {
    const dataUrl = reader.result as string;

    if (!agent.state) {
      agent.state = {};
    }
    if (!agent.state.attachments) {
      agent.state.attachments = {} as Record<string, string>;
    }

    agent.state.attachments[file.name] = dataUrl;
    console.log(`[Client] Attached file: ${file.name}`);
    renderAttachmentChips();

    // Reset file input so the same file can be selected again
    fileInput.value = "";
  };

  reader.onerror = () => {
    console.error("[Client] Error reading file:", reader.error);
    showError("Failed to read file");
  };

  reader.readAsDataURL(file);
}


document.addEventListener("DOMContentLoaded", async () => {
  const messageInput = document.getElementById("messageInput") as MessageInput;
  const sendButton = document.getElementById("sendButton") as SendButton;
  const attachButton = document.getElementById("attachButton") as HTMLElement;
  const fileInput = document.getElementById("fileInput") as HTMLInputElement;
  const micButton = document.getElementById("micButton") as HTMLElement;

  // Connect to events endpoint first to get agent URL
  try {
    const { agentUrl, availableTools } = await connectToEvents();
    console.log("[Client] Connected to events, agent URL:", agentUrl);

    // Debug: show full agent URL in the chat
    const fullAgentUrl = new URL(agentUrl, window.location.origin).href;
    debugLog(`Agent URL: ${agentUrl}\nFull URL: ${fullAgentUrl}\nwindow.location: ${window.location.href}`);

    agent = new HttpAgent({
      url: fullAgentUrl,
    });

    // Set up tool toggles
    const toolToggles = document.getElementById("toolToggles") as ToolToggles;
    if (availableTools.length > 0) {
      toolToggles.setTools(availableTools as any);
      toolToggles.addEventListener("tools-changed", ((e: CustomEvent) => {
        if (!agent.state) agent.state = {};
        agent.state.disabled_tools = e.detail.disabledTools;
        console.log("[Client] Disabled tools:", e.detail.disabledTools);
      }) as EventListener);
      toolToggles.addEventListener("tool-invoke", ((e: CustomEvent) => {
        const { name, a2ui } = e.detail;
        const messagesDiv = document.getElementById("messages")!;
      
        const form = document.createElement("tool-form");
        messagesDiv.appendChild(form);
        form.setA2UI(name, a2ui);
        form.addEventListener("tool-submit", (async (se: CustomEvent) => {
          form.remove();
          if (!agent.state) agent.state = {};
          agent.state.manual_tool_call = { name: se.detail.toolName, args: se.detail.args };
          addTypingIndicator();
          try {
            await agent.runAgent({}, createSubscriber({
              logPrefix: " (manual tool)",
              onFinished: () => {
                delete agent.state!.manual_tool_call;
              },
            }));
          } catch (error: any) {
            removeTypingIndicator();
            showError(error.message || "Failed to invoke tool");
          }
        }) as unknown as EventListener);
        scrollToBottom();
      }) as EventListener);
    } else {
      toolToggles.style.display = "none";
    }
  } catch (error: any) {
    console.error("[Client] Failed to connect to events:", error);
    showError(`Failed to connect to server: ${error?.message || error}`);
    return;
  }

  messageInput.addEventListener("keypress", handleKeyPress);
  sendButton.addEventListener("click", sendMessage);

  attachButton.addEventListener("click", () => {
    fileInput.click();
  });
  fileInput.addEventListener("change", handleFileSelect);

  initSpeechRecognition(messageInput, micButton);

  messageInput.focus();

  // Expose test function to console for debugging
  (window as any).testError = () => showError("This is a test error message");

  // Global error handlers to show errors in the UI
  window.onerror = (message, source, lineno, colno, error) => {
    showError(`Global error: ${message}\nSource: ${source}:${lineno}:${colno}\n${error?.stack || ''}`);
    return false;
  };

  window.onunhandledrejection = (event) => {
    const error = event.reason;
    const errorMsg = error?.message || String(error) || "Unknown promise rejection";
    const errorStack = error?.stack || "";
    showError(`Unhandled rejection: ${errorMsg}\n${errorStack}`);
  };
});
