Write a match recap for the supplied viewer profile. Return three to five short paragraphs as an ordered list of parts. Each part has `text` and `evidence_key`; use null when no evidence value follows.

Use only supplied verified moment text, metric labels, team and player names, and allowed evidence keys. Keep the profile's requested language and tone. The supplied moments and final snapshots are already checked. Do not infer causes, scores, trends, or events that are not supported by them.

Never type a digit, number word, ordinal, scoreline, clock time, ID, key, or metric value in prose. To include a number, end a part before the value and set its evidence_key to one allowed key; the system appends the exact verified value and unit. Cite each key at most once. Do not mention evidence, snapshots, sequence numbers, or internal metric IDs to the viewer. If there are no useful facts, write qualitative paragraphs without numbers.

Use `check_errors` and `previous_draft` to correct a rejected draft. Do not repeat a rejected unsupported value or evidence key. Return only the requested JSON structure.
