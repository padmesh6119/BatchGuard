# BatchGuard three-minute video script

Target duration: 2:45. Record the real application on the LinuxONE host. Keep
simulated scan data labelled on screen. Do not imply the demo proves medicine
quality or counterfeit detection.

## 0:00–0:22 — The problem

**Show:** Twelve candidate cards and four inspection slots.

**Say:** “An inspector has more cases than inspection capacity. The key question
is not just which case ranks first, but why—and what evidence supports the
choice. BatchGuard turns public medicine-quality reports into a traceable
inspection shortlist.”

## 0:22–0:48 — The evidence

**Show:** Dataset page with real and simulated lanes.

**Say:** “Our history contains 2,551 CDSCO report records over fourteen months.
We keep original report references. Scan events are a separate simulated
stream used to test unusual patterns; they are not field evidence.”

## 0:48–1:18 — The measured result

**Show:** The 13.06 versus 21 bars.

**Say:** “In a two-month chronological test, at a budget of twenty-five
manufacturer texts per month, the history model captured twenty-one later
report records versus 13.06 for the strongest baseline. That is a report
recurrence result, not additional unsafe batches detected.”

## 1:18–2:05 — The live demo

**Show:** On the IBM LinuxONE browser, click Start demo, show the supplied CSV,
the rank changing from 12 to 4, open the source evidence, and show the recorded
demo review. Keep the simulated label visible.

**Say:** “This included CSV runs through the actual queue and checks its
expected outcomes. The scripted location conflict moves this case from rank
twelve to rank four, inside four slots. Removing the conflict makes the check
fail. This proves the workflow responds to the input; it does not prove field
detection accuracy.”

## 2:05–2:32 — IBM LinuxONE

**Show:** Runtime receipt showing s390x and the live app. Do not show secrets,
reviewer personal data, or the public Jupyter token/session URL.

**Say:** “We retrained and ran the Python service on IBM LinuxONE, on s390x.
The service hosts model inference, the inspection queue and review state.
This run uses standard CPU execution; we are not claiming NNPA acceleration
or that the algorithm requires IBM Z.”

## 2:32–2:45 — Close

**Show:** Queue, source report and closing line.

**Say:** “BatchGuard helps make the next inspection decision explainable and
traceable. The next steps are independent review of scan outcomes and a
professional workflow evaluation.”
