# Structured humanization

Random humanization adds noise: every note moves on its own, nothing is remembered from one note to the next. Musicians don't play like that. Their timing and dynamics drift, push and lay back, with a long memory. Listeners hear the difference: studies of human timing fluctuations find long-range correlations rather than white noise, and listeners prefer them.

> *"Cedra adds a very human vibe."* Olivier Cedrati, after the first track made with these tools.

## Why it sounds human

A musician never plays the same bar twice, yet never plays at random either: the variations have a memory. Structured humanization has the same four traits:

- **never identical**: the rotation is irrational, so nothing repeats exactly;
- **never messy**: hits and values stay evenly spread (gaps of only two or three sizes);
- **a memory**: near-periods (13, 47 steps for Cedra) come back almost unchanged, like a phrase played again with small changes;
- **independent gestures**: timing, velocity and length follow rotations that are independent over Q, like the two hands of a drummer.

Random humanization only has the first trait, a rigid grid only the second.

Ableton Studio MCP offers a third way between the rigid grid and random jitter: **irrational rotations**.

$$x_n = \{ n\theta + \varphi \}, \qquad \theta \text{ irrational}$$

where $\{x\}$ is the fractional part. The values never repeat, yet they are spread as evenly as possible (three-distance theorem). The result is variation with structure.

## Quasi-periodic rhythms: `quasiperiodic_rhythm`

Put a hit on step $n$ when the rotation falls in a window of length $\tau$:

$$\text{hit}(n) \iff \{ n\theta + \varphi \} < \tau.$$

- **Even.** The gaps between hits take at most three sizes, and with $\tau = \theta$ (the default) only two. Every window of the same length holds the same number of hits, give or take one. These are **Sturmian words**, the infinite relatives of Euclidean rhythms.
- **Never periodic.** Because $\theta$ is irrational, the pattern never repeats exactly. It seems to loop on certain lengths, then slides by one step.
- **Near-periods.** The lengths on which it almost loops are the denominators of the continued fraction of $\theta$. A loop of such a length closes almost seamlessly. The tool returns them as `near_periods`, and `seam_mismatch` gives the share of steps that change at the loop point, which equals $2\min(\lVert L\theta\rVert, \tau, 1-\tau)$ for a loop of $L$ steps.
- **Dynamics.** Each hit's velocity follows $\{n\theta + \varphi\}$, so the dynamics never settle either.
- **Accents where the groove slips.** With `accent_role`, a second pad plays only on the steps where the pattern differs from itself shifted by a near-period $q$, that is $\text{hit}(n) \neq \text{hit}(n+q)$. The accents are sparse and fall exactly where the rhythm's own structure moves.

| rotation | value | continued fraction | near-periods | character |
|---|---|---|---|---|
| `cedra` | 0.617006 | [0; 1, 1, 1, 1, 1, 1, 3, 29, ...] | 2, 3, 5, 8, 13, **47**, 1376, 1423 | starts like the golden ratio, then a long, almost exact 47-step cycle that slowly slides |
| `golden` | 0.618034 | [0; 1, 1, 1, ...] | 2, 3, 5, 8, 13, 21, 34, 55, 89 | the most even of all, Fibonacci lengths |
| `silver` | 0.414214 | [0; 2, 2, 2, ...] | 2, 5, 12, 29, 70 | sparser, other proportions |

The rotation is your choice: `quasiperiodic_rhythm` has no default, and without one it writes nothing and lists the options. Any number between 0 and 1 also works; a rational one gives a plain (periodic) Euclidean-like rhythm.

## Micro-variations: `transform_clip` with `humanize_structured`

```json
{"op": "humanize_structured", "timing": 0.01, "velocity": 8, "duration": 0.1, "drift": 0.3, "drift_bars": 8, "phase": 0}
```

Each note's change mixes two parts:

- **a fast part**, a rotation that differs at every onset, never repeats, and stays evenly spread;
- **a slow part** (weight `drift`), a smooth curve over about `drift_bars` bars made of two sines whose periods have an irrational ratio, so it never comes back to itself. This is the groove pushing and laying back, getting louder and softer.

Timing, velocity and length use **three different rotations**: the logarithms of three Galois conjugates of the Cedra constant. Together with 1, these numbers are linearly independent over $\mathbb{Q}$, so the three variations are jointly equidistributed and don't move together. A note played late is not systematically louder. Notes starting together (a chord) keep the same timing shift. Another `phase` gives another take with the same character, and the same settings always give the same result.

## The Cedra rotation

The `cedra` rotation is $\theta = \ln C$ with

$$C = \sqrt{3} + \tfrac{3}{2}\sqrt{2} - 2 \approx 1.853371.$$

$\ln C$ is transcendental. Its continued fraction starts with six 1s, like the golden ratio, so short patterns sound golden. Then the partial quotients 3 and 29 make a 47-step cycle that is almost exact, and the pattern slides very slowly against it. The independence of the conjugates' logarithms, the near-period formula and the diffraction of these rhythms are proved in [cedrati/cedra](https://github.com/cedrati/cedra).

## Tips

- On hats or a shaker at 16ths, `quasiperiodic_rhythm` with `accent_role="rim"` gives a hypnotic part that keeps evolving over a long loop.
- Use `length_steps` with a near-period (47, or 1376 for about 86 bars of 16ths) when the clip should loop without an audible seam. Keep whole bars when it should line up with the rest of the arrangement.
- Keep `timing` small (0.005 to 0.02 beats). The structure is what you feel, not the amount.
