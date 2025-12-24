
import { HttpAgent, type Message, type AgentSubscriber } from "@ag-ui/client";
import "../static/styles.css";

// Web Speech API types
interface SpeechRecognitionEvent extends Event {
  resultIndex: number;
  results: SpeechRecognitionResultList;
}

interface SpeechRecognitionResultList {
  length: number;
  item(index: number): SpeechRecognitionResult;
  [index: number]: SpeechRecognitionResult;
}

interface SpeechRecognitionResult {
  isFinal: boolean;
  length: number;
  item(index: number): SpeechRecognitionAlternative;
  [index: number]: SpeechRecognitionAlternative;
}

interface SpeechRecognitionAlternative {
  transcript: string;
  confidence: number;
}

interface SpeechRecognition extends EventTarget {
  continuous: boolean;
  interimResults: boolean;
  lang: string;
  onstart: ((this: SpeechRecognition, ev: Event) => void) | null;
  onend: ((this: SpeechRecognition, ev: Event) => void) | null;
  onerror: ((this: SpeechRecognition, ev: Event & { error: string }) => void) | null;
  onresult: ((this: SpeechRecognition, ev: SpeechRecognitionEvent) => void) | null;
  onspeechend: ((this: SpeechRecognition, ev: Event) => void) | null;
  start(): void;
  stop(): void;
  abort(): void;
}

declare global {
  interface Window {
    webkitSpeechRecognition: new () => SpeechRecognition;
    SpeechRecognition: new () => SpeechRecognition;
  }
}

new EventSource('http://localhost:8001/esbuild').addEventListener('change', () => {
  console.log("reloading");
  setTimeout(() => location.reload(), 100);
});

let messages: Message[] = [];
let currentAssistantMessage: HTMLElement | null = null;
let currentToolCall: HTMLElement | null = null;
let toolCallsMap: Record<
  string,
  { name: string; args: string; element: HTMLElement }
> = {};
let isProcessing = false;

// Web Components
function defineComponent(name: string) {
  customElements.define(name, class extends HTMLElement {
    connectedCallback() {
      const template = document.getElementById(`template-${name}`) as HTMLTemplateElement;
      const shadow = this.attachShadow({ mode: "open" });
      shadow.appendChild(template.content.cloneNode(true));
    }
  });
}

defineComponent("chat-container");
defineComponent("chat-messages");
defineComponent("chat-header");
defineComponent("chat-input-container");
defineComponent("attachments-container");
defineComponent("input-wrapper");
defineComponent("mic-button");
defineComponent("typing-indicator");

class ChatMessage extends HTMLElement {
  connectedCallback() {
    const template = document.getElementById("template-chat-message") as HTMLTemplateElement;
    const shadow = this.attachShadow({ mode: "open" });
    shadow.appendChild(template.content.cloneNode(true));
    const avatar = shadow.querySelector(".avatar")!;
    avatar.textContent = this.getAttribute("role") === "user" ? "U" : "A";
  }
}
customElements.define("chat-message", ChatMessage);

class CustomEventDisplay extends HTMLElement {
  connectedCallback() {
    const template = document.getElementById("template-custom-event") as HTMLTemplateElement;
    const shadow = this.attachShadow({ mode: "open" });
    shadow.appendChild(template.content.cloneNode(true));
    const nameEl = shadow.querySelector(".name")!;
    nameEl.textContent = this.getAttribute("name") || "";
  }
}
customElements.define("custom-event-display", CustomEventDisplay);

class AttachmentChip extends HTMLElement {
  connectedCallback() {
    const template = document.getElementById("template-attachment-chip") as HTMLTemplateElement;
    const shadow = this.attachShadow({ mode: "open" });
    shadow.appendChild(template.content.cloneNode(true));
    const filename = this.getAttribute("filename") || "";
    const nameEl = shadow.querySelector(".name")!;
    nameEl.textContent = filename;
    (nameEl as HTMLElement).title = filename;
    const removeBtn = shadow.querySelector(".remove")!;
    removeBtn.addEventListener("click", () => {
      this.dispatchEvent(new CustomEvent("remove", { detail: filename }));
    });
  }
}
customElements.define("attachment-chip", AttachmentChip);

