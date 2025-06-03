# TODO List

## bots.html

- [x] Implement markdown for UI screens. Currently facing a library include issue.
- [x] Make the input box multiline and more like the openai chatgpt window.
- [x] Make bots on the left side smaller and easily identifiable, including some kind of highlight on click.
- [x] Disable the send button until a bot is selected.
- [x] Add edit mode from the same area as delete. Edit mode should pop up a modal with the bot details.
- [x] Add a warning alert when the delete bot is clicked.
- [x] Make the "search bots" dialog functional and collapsible by default.
- [x] Add sliders for controlling:
   - The number of messages of history used for the prompt.
   - The amount of response to generate.

## connectors.html

- [x] Change connectors from hardcoded to an object model.
- [x] Add "Add connector" and "Delete connector" functionality, similar to bots.html.
- [x] Add an edit mode for connectors to let the user edit the credentials and other things.
- [x] Make the test button functional. Currently, the backend endpoint doesn't exist.
- [x] Make the status endpoint on the backend functional to give a clear up/down status for the front end to see per connector.

## channels.html

- [x] This page needs complete work. Backend endpoints are not done yet.

## filters.html

- [x] Depends on the channels page.

## messages.html

- [x] This page should be showing a log of all messages across the platform. There is a general endpoint.
- [x] Add filters on the side to filter by connector, channel, bot, filter, message freetext, or time.
- [x] Allow user to select a channel on this screen and the message will be delivered directly to that channel. It should have an IRC-like feel.

