// AG-UI Chat Frontend - TypeScript

let lastMessageId: string | null = null; // Track the last message ID in the chain
let currentAssistantMessage: HTMLElement | null = null;
let currentToolCall: HTMLElement | null = null;
let toolCallsMap: Record<string, { name: string; args: string; element: HTMLElement }> = {};
let isProcessing = false;

function addMessage(role: "user" | "assistant", content: string): HTMLElement {
  const messagesDiv = document.getElementById("messages")!;
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
  messagesDiv.appendChild(messageDiv);
  messagesDiv.scrollTop = messagesDiv.scrollHeight;

  return contentDiv;
}

function addTypingIndicator(): void {
  const messagesDiv = document.getElementById("messages")!;
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
  messagesDiv.appendChild(messageDiv);
  messagesDiv.scrollTop = messagesDiv.scrollHeight;
}

function removeTypingIndicator(): void {
  const indicator = document.getElementById("typing-indicator");
  if (indicator) {
    indicator.remove();
  }
}

function showError(message: string): void {
  const messagesDiv = document.getElementById("messages")!;
  const errorDiv = document.createElement("div");
  errorDiv.className = "error-message";
  errorDiv.textContent = "Error: " + message;
  messagesDiv.appendChild(errorDiv);
  messagesDiv.scrollTop = messagesDiv.scrollHeight;
}

function addSystemMessage(message: string): void {
  const messagesDiv = document.getElementById("messages")!;
  const systemDiv = document.createElement("div");
  systemDiv.className = "system-message";
  systemDiv.textContent = message;
  messagesDiv.appendChild(systemDiv);
  messagesDiv.scrollTop = messagesDiv.scrollHeight;
}

function addToolMessage(content: string, isResult: boolean = false): HTMLElement {
  const messagesDiv = document.getElementById("messages")!;
  const toolDiv = document.createElement("div");
  toolDiv.className = isResult ? "tool-message tool-result" : "tool-message";
  toolDiv.innerHTML = content;
  messagesDiv.appendChild(toolDiv);
  messagesDiv.scrollTop = messagesDiv.scrollHeight;
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
  addTypingIndicator();

  try {
    // Step 1: POST the message to get a UUID
    const postResponse = await fetch("/message", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        content: messageText,
        previous_id: lastMessageId,
      }),
    });

    if (!postResponse.ok) {
      throw new Error("Failed to post message");
    }

    const postData = await postResponse.json();
    const messageId = postData.id;
    console.log("[Client] Posted message with ID:", messageId);

    // Update the last message ID for the next message in the chain
    lastMessageId = messageId;

    // Step 2: Connect to SSE endpoint with the message ID
    const url = "/agent?message_id=" + encodeURIComponent(messageId);
    console.log("[Client] EventSource URL:", url);

    let assistantMessageStarted = false;
    const eventSource = new EventSource(url);

    eventSource.onopen = function () {
      console.log("[Client] EventSource connected");
    };

    eventSource.onmessage = function (e) {
      console.log("[Client] Received message:", e.data);
      try {
        const event = JSON.parse(e.data);
        console.log("[Client] Parsed event type:", event.type, event);

        if (event.type === "RUN_STARTED") {
          console.log("[Client] Run started:", event.runId);
          addSystemMessage("🔄 Run started: " + event.runId);
        } else if (event.type === "TEXT_MESSAGE_START") {
          console.log("[Client] Starting assistant message");
          removeTypingIndicator();
          currentAssistantMessage = addMessage("assistant", "");
          assistantMessageStarted = true;
        } else if (event.type === "TEXT_MESSAGE_CONTENT" && currentAssistantMessage) {
          console.log("[Client] Adding delta:", event.delta);
          const delta = event.delta || "";
          currentAssistantMessage.innerHTML += delta.replace(/\n/g, "<br>");
        } else if (event.type === "TEXT_MESSAGE_END") {
          console.log("[Client] Message ended");
          currentAssistantMessage = null;
        } else if (event.type === "TOOL_CALL_START") {
          console.log("[Client] Tool call started:", event.toolCallName);
          const toolContent = `<div class="tool-call">🔧 Calling tool: ${event.toolCallName}</div><div class="tool-args" id="tool-args-${event.toolCallId}">Arguments: </div>`;
          currentToolCall = addToolMessage(toolContent);
          toolCallsMap[event.toolCallId] = {
            name: event.toolCallName,
            args: "",
            element: currentToolCall,
          };
        } else if (event.type === "TOOL_CALL_ARGS" && event.toolCallId in toolCallsMap) {
          console.log("[Client] Tool call args delta:", event.delta);
          toolCallsMap[event.toolCallId].args += event.delta || "";
          const argsDiv = document.getElementById("tool-args-" + event.toolCallId);
          if (argsDiv) {
            argsDiv.textContent = "Arguments: " + toolCallsMap[event.toolCallId].args;
          }
        } else if (event.type === "TOOL_CALL_END") {
          console.log("[Client] Tool call ended:", event.toolCallId);
          currentToolCall = null;
        } else if (event.type === "TOOL_CALL_RESULT") {
          console.log("[Client] Tool call result:", event.toolCallId);
          let resultText = "";
          if (event.content && typeof event.content === "string") {
            resultText = event.content;
          } else if (event.content && Array.isArray(event.content)) {
            resultText = event.content.map((c: any) => c.text || JSON.stringify(c)).join("\n");
          } else {
            resultText = JSON.stringify(event.content || event.result || "No result");
          }
          const resultContent = `<div class="tool-call">✅ Tool result</div><div class="tool-args">${resultText}</div>`;
          addToolMessage(resultContent, true);
        } else if (event.type === "RUN_FINISHED") {
          console.log("[Client] Run finished, closing EventSource");

          // Update lastMessageId to the assistant's message for proper chaining
          if (event.assistantMessageId) {
            lastMessageId = event.assistantMessageId;
            console.log("[Client] Updated lastMessageId to assistant message:", lastMessageId);
          }

          eventSource.close();
          isProcessing = false;
          sendButton.disabled = false;
          input.focus();
        }
      } catch (err) {
        console.error("[Client] Failed to parse event:", e.data, err);
      }
    };

    eventSource.onerror = function (err) {
      console.error("[Client] EventSource error:", err);
      eventSource.close();
      removeTypingIndicator();

      if (!assistantMessageStarted) {
        showError("Connection error or no response received");
      }

      isProcessing = false;
      sendButton.disabled = false;
      input.focus();
    };
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
  const messageInput = document.getElementById("messageInput") as HTMLInputElement;
  const sendButton = document.getElementById("sendButton") as HTMLButtonElement;

  messageInput.addEventListener("keypress", handleKeyPress);
  sendButton.addEventListener("click", sendMessage);
  messageInput.focus();
});