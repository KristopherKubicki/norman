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

    // Send message to the backend (replace with the appropriate API endpoint)
    fetch('/api/process_message', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message, connector }),
    })
        .then(response => response.json())
        .then(data => {
            // Display received message
            messageDisplay.innerHTML += `<p><strong>Norman:</strong> ${data.response}</p>`;
        })
        .catch(error => {
            console.error('Error:', error);
        });
});


