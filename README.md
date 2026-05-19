AI-Assisted Robot Framework Test Generation from Jira &
GitLab
Objective
This script automates the transformation of a Jira ticket into a relevant Robot Framework test proposal. It retrieves and
summarizes Jira tickets, identifies the functional scenario type, determines the relevant parts of the Robot Framework
repository, reads targeted GitLab files, and generates coherent Robot Framework test cases aligned with the existing
framework.
Prerequisites / Resources
Infrastructure:
- Docker Compose environment
- GitLab container
- Jira container
Access:
- Jira personal access token
- GitLab personal access token
Technologies:
- Python
- MCP (Model Context Protocol)
- OpenAI-compatible LLM
- Robot Framework
Functional Workflow
1. Read a Jira ticket
2. Generate a QA-oriented summary
3. Characterize the functional scenario
4. Identify relevant GitLab framework files
5. Read targeted framework resources
6. Reuse existing keywords and conventions
7. Generate a coherent Robot Framework test proposal
Ticket Characterization
The script classifies the ticket into categories such as:
- private call
- video call
- conference call
- messaging
- other
This classification avoids exploring the entire repository unnecessarily.
GitLab Mapping
Based on the detected scenario type, the script maps the ticket to the most relevant framework files.
Example:
- private call → private call keywords/resources
- conference call → conference call templates
- video call → media validation keywords
Targeted GitLab Exploration
The script uses MCP GitLab tools such as:
- get_project
- get_repository_tree
- get_file_contents
It retrieves:
- convention files
- Robot Framework keywords
- templates/examples
- reusable resources
Robot Framework Recommendation Generation
The AI generates:
- recommended keywords
- required imports/resources
- test structure
- Robot Framework test case proposal
while respecting existing framework conventions.
Example Prompt
You are a QA automation assistant.
Your goal is to generate a Robot Framework test case proposal.
Rules:
- NEVER invent Robot Framework keywords.
- ONLY reuse keywords found inside the GitLab repository.
- Follow existing framework conventions.
- Reuse templates/resources when available.
- Prefer consistency over creativity.
Expected Output
The script produces:
- Jira summary
- scenario classification
- relevant framework files
- Robot Framework recommendations
- generated Robot Framework test proposal
Guardrails
- Never invent Robot Framework keywords
- Reuse existing framework resources only
- Limit repository exploration to relevant files
- Maintain framework consistency
- Preserve naming conventions
Limitations
- Human validation is still required
- Output quality depends on Jira ticket quality
- GitLab repository organization impacts relevance
- Scenario/file mappings must be maintained manually
- The script accelerates test creation but does not fully replace QA expertise