class AttachmentPreview extends HTMLElement {
  connectedCallback() {
    const template = document.getElementById("template-attachment-preview") as HTMLTemplateElement;
    const shadow = this.attachShadow({ mode: "open" });
    shadow.appendChild(template.content.cloneNode(true));
    const filename = this.getAttribute("filename") || "";
    const nameEl = shadow.querySelector(".name") as HTMLElement;
    nameEl.textContent = `📎 ${filename}`;
    nameEl.title = filename;
    const iframe = shadow.querySelector("iframe")!;
    iframe.src = this.getAttribute("src") || "";
    iframe.title = filename;
    const header = shadow.querySelector(".header")!;
    header.addEventListener("click", () => {
      this.classList.toggle("expanded");
    });
  }
}
customElements.define("attachment-preview", AttachmentPreview);

defineComponent("tool-approval");

class ToolApprovalItem extends HTMLElement {
  connectedCallback() {
    const template = document.getElementById("template-tool-approval-item") as HTMLTemplateElement;
    const shadow = this.attachShadow({ mode: "open" });
    shadow.appendChild(template.content.cloneNode(true));

    const toolName = this.getAttribute("tool-name") || "";
    const args = this.getAttribute("args") || "";

    shadow.querySelector(".tool-name")!.textContent = `Tool: ${toolName}`;
    shadow.querySelector(".args")!.textContent = `Arguments: ${args}`;

    const approveBtn = shadow.querySelector(".approve")!;
    const rejectBtn = shadow.querySelector(".reject")!;

    approveBtn.addEventListener("click", () => {
      approveBtn.setAttribute("disabled", "true");
      rejectBtn.setAttribute("disabled", "true");
      this.classList.add("approved");
      this.dispatchEvent(new CustomEvent("approve"));
    });

    rejectBtn.addEventListener("click", () => {
      approveBtn.setAttribute("disabled", "true");
      rejectBtn.setAttribute("disabled", "true");
      this.classList.add("rejected");
      this.dispatchEvent(new CustomEvent("reject"));
    });
  }
}
customElements.define("tool-approval-item", ToolApprovalItem);

class ScrollAnchor extends HTMLElement {
  connectedCallback() {
    if (document.querySelectorAll("scroll-anchor").length > 1) {
      throw new Error("Only one scroll-anchor allowed in document");
    }
    this.style.fontSize = "1px";
  }
}
customElements.define("scroll-anchor", ScrollAnchor);

// Speech recognition state
let recognition: SpeechRecognition | null = null;
let isRecognizing = false;

function createRecognition(): SpeechRecognition {
  const SpeechRecognitionAPI = window.SpeechRecognition || window.webkitSpeechRecognition;
  const rec = new SpeechRecognitionAPI();
  rec.continuous = false;
  rec.interimResults = true;
  rec.lang = "en-US";

  rec.onstart = () => {
    console.log("[Speech] Recognition started");
    isRecognizing = true;
    updateMicButtonUI(true);
  };

  rec.onend = () => {
    console.log("[Speech] Recognition ended");
    isRecognizing = false;
    updateMicButtonUI(false);
  };

  rec.onerror = (event) => {
    console.error("[Speech] Recognition error:", event.error);
    isRecognizing = false;
    updateMicButtonUI(false);
  };

  rec.onresult = (event: SpeechRecognitionEvent) => {
    const input = document.getElementById("messageInput") as HTMLInputElement;
    let finalTranscript = "";
    let interimTranscript = "";

    for (let i = event.resultIndex; i < event.results.length; i++) {
      const transcript = event.results[i][0].transcript;
      if (event.results[i].isFinal) {
        finalTranscript += transcript;
      } else {
        interimTranscript += transcript;
      }
    }

    if (finalTranscript) {
      input.value = finalTranscript;
      console.log("[Speech] Final transcript:", finalTranscript);
    } else if (interimTranscript) {
      input.value = interimTranscript;
      console.log("[Speech] Interim transcript:", interimTranscript);
    }
  };

  rec.onspeechend = () => {
    console.log("[Speech] Speech ended");
    rec.stop();
  };

  return rec;
}

