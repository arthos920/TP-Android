
Just to align with you — what would be most useful?


I’ll start with a quick overview, then go into the script, and finish with an example.



We run two Docker containers, one for Jira and one for GitLab, configured with personal access tokens.
They expose MCP endpoints that the Python script uses to retrieve tickets and read the test framework.


🎯 Overview

This script automates the transformation of a Jira ticket into a relevant Robot Framework test case proposal by leveraging targeted reading of the test framework stored in GitLab.

⸻

🔄 Overall Logic

The script follows a simple pipeline:

1. It reads a Jira ticket
2. It generates a structured, QA-oriented summary
3. It identifies the functional scenario type
4. It determines which GitLab framework files are relevant
5. It reads those files
6. It extracts reusable keywords and conventions
7. It generates a Robot Framework test case aligned with the existing framework

⸻

🧩 Functional Breakdown

1. Jira Ticket Retrieval and Summarization

The script queries Jira via MCP to retrieve the ticket, then produces a QA-focused summary including:

* objective
* preconditions
* main steps
* expected results
* points of attention

⸻

2. Ticket Characterization

The script then identifies the type of scenario being tested.

For example:

* private call
* video call
* conference call
* other

This step helps avoid unnecessary exploration of the entire repository.

⸻

3. Mapping to the GitLab Framework

Once the ticket type is identified, the script uses a mapping to determine which framework files should be read.

👉 Key idea:
A given ticket type corresponds to specific files or areas of the test framework.

Instead of scanning the entire repository, the script focuses only on the most relevant files.

⸻

4. Targeted Reading of GitLab Files

The script retrieves:

* convention files
* scenario-specific keyword files
* optional templates or example tests

This ensures the generation is grounded in the actual framework.

⸻

5. Robot Framework Recommendation Generation

Using both Jira and GitLab data, the script builds:

* relevant keywords to reuse
* required imports/resources
* a test structure (skeleton)
* a complete and relevant Robot Framework test case


Limitations (Honest View)

It is important to highlight current limitations:

* it provides a strong test proposal but does not fully replace human validation
* the quality depends on the quality of the Jira ticket and the structure of the GitLab framework
* the mapping between ticket types and files must be maintained
* it is very effective for accelerating test creation, but not sufficient on its own to guarantee full execution readiness



