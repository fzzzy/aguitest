import type { MessageInput } from "./components/elements";

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

let recognition: SpeechRecognition | null = null;
let isRecognizing = false;

function createRecognition(input: MessageInput, micButton: HTMLElement): SpeechRecognition {
  const SpeechRecognitionAPI = window.SpeechRecognition || window.webkitSpeechRecognition;
  const rec = new SpeechRecognitionAPI();
  rec.continuous = false;
  rec.interimResults = true;
  rec.lang = "en-US";

  rec.onstart = () => {
    console.log("[Speech] Recognition started");
    isRecognizing = true;
    micButton.classList.add("recording");
    micButton.title = "Stop speech recognition";
  };

  rec.onend = () => {
    console.log("[Speech] Recognition ended");
    isRecognizing = false;
    micButton.classList.remove("recording");
    micButton.title = "Start speech recognition";
  };

  rec.onerror = (event) => {
    console.error("[Speech] Recognition error:", event.error);
    isRecognizing = false;
    micButton.classList.remove("recording");
    micButton.title = "Start speech recognition";
  };

  rec.onresult = (event: SpeechRecognitionEvent) => {
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

export function initSpeechRecognition(input: MessageInput, micButton: HTMLElement): void {
  if (!window.SpeechRecognition && !window.webkitSpeechRecognition) {
    micButton.style.display = "none";
    return;
  }

  micButton.addEventListener("click", () => {
    if (isRecognizing) {
      recognition?.stop();
      return;
    }

    if (!recognition) {
      recognition = createRecognition(input, micButton);
    }

    try {
      recognition.start();
    } catch (error) {
      console.error("[Speech] Failed to start recognition:", error);
    }
  });
}
