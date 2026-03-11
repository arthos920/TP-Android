sldie 1:
In this slide, I present our automation testing environment.

Our automation framework is based on Robot Framework, where we define the automated test cases.

We also use Python scripts to implement reusable functions and manage selectors used in the tests.

Selectors, also called locators, are identifiers used by the automation tools to find elements in the user interface, such as buttons, text fields, or menus.

The framework relies on several libraries depending on the type of testing.

We use Selenium for web testing, Appium for mobile testing, and curl for API requests.

Using this framework, we can automate tests for different systems under test, including web applications, mobile applications, and APIs.


transi :

The first use case focused on helping maintain the automation framework.

The second use case focuses on helping convert manual test cases into automated tests.







slide 4:

In this second use case, the goal is to translate manual test cases written in Jira into Robot Framework automated tests.

Today, the process is mostly manual.

First, testers read the test case written in Jira and understand the scenario.

Then, they manually create the corresponding automation script in Robot Framework.

Finally, this script is integrated into the automation framework and can be executed as part of the automated test suite.


transi:


Today this whole process is mostly manual.

To simplify this process, we explored how AI could help translate these test cases automatically.

slide 5:

In this slide, I present the workflow used to translate Jira test cases into Robot Framework tests using our internal AI tool, Daisei.

First, the AI is integrated into the development environment using the Continue extension in the IDE.
This allows developers and testers to interact directly with the AI.

Then, the AI connects to different sources using MCP servers.

On one side, it connects to Jira, where the manual test cases are written.
The AI reads the test case and generates a summary of the scenario.

On the other side, the AI connects to GitLab, where the automation framework is stored.
This allows the AI to understand the existing code structure and context.

Using both the test description and the framework context, the AI generates an output template for a Robot Framework test case.




excuse demo :

Normally, we planned to include a live demonstration of this workflow.

However, due to a platform restart earlier this week, the environment was not available and the demo could not be prepared in time.

Instead, I will show the generated outputs to illustrate the results.






