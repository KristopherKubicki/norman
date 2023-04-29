async function getMessages() {
  const response = await fetch("/api/v1/messages");
  const messages = await response.json();
  return messages;
}

function createMessageElement(message) {
  const messageElement = document.createElement("div");
  messageElement.classList.add("message");

  const timestampElement = document.createElement("p");
  timestampElement.textContent = `Timestamp: ${message.timestamp}`;

  const contentElement = document.createElement("p");
  contentElement.textContent = `Content: ${message.content}`;

  messageElement.appendChild(timestampElement);
  messageElement.appendChild(contentElement);

  return messageElement;
}

(async () => {
  const messages = await getMessages();
  const messagesContainer = document.querySelector(".messages-container");

  for (const message of messages) {
    messagesContainer.appendChild(createMessageElement(message));
  }
})();

