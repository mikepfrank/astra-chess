## Bounded initial deliberation

On your own move turns, strategize independently first, but not indefinitely.
After chess_status, keep unaided deliberation in quiet positions to a brief
comparison of plausible plans. Once you have a reasonable legal candidate and
a concrete concern, register it with chess_candidate and call chess_query
promptly. If several reasonable moves seem close, use the engine to help compare
them; do not spend a long reasoning block trying to prove one dominant before
consulting it. Afterwards, weigh the completed depth and tactical evidence
alongside your judgment: a small heuristic score gap alone need not overturn
a sound positional plan. Preserve the normal review and submission reserve.
