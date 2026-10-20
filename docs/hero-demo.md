# Show me why: judge walkthrough

## Demonstration

1. Start a balanced synthetic match. Use faster live playback to reach an insight; historical evidence always replays at 1x.
2. Open **SHOW ME WHY** on a published story. Stories remain available after the broadcast overlay expires.
3. Select an underlined numeric phrase. Show the saved value, fresh computation, calculation method, and time window.
4. Select a gold source event. The replay seeks to its historical timestamp and pauses; use **FOCUS EVIDENCE** in the 3D view. Gold marks show sources; teal marks show context. A tracking-only metric may have player markers without source-event arrows.
5. Switch to a published Spanish audience version. The wording changes while the evidence reference and replay position remain fixed.
6. Show the agent decisions. To demonstrate recovery, arm **Inject a wrong stat** before the next insight and inspect that story after publication. This intentionally corrupts a structured draft claim; its declared value, cited text, rejection, and subsequent decision are visible. Describe it as fault injection.
7. Select **RETURN LIVE**. The live match continued throughout inspection.

Suggested narration: “This sentence was published. Here is its calculation, here is the play behind it, and here is the agent decision that allowed it on screen.”

## Claims we can demonstrate

- Saved evidence is retained at generation time, including tracking metrics that change without a new event sequence.
- Recalculation runs the deterministic metrics engine on historical raw inputs rather than reading back the saved value. It checks reproducibility with the same algorithm, not independent validation of the algorithm itself.
- The endpoint excludes later events and tracking samples. The displayed 20-second passage is context; aggregate calculations can use a longer window, shown explicitly.
- Audience tabs show versions actually published for this insight. They do not generate translations during inspection.
- Traces belong to the selected moment. Rejected drafts are distinguishable from published wording.

## Practical limits

Numeric agreement does not establish tactical causation. Reconstructed player movement and all match data are synthetic. Missing raw history yields an unavailable result. Evidence is session-scoped in memory, not a durable audit archive; its reference is an identifier, not a cryptographic authenticity guarantee.

Local previews use mock generation unless explicitly configured otherwise. Demonstrate Microsoft Foundry execution using the deployed configured runtime and its real traces. Do not describe mock calls as live model calls.

For the under-two-minute submission, prioritize one successful inspection and one clear rejected-claim recovery. Keep enough time to show the Microsoft Agent Framework handoffs and viewer benefit. Confirm the final recording and submission satisfy the official rules.
