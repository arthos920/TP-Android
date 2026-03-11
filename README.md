MOBILE AUTOMATION RULE — MANDATORY SCREEN ANALYSIS

The AI is controlling a mobile device through MCP tools.

RULE: Before performing ANY action on the mobile device, the AI MUST first call the tool `mobile_list_elements_on_screen`.

Purpose:
This tool returns the list of all visible UI elements currently present on the screen (texts, buttons, icons, input fields, labels, ids, and positions). The AI must always use this information to determine what element it should interact with.

Mandatory workflow:

1. Screen inspection
Before any mobile interaction (tap, click, swipe, scroll, long press, input text, etc.), the AI MUST call:

mobile_list_elements_on_screen

2. Element identification
After retrieving the list of elements, the AI must analyze the returned data and identify the correct target element using available properties such as:
- text
- label
- id
- accessibility label
- position
- element type

3. Action validation
Before performing the action, the AI must ensure that:
- the target element exists in the returned list
- the element is visible on screen
- the element corresponds to the user's request

4. Execute action
Only after the element has been clearly identified from the tool results can the AI perform the requested action (tap, swipe, input text, etc.).

5. Re-check after UI change
If an action may change the UI (navigation, opening a page, closing a popup, scrolling, etc.), the AI MUST call `mobile_list_elements_on_screen` again before performing the next action.

Critical rule:
The AI MUST NEVER perform a mobile interaction without first calling `mobile_list_elements_on_screen` to understand the current screen state.