During the endurance test, Julien and I observed a UI issue occurring when the PTT action was triggered. Since the same action was repeatedly executed by all 6 UEs over a long period, it is possible that this issue contributed to the application becoming unstable or crashing.

However, I currently do not have logs that allow me to confirm a direct link between this UI issue and the UE lock/crash, so for now this remains a hypothesis.


The six UEs were simultaneously operational for a cumulative duration of approximately 39h46min during the run.
The longest continuous stable period was approximately 37h24min, from 24/09 11:58:37 to 26/09 01:22:58.
After 26/09 01:22:58, at least one UE remained in failure until the end of the run.


Yes, a few additional outcomes:

The run stopped after 86h18 instead of the planned 120h.
A total of 60,000 PTT attempts were executed across the 6 UEs, with 29,325 successful PTTs and 30,675 failures, giving an overall success rate of 48.88%.
The failures were mostly grouped into long continuous failure periods, rather than isolated errors. Once some UEs entered this state, they did not recover for several hours or until the end of the run.
The 25/09 was very stable, with exactly 1,989 successful PTTs per UE.