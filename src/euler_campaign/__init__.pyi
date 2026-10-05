"""Staged design for the new Euler signature campaign.

Base data records, pure Q-prime calculation, and physical geometry are implemented.
Profile records, Deere-direct borehole sampling, and Priest-Hudson face sampling
are implemented. Vertical faces average the x/y scanline RQDs.
Round-length policy, tunnel progression, profile comparison, profile coverage,
and Bounded Euler signature updates, multi-start orchestration, and durable
revision/generation persistence are implemented. The repository-root
``run_euler_campaign.py`` command connects a CampaignProject to the required
MLX-GPU simulator and SQLite store; actual GPU smoke/resume verification remains
required before an operational campaign is considered verified.
Existing legacy campaign files remain unchanged.
"""
