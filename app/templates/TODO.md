# TODO List

## bots.html

1. Implement markdown for UI screens. Currently facing a library include issue.
2. Make the input box multiline and more like the openai chatgpt window.
3. Make bots on the left side smaller and easily identifiable, including some kind of highlight on click.
4. Disable the send button until a bot is selected.
5. Add edit mode from the same area as delete. Edit mode should pop up a modal with the bot details.
6. Add a warning alert when the delete bot is clicked.
7. Make the "search bots" dialog functional and collapsible by default.
8. Add sliders for controlling:
   - The number of messages of history used for the prompt.
   - The amount of response to generate.

## connectors.html

1. Change connectors from hardcoded to an object model.
2. Add "Add connector" and "Delete connector" functionality, similar to bots.html.
3. Add an edit mode for connectors to let the user edit the credentials and other things.
4. Make the test button functional. Currently, the backend endpoint doesn't exist.
5. Make the status endpoint on the backend functional to give a clear up/down status for the front end to see per connector.

## channels.html

1. This page needs complete work. Backend endpoints are not done yet.

## filters.html

1. Depends on the channels page.

## messages.html

1. This page should be showing a log of all messages across the platform. There is a general endpoint.
2. Add filters on the side to filter by connector, channel, bot, filter, message freetext, or time.
3. Allow user to select a channel on this screen and the message will be delivered directly to that channel. It should have an IRC-like feel.

