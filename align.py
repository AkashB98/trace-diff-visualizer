"""Sequence alignment of two step lists (Needleman-Wunsch / DP).

This is the piece the sibling ``tool-call-trace-replay`` differ lists as
future work: instead of aligning steps *positionally* (so one step
inserted mid-trace cascades into tool_drift on every downstream step),
steps are aligned by *content*.

Pair score for aligning a left step with a right step:

  +2  same tool
  +2  canonical args identical
  +1  same observation text
  -3  none of the above (unrelated steps — aligning them is worse than
      paying two gap penalties)

Gap penalty is -1 per one-sided step (``missing`` on the left-only side,
``extra`` on the right-only side). Result payloads are deliberately NOT
part of the signature: a result change must not break the alignment of
the step that produced it.

Tie-breaking is deterministic and forward: when several moves reach the
same optimal score, prefer diagonal (pair) > missing (left-only) >
extra (right-only). Rendering / reporting therefore never depends on
dict order or DP traversal accidents.
"""

from __future__ import annotations

from typing import List, Optional, Tuple

from trace import Step, canonical

GAP_PENALTY = -1
UNRELATED = -3


def pair_score(left: Step, right: Step) -> int:
    score = 0
    if left.tool == right.tool:
        score += 2
    if canonical(left.args) == canonical(right.args):
        score += 2
    if left.observation and left.observation == right.observation:
        score += 1
    if score == 0:
        return UNRELATED
    return score


# An alignment row: (left index or None, right index or None)
AlignmentRow = Tuple[Optional[int], Optional[int]]


def align_steps(left: List[Step], right: List[Step]) -> List[AlignmentRow]:
    """Globally align two step lists, maximising the total pair score."""
    n, m = len(left), len(right)
    # dp[i][j] = best score aligning left[i:] with right[j:] (suffix DP)
    dp = [[0] * (m + 1) for _ in range(n + 1)]
    for i in range(n - 1, -1, -1):
        dp[i][m] = dp[i + 1][m] + GAP_PENALTY
    for j in range(m - 1, -1, -1):
        dp[n][j] = dp[n][j + 1] + GAP_PENALTY
    for i in range(n - 1, -1, -1):
        for j in range(m - 1, -1, -1):
            dp[i][j] = max(
                pair_score(left[i], right[j]) + dp[i + 1][j + 1],
                GAP_PENALTY + dp[i + 1][j],
                GAP_PENALTY + dp[i][j + 1],
            )

    rows: List[AlignmentRow] = []
    i = j = 0
    while i < n or j < m:
        if i < n and j < m:
            diag = pair_score(left[i], right[j]) + dp[i + 1][j + 1]
            if diag == dp[i][j]:
                rows.append((i, j))
                i += 1
                j += 1
                continue
            missing = GAP_PENALTY + dp[i + 1][j]
            if missing == dp[i][j]:
                rows.append((i, None))
                i += 1
                continue
            rows.append((None, j))
            j += 1
        elif i < n:
            rows.append((i, None))
            i += 1
        else:
            rows.append((None, j))
            j += 1
    return rows
