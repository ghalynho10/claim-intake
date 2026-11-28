"""Synthetic claim packets with known answers (spec 0003).

Builds each packet from a seed in fixed stages (scenario, plan, render, noise,
derive, verify) so the same seed always gives the same packets, and refuses to
write any packet whose labels fail a check against its final text.
"""
