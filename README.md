sole 1:

This slide presents our automation testing environment.

On the left, we have the libraries used by the framework, such as Selenium for web testing, Appium for mobile testing, and curl for API requests.

In the center, we have our automation framework based on Python and Robot Framework.
Python scripts contain reusable functions and selectors, and Robot Framework contains the test cases.

On the right, we have the systems under test, including web applications, mobile applications, and APIs.



transis :
Now that I have presented our automation testing environment, I will introduce the first use case.


slide2:

In this first use case, we focus on framework maintenance when a new version of the application is released.

At the beginning, our automation framework works with version A of the application.

When a new version of the application is released, in this example version B, some elements in the interface may change.

Because of these changes, some selectors used in the automation framework may no longer work.

To fix this, we currently need to manually update the selectors in the framework using Python scripts.

After updating the selectors, the framework becomes compatible with the new version of the application.

transi:
To reduce this manual work, we explored how AI could help automate this process.

slide3:
In this slide, I present the workflow we use with our internal AI tool called Daisei.

First, Daisei is integrated into our development environment using the Continue extension in the IDE.
This allows us to interact directly with the AI from our development tools.

Then the AI connects to different sources using MCP servers running in Docker.

On one side, it connects to Appium, which allows it to interact with mobile devices and extract selectors from the application.
This can be done on a device running the new version of the application.

On the other side, the AI connects to GitLab, where our automation framework code is stored, to extract the selectors currently used in the tests.

By comparing these two sources, the AI generates an output file containing updated selectors for the new version of the application.



transi:
The first use case showed how AI can help maintain our automation framework.

Now I will present a second use case related to test creation and code generation.


slide :4

In this second use case, the goal is to improve how we write our automation tests.

Today, many of our automation scripts are written without Gherkin syntax.

Because of this, the scripts sometimes require manual updates to align with the testing standards we want to use.

Our objective is to progressively integrate Gherkin syntax into our automation scripts.

By doing this, tests become easier to read, easier to maintain, and closer to the way manual testers describe test scenarios.

transi:
To help with this transition to Gherkin, we explored how AI could assist in generating test code automatically.


slide 5:
In this slide, I present the workflow used to generate test code with our internal AI tool, Daisei.

First, the AI is integrated into the development environment using the Continue extension in the IDE.
This allows developers or testers to interact directly with the AI.

The AI then connects to different sources using MCP servers.

On one side, it connects to Jira, where manual testers write the test cases.
The AI reads the test case and generates a summary of the scenario.

On the other side, the AI connects to GitLab, where the automation framework code is stored.
This allows the AI to understand the existing code context and structure of the tests.

Using both the test description and the framework context, the AI generates an output containing a test template in Gherkin format.



