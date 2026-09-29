Hi,

These are the data I was able to extract from the automation side using the Robot Framework/Appium logs. We can compare them with Julien’s results to see whether he gets the same values with his tools.

During the endurance test, Julien and I observed a UI issue occurring when the PTT action was triggered. Since the same action was repeatedly executed by all 6 UEs over a long period, it is possible that this issue contributed to the application becoming unstable or crashing. However, I currently do not have logs that allow me to confirm a direct link between this UI issue and the UE lock/crash, so for now this remains a hypothesis.

The six UEs were simultaneously operational for a cumulative duration of approximately 39h46min during the run. The longest continuous stable period was approximately 37h24min, from 24/09 11:58:37 to 26/09 01:22:58. After 26/09 01:22:58, at least one UE remained in failure until the end of the run.

Yes, a few additional outcomes:

The reason for the early stop is now confirmed. The Robot Framework WHILE loop reached its default limit of 10,000 iterations, causing the loop to be aborted after 86h18m13s, before reaching the planned 120h. The loop limit will need to be increased or removed for the next endurance run.

A total of 60,000 PTT attempts were executed across the 6 UEs, with 29,325 successful PTTs and 30,675 failures, giving an overall automation success rate of 48.88%.

The failures were mostly grouped into long continuous failure periods rather than isolated errors. Once some UEs entered this state, they did not recover for several hours or until the end of the run.

The 25/09 was particularly stable, with exactly 1,989 successful PTTs per UE.

BR