function updateMicButtonUI(recording: boolean): void {
  const micButton = document.getElementById("micButton");
  if (!micButton) return;

  if (recording) {
    micButton.classList.add("recording");
    micButton.title = "Stop speech recognition";
  } else {
    micButton.classList.remove("recording");
    micButton.title = "Start speech recognition";
  }
}

function startRecognition(): void {
  if (isRecognizing) {
    recognition?.stop();
    return;
  }

  if (!recognition) {
    recognition = createRecognition();
  }

  try {
    recognition.start();
  } catch (error) {
    console.error("[Speech] Failed to start recognition:", error);
  }
}

const agent = new HttpAgent({
  url: "/agent",
});


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

  const input = document.getElementById("messageInput") as HTMLInputElement;
  const sendButton = document.getElementById("sendButton") as HTMLButtonElement;

  const subscriber: AgentSubscriber = {
    onRunStartedEvent: (_params) => {
      console.log(`[Client] Run started${logPrefix}`);
    },

    onTextMessageStartEvent: (_params) => {
      console.log("[Client] Starting assistant message");
      removeTypingIndicator();
      currentAssistantMessage = addMessage("assistant", "");
    },

    onTextMessageContentEvent: (params) => {
      if (currentAssistantMessage && params.event.delta) {
        console.log("[Client] Adding delta:", params.event.delta);
        currentAssistantMessage.innerHTML += params.event.delta.replace(
          /\n/g,
          "<br>"
        );
        scrollToBottom();
      }
    },

    onTextMessageEndEvent: (params) => {
      console.log("[Client] Message ended");
      if (currentAssistantMessage) {
        messages.push({
          id: params.event.messageId,
          role: "assistant",
          content: currentAssistantMessage.textContent || "",
        });
      }
      currentAssistantMessage = null;
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
      const toolContent = `<div class="tool-call">🔧 Calling tool: ${params.event.toolCallName}</div><div class="tool-args" id="tool-args-${params.event.toolCallId}">Arguments: </div>`;
      currentToolCall = addToolMessage(toolContent);
      toolCallsMap[params.event.toolCallId] = {
        name: params.event.toolCallName,
        args: "",
        element: currentToolCall,
      };
    };

    subscriber.onToolCallArgsEvent = (params) => {
      const toolCallId = params.event.toolCallId;
      if (toolCallId in toolCallsMap && params.event.delta) {
        console.log("[Client] Tool call args delta:", params.event.delta);
        toolCallsMap[toolCallId].args += params.event.delta;
        const argsDiv = document.getElementById("tool-args-" + toolCallId);
        if (argsDiv) {
          argsDiv.textContent = "Arguments: " + toolCallsMap[toolCallId].args;
          scrollToBottom();
        }
      }
    };

    subscriber.onToolCallEndEvent = (params) => {
      console.log("[Client] Tool call ended:", params.event.toolCallId);
      currentToolCall = null;
    };

    subscriber.onToolCallResultEvent = (params) => {
      console.log("[Client] Tool call result:", params.event.toolCallId);
      const resultText = params.event.content || "No result";
      const resultContent = `<div class="tool-call">✅ Tool result</div><div class="tool-args">${resultText}</div>`;
      addToolMessage(resultContent, true);
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
        const spacer = document.getElementById("scroll-anchor")!;

        for (const [filename, dataUrl] of Object.entries(attachments)) {
          const preview = document.createElement("attachment-preview");
          preview.setAttribute("filename", filename);
          preview.setAttribute("src", dataUrl);
          messagesDiv.insertBefore(preview, spacer);
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
        const spacer = document.getElementById("scroll-anchor")!;
        messagesDiv.insertBefore(approvalContainer, spacer);
        scrollToBottom();

        return;
      }

      const eventEl = document.createElement("custom-event-display");
      eventEl.setAttribute("name", `📌 ${params.event.name}`);
      eventEl.textContent = typeof params.event.value === 'string' ? params.event.value : JSON.stringify(params.event.value, null, 2);
      const messagesDiv = document.getElementById("messages")!;
      const spacer = document.getElementById("scroll-anchor")!;
      messagesDiv.insertBefore(eventEl, spacer);
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
    const input = document.getElementById("messageInput") as HTMLInputElement;
    const sendButton = document.getElementById("sendButton") as HTMLButtonElement;
    isProcessing = false;
    sendButton.disabled = false;
    input.focus();
  }
}


