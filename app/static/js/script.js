const messageDisplay = document.getElementById('messageDisplay');
const messageInput = document.getElementById('messageInput');
const sendButton = document.getElementById('sendButton');
const connectorSelect = document.getElementById('connectorSelect');

sendButton.addEventListener('click', () => {
    const message = messageInput.value;
    const connector = connectorSelect.value;

    // Clear input
    messageInput.value = '';

    // Display sent message
    messageDisplay.innerHTML += `<p><strong>You:</strong> ${message}</p>`;

    // Show thinking indicator while waiting for response
    const thinking = document.createElement('p');
    thinking.id = 'thinking-indicator';
    thinking.innerHTML = '<em>Norman is thinking...</em>';
    messageDisplay.appendChild(thinking);
    messageDisplay.scrollTop = messageDisplay.scrollHeight;

    // Send message to the backend (replace with the appropriate API endpoint)
    fetch('/api/process_message', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message, connector }),
    })
        .then(response => response.json())
        .then(data => {
            // Remove thinking indicator and display received message
            thinking.remove();
            messageDisplay.innerHTML += `<p><strong>Norman:</strong> ${data.response}</p>`;
            messageDisplay.scrollTop = messageDisplay.scrollHeight;
        })
        .catch(error => {
            thinking.remove();
            console.error('Error:', error);
        });
});


