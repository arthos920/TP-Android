{
  "rules": [
    "When the user provides a Jira ticket ID, ALWAYS retrieve the ticket details using the Jira MCP server. Do not guess. Always use the Jira MCP server tools first.",
    "If the Jira server is unreachable, STOP and notify the user. Never invent ticket content.",
    "Once the Jira ticket content is retrieved, ALWAYS extract: steps to reproduce, expected behavior, environment, device type, and acceptance criteria.",
    "Before running mobile tests, ALWAYS verify that the Mobile MCP server is connected and reachable. If unreachable, STOP and notify the user.",
    "When interacting with the Mobile MCP server, NEVER simulate actions. ALWAYS call real MCP tools such as 'click', 'navigate', 'input', 'screenshot', or others. Never claim an action is done unless the tool call succeeded.",
    "After each MCP tool call, RETURN the real execution result. If the tool returns an error, STOP and display it.",
    "Follow ALWAYS this workflow for test execution:",
    "1. Fetch Jira ticket via Jira MCP server.",
    "2. Parse ticket → extract test steps.",
    "3. For each step, convert it into concrete MCP Mobile actions.",
    "4. Execute every step via Mobile MCP server tools.",
    "5. After each step, confirm real execution.",
    "6. If screenshots are required, ALWAYS capture one using the mobile MCP tool.",
    "7. At the end of the test, produce a test report based ONLY on real results, not assumptions.",
    "NEVER claim that a test is completed if any MCP call failed or was skipped.",
    "NEVER hallucinate UI elements. If an element is not found, ask the user for clarification or request a screenshot.",
    "Always stay strictly synchronized with real device state through MCP responses."
  ]
}