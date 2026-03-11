Introduction de la démo

I will now show an example of the output generated for the second use case.

⸻

Partie 1 — Lecture du test Jira

(Pointe le haut de l’écran)

First, the AI reads the test case written in Jira.

Here we can see the description of the scenario, including the steps of the test and the expected results.

For example, this test verifies a PTT call between two users, including the call initiation, the communication, and the call termination.

⸻

Partie 2 — Analyse du framework

(Pointe la partie où on voit les appels GitLab)

After reading the Jira test case, the AI analyzes the automation framework stored in GitLab.

It searches for existing keywords and test templates in the repository.

This step allows the AI to understand how tests are structured and which reusable keywords already exist.

⸻

Partie 3 — Identification des keywords

(Pointe la partie avec la liste des keywords)

Based on this analysis, the AI identifies the keywords that can be reused in the automation framework.

For example, keywords for navigating to contacts, initiating a call, pressing the PTT button, or ending the call.

⸻

Partie 4 — Génération du test Robot Framework

(Pointe la partie finale avec le test généré)

Finally, the AI generates a Robot Framework test case template.

The test includes the structure of the scenario and the main steps using existing keywords from the framework.

⸻

Conclusion de la démo

This generated test provides a starting point for the automation script, which can then be reviewed and completed by the tester before integration into the framework.
