export function helloWorld(name: string): string {
  if (name === "Error") {
    throw new Error("Invalid name");
  }
  return `Hello, ${name}!`;
}