function scrollToBottom(): void {
  const anchor = document.getElementById("scroll-anchor");
  if (anchor) {
    anchor.scrollIntoView({ behavior: "auto", block: "end" });
  }
}


function addMessage(role: "user" | "assistant", content: string): HTMLElement {
  const messagesDiv = document.getElementById("messages")!;
  const spacer = document.getElementById("scroll-anchor")!;
  const messageEl = document.createElement("chat-message");
  messageEl.setAttribute("role", role);
  messageEl.textContent = content;
  messagesDiv.insertBefore(messageEl, spacer);
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
  const spacer = document.getElementById("scroll-anchor")!;
  const errorDiv = document.createElement("div");
  errorDiv.className = "error-message";
  errorDiv.textContent = "Error: " + message;
  messagesDiv.insertBefore(errorDiv, spacer);
  scrollToBottom();
}


function addToolMessage(
  content: string,
  isResult: boolean = false
): HTMLElement {
  const messagesDiv = document.getElementById("messages")!;
  const spacer = document.getElementById("scroll-anchor")!;
  const toolDiv = document.createElement("div");
  toolDiv.className = isResult ? "tool-message tool-result" : "tool-message";
  toolDiv.innerHTML = content;
  messagesDiv.insertBefore(toolDiv, spacer);
  scrollToBottom();
  return toolDiv;
}


async function sendMessage(): Promise<void> {
  const input = document.getElementById("messageInput") as HTMLInputElement;
  const sendButton = document.getElementById("sendButton") as HTMLButtonElement;
  const messageText = input.value.trim();

  if (!messageText || isProcessing) return;

  console.log("[Client] Sending message:", messageText);
  isProcessing = true;
  sendButton.disabled = true;
  input.value = "";

  addMessage("user", messageText);
  messages.push({
    id: crypto.randomUUID(),
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
    showError(error.message || "Failed to send message");
    isProcessing = false;
    sendButton.disabled = false;
    input.focus();
  }
}


function handleKeyPress(event: KeyboardEvent): void {
  if (event.key === "Enter" && !event.shiftKey) {
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


document.addEventListener("DOMContentLoaded", () => {
  const messageInput = document.getElementById("messageInput") as HTMLInputElement;
  const sendButton = document.getElementById("sendButton") as HTMLButtonElement;
  const attachButton = document.getElementById("attachButton") as HTMLButtonElement;
  const fileInput = document.getElementById("fileInput") as HTMLInputElement;
  const micButton = document.getElementById("micButton") as HTMLElement;

  messageInput.addEventListener("keypress", handleKeyPress);
  sendButton.addEventListener("click", sendMessage);

  attachButton.addEventListener("click", () => {
    fileInput.click();
  });
  fileInput.addEventListener("change", handleFileSelect);

  // Speech recognition button - only show if supported
  if (window.SpeechRecognition || window.webkitSpeechRecognition) {
    micButton.addEventListener("click", startRecognition);
  } else {
    micButton.style.display = "none";
  }

  messageInput.focus();
});
