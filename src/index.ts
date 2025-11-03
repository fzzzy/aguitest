// AG-UI Chat Frontend using @ag-ui/client HttpAgent
import { HttpAgent, type Message } from "@ag-ui/client";

// State
let messages: Message[] = [];
let currentAssistantMessage: HTMLElement | null = null;
let currentToolCall: HTMLElement | null = null;
let toolCallsMap: Record<
  string,
  { name: string; args: string; element: HTMLElement }
> = {};
let isProcessing = false;

const agent = new HttpAgent({
  url: "/agent",
});

function scrollToBottom(): void {
  const anchor = document.getElementById("scroll-anchor");
  if (anchor) {
    anchor.scrollIntoView({ behavior: "auto", block: "end" });
  }
}

function addMessage(role: "user" | "assistant", content: string): HTMLElement {
  const messagesDiv = document.getElementById("messages")!;
  const spacer = document.getElementById("scroll-anchor")!;
  const messageDiv = document.createElement("div");
  messageDiv.className = `message ${role}`;

  const avatar = document.createElement("div");
  avatar.className = "message-avatar";
  avatar.textContent = role === "user" ? "U" : "A";

  const contentDiv = document.createElement("div");
  contentDiv.className = "message-content";
  contentDiv.textContent = content;

  messageDiv.appendChild(avatar);
  messageDiv.appendChild(contentDiv);
  messagesDiv.insertBefore(messageDiv, spacer);
  scrollToBottom();

  return contentDiv;
}

function addTypingIndicator(): void {
  const messagesDiv = document.getElementById("messages")!;
  const spacer = document.getElementById("scroll-anchor")!;
  const messageDiv = document.createElement("div");
  messageDiv.className = "message assistant";
  messageDiv.id = "typing-indicator";

  const avatar = document.createElement("div");
  avatar.className = "message-avatar";
  avatar.textContent = "A";

  const typingDiv = document.createElement("div");
  typingDiv.className = "message-content";
  typingDiv.innerHTML =
    '<div class="typing-indicator"><span></span><span></span><span></span></div>';

  messageDiv.appendChild(avatar);
  messageDiv.appendChild(typingDiv);
  messagesDiv.insertBefore(messageDiv, spacer);
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

  // Add user message to UI and state
  addMessage("user", messageText);
  messages.push({
    id: crypto.randomUUID(),
    role: "user",
    content: messageText,
  });

  addTypingIndicator();

  try {
    // Subscribe to agent events
    const unsubscribe = agent.subscribe({
      onRunStartedEvent: (_params) => {
        console.log("[Client] Run started");
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
          // Store the complete message
          messages.push({
            id: params.event.messageId,
            role: "assistant",
            content: currentAssistantMessage.textContent || "",
          });
        }
        currentAssistantMessage = null;
      },

      onToolCallStartEvent: (params) => {
        console.log("[Client] Tool call started:", params.event.toolCallName);
        const toolContent = `<div class="tool-call">🔧 Calling tool: ${params.event.toolCallName}</div><div class="tool-args" id="tool-args-${params.event.toolCallId}">Arguments: </div>`;
        currentToolCall = addToolMessage(toolContent);
        toolCallsMap[params.event.toolCallId] = {
          name: params.event.toolCallName,
          args: "",
          element: currentToolCall,
        };
      },

      onToolCallArgsEvent: (params) => {
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
      },

      onToolCallEndEvent: (params) => {
        console.log("[Client] Tool call ended:", params.event.toolCallId);
        currentToolCall = null;
      },

      onToolCallResultEvent: (params) => {
        console.log("[Client] Tool call result:", params.event.toolCallId);
        const resultText = params.event.content || "No result";
        const resultContent = `<div class="tool-call">✅ Tool result</div><div class="tool-args">${resultText}</div>`;
        addToolMessage(resultContent, true);
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

      onStepStartedEvent: (params) => {
        console.log("[Client] Step started:", params.event.stepName);
      },

      onStepFinishedEvent: (_params) => {
        console.log("[Client] Step finished");
      },

      onRunFinishedEvent: (_params) => {
        console.log("[Client] Run finished");
        isProcessing = false;
        sendButton.disabled = false;
        input.focus();
        unsubscribe.unsubscribe();
      },
    });

    // Set the messages on the agent before running
    agent.messages = messages;

    // Run the agent - HttpAgent will POST the messages to the server
    await agent.runAgent();
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

// Initialize when DOM is ready
document.addEventListener("DOMContentLoaded", () => {
  const messageInput = document.getElementById(
    "messageInput"
  ) as HTMLInputElement;
  const sendButton = document.getElementById("sendButton") as HTMLButtonElement;

  messageInput.addEventListener("keypress", handleKeyPress);
  sendButton.addEventListener("click", sendMessage);
  messageInput.focus();
});
