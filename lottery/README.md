# lottery

A scanner that shows when a lottery game near Kansas City is a positive-expectation bet.

A lottery game gives 50 to 82 cents for each dollar on a usual day. Three local games have a jackpot that increases until a player wins it. After many draws with no winner, the expected value of a ticket can be more than its price. Missouri also publishes the full prize table of each Scratchers game each day. From that table, the tool calculates the expected value of the tickets that are not sold. The tool reads those public numbers and does the arithmetic. It does not buy tickets and it holds no account.

## Use

```
lottery/bin/lottery-scan                 # jackpot games, 5 seconds
lottery/bin/lottery-scan --scratchers    # add all Missouri Scratchers (approximately 90 seconds)
lottery/bin/lottery-scan --json
lottery/bin/lottery-scan --ledger        # append the result to lottery/data/ledger.jsonl
lottery/bin/lottery-scan --notify        # banner and Discord DM, only when a trigger is on
```

The exit code is 0 when no trigger is on and 10 when one is.

## What the columns mean

| Column | Definition |
| --- | --- |
| pre-tax, after tax | Expected value of one ticket for each dollar at the current jackpot, with the least-picked numbers |
| even pre | The advertised jackpot at which the expected value of a ticket is equal to its price before tax |
| even after | The same level after federal and state income tax on the jackpot |
| printed | Scratchers: value of all prizes divided by the face value of all tickets |
| sold | Scratchers: the share of the game that is sold, from the middle prize tiers |
| now | Scratchers: expected value for each dollar of the tickets that are not sold |
| turns + at | Scratchers: the sold share at which the game goes above 1.00 if no more top prizes are claimed |

## Games

| Game | Where | Ticket | Jackpot odds for one ticket | Break-even, before tax | Break-even, after tax |
| --- | --- | --- | --- | --- | --- |
| Show Me Cash | Missouri retail | $1 | 1 in 575,757 | approximately $453,000 | approximately $731,000 |
| MO Millions | Missouri retail | $2 | 1 in 5,245,786 | approximately $17.6 million advertised | approximately $30 million advertised |
| Super Kansas Cash | Kansas retail | $1 (2 boards) | 1 in 2,517,200 | approximately $1.99 million | approximately $3.43 million |

The tool calculates these levels from the prize tables in `lottery_ev.py`. They change when a lottery changes a prize table or when the tax constants change.

## Method

- Jackpot games: expected value = fixed prizes + jackpot x probability of a win x expected share. The expected share uses a Poisson count of other winners. Sales for each draw increase with the jackpot. The slope comes from the draw history of each lottery.
- Least-picked numbers: in Show Me Cash, players pick the numbers 32 to 39 less frequently than the other numbers. A set from that range has approximately half the co-winners of an average set. This multiplier comes from the winner counts of 4,780 draws.
- Scratchers: the sold share comes from the prize tiers between 2.5 times the ticket price and $600. Players claim those prizes quickly. Players claim the lowest tiers late or not at all, so the counts of those tiers overstate the prizes that stay in the game. Prize tiers with 200 or more prizes are taken at the printed rate. Rarer prizes are taken at the unclaimed count.
- Tax: a 2026 single filer with $30,000 of other income. The model uses the IRS brackets and the 90 percent limit on the deduction of losing tickets (IRC 165(d)). Missouri tax is 4.7 percent. Kansas tax is 5.58 percent with no deduction for losing tickets. The result is an estimate for planning.

## Checks

`pytest tests/test_lottery_ev.py` runs the positive controls. The prize tables must reproduce the "overall chances" line that each lottery prints. A synthetic Scratchers game with no top prize left must have an expected value below its printed payout.

## Limits

- A positive expected value is not a profit. One Show Me Cash ticket wins the jackpot 1 time in 575,757.
- The Scratchers data shows prizes that are unclaimed. It is possible that a top prize is sold but not claimed.
- Kansas Scratchers are not included. Kansas does not publish total prize counts or ticket counts.
- The ledger in `lottery/data/` is local and is not in the repository.
