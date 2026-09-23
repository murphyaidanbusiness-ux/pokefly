# fly-brain-pokemon: continued training must not make the fly worse (v4)

Approved by Aidan on 2026-09-22. Builds on commit `d267154`. Same rules as the earlier specs (work only in this folder, `.venv` python, quote the path, numpy only, tuning numbers in `config.py`, never loosen a test, no em dashes in prose, one commit, no push).

## The problem, measured

`brains/v1-2M.npz` is the brain after run 1 (100 episodes, 2M ticks): it leaves the house in 10 of 10 held-out evaluation episodes (seeds 90000-90009, `train.py --evaluate`). Run 2 resumed from it with the same constant learning rates for 129 more episodes (`runs/train2.csv`, `brains/v2-unstable.npz`). The share of training episodes leaving the house went 1.00, 0.80, 0.70, 0.40, 0.00, 0.00, 0.80, 0.40, 0.50, 0.60, 0.40, 0.30, 0.00 by 10-episode bucket. It never settled; it wandered in and out of a good policy. Meanwhile `|w_critic|` grew monotonically 0.029 to 0.043 and the per-pool mean actor weights moved by as much as the whole policy (DOWN 0.0081 to 0.0003, RIGHT 0.0037 to 0.0136 between the two saved brains). The per-episode reward is dominated by one coin flip (did it get out the door) so the gradient signal is high-variance, and a constant step size means the policy keeps being knocked around by every lucky or unlucky episode long after it has found something that works. `run.py` then auto-loads whatever the last checkpoint happened to be.

## What to build

1. **A learning-rate schedule.** `lr = lr0 / (1 + episodes_trained / lr_decay_episodes)` for both actor and critic, `lr_decay_episodes` in `config.py` (start at 100: resuming from 100 episodes runs at half rate, at 300 at a quarter). Applied from `episodes_trained`, so `--resume` continues the schedule instead of restarting it. Log the effective lr in each CSV row. Consider also a slow weight decay toward zero on the critic if `|w_critic|` keeps climbing; only if you can show it helps.
2. **Keep the best brain, not the last one.** Training keeps two files: the training state (`--out`, default `brains/training.npz`, always the latest weights, what `--resume` continues from) and the best brain (`--best`, default `brains/latest.npz`, what `run.py` auto-loads). Every `eval_every` training episodes run an evaluation BLOCK of `eval_block` episodes (default 3) with learning off on FIXED seeds (the same seeds every block, distinct from the held-out 90000-90009 set), score = mean reward over the block, and copy the training state to the best file only when the score beats the best so far. The best file records its score and the episode it came from; `run.py` prints them. Also seed the best from the resumed brain: when resuming from a brain that has no recorded score, evaluate it first so the current best is never silently a worse brain. Ctrl+C keeps both files consistent.
3. **Do not touch the learning rule otherwise** unless the experiment below forces it, and then say exactly what and why.

## Tests
- The schedule: lr at 0, 100, 300 episodes; resume continues from the stored count.
- Best-keeping on a fake trainer (no ROM): a sequence of block scores 3, 5, 4, 6 writes the best file at 3, 5 and 6 only, with the score and episode inside.
- Resuming from a brain without a score evaluates it before training.
- All 121 existing tests pass; if one must change say which and why.

## The experiment (report raw numbers)
1. Resume from a copy of `brains/v1-2M.npz` with the new code for at least 3,000,000 training ticks (`--episode-ticks 20000`), evaluation blocks included. Launch it with run_in_background; it takes about an hour. Report ticks/s and wall clock.
2. Report the 10-episode-bucket table (mean reward, share leaving the house, |w_actor|, |w_critic|, lr) the way the problem statement does, so it can be compared with run 2 directly.
3. Evaluate `brains/latest.npz` (the best) AND the final training state on the held-out seeds 90000-90009, 10 episodes each, learning off, and put both beside v1-2M's 10 of 10 / mean reward 179.5.
4. **Acceptance:** the best brain leaves the house in at least 9 of 10 held-out episodes with mean reward at or above v1-2M's, AND no 20-episode bucket of the new training run has a leave-house share below 0.30 after the first 20 episodes. If the second half fails but the first passes, say so: the best-keeping then makes continued training safe even though the training state still wobbles, and that is worth knowing.
5. Stretch, report only: does the best brain reach Route 1 (map 12), Oak's Lab (40) or set an event flag more often than v1-2M did?

## Definition of done
Tests green (paste), the experiment reported, `brains/latest.npz` left as the best brain and `brains/training.npz` as the training state, README's Train section updated (the two files, the schedule, how to continue training safely), one commit ending `Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>`, no push. Final message is a reviewer's report: what changed, pasted outputs, numbers, deviations with reasons, everything unverified.
