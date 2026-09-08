"""ESPN fantasy football stat ids, for rendering a league's scoring table.

The ids are ESPN's, not documented anywhere official. This map was checked
against Roll for First Down's scoring items on 2026-09-07: every value the
playbook had already verified by hand (0.04 per passing yard on id 3, 0.10
per rushing yard on 24, 4 per passing TD on 4, 6 per rushing TD on 25, the
3/4/5/6 field-goal buckets on 80/77/198/201, -1 per miss on 85, -7 for 550+
yards allowed on 136, 1 per reception on 53) landed on the id this map names.
Unknown ids render as "stat <id>" rather than guessing.
"""

STAT_NAMES: dict[int, str] = {
    3: "Passing yards (per yard)",
    4: "Passing TD",
    19: "Passing 2-pt conversion",
    20: "Interception thrown",
    24: "Rushing yards (per yard)",
    25: "Rushing TD",
    26: "Rushing 2-pt conversion",
    42: "Receiving yards (per yard)",
    43: "Receiving TD",
    44: "Receiving 2-pt conversion",
    53: "Reception",
    63: "Fumble recovered for TD",
    72: "Fumble lost",
    74: "FG made 50+ yards",
    77: "FG made 40-49 yards",
    80: "FG made 0-39 yards",
    85: "FG missed",
    86: "PAT made",
    88: "PAT missed",
    89: "D/ST 0 points allowed",
    90: "D/ST 1-6 points allowed",
    91: "D/ST 7-13 points allowed",
    92: "D/ST 14-17 points allowed",
    93: "Blocked punt/FG returned for TD",
    95: "D/ST interception",
    96: "D/ST fumble recovery",
    97: "D/ST blocked kick",
    98: "D/ST safety",
    99: "D/ST sack",
    101: "Kickoff return TD",
    102: "Punt return TD",
    103: "Fumble return TD",
    104: "Interception return TD",
    122: "D/ST 18-27 points allowed",
    123: "D/ST 28-34 points allowed",
    124: "D/ST 35-45 points allowed",
    125: "D/ST 46+ points allowed",
    128: "D/ST under 100 yards allowed",
    129: "D/ST 100-199 yards allowed",
    130: "D/ST 200-299 yards allowed",
    131: "D/ST 300-349 yards allowed",
    132: "D/ST 350-399 yards allowed",
    133: "D/ST 400-449 yards allowed",
    134: "D/ST 450-499 yards allowed",
    135: "D/ST 500-549 yards allowed",
    136: "D/ST 550+ yards allowed",
    198: "FG made 50-59 yards",
    201: "FG made 60+ yards",
    206: "D/ST 2-pt conversion return",
    209: "D/ST 1-pt safety",
}


def stat_name(stat_id: int) -> str:
    return STAT_NAMES.get(stat_id, f"stat {stat_id}")
