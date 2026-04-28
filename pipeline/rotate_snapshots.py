#!/usr/bin/env python3
"""Keep only the last 7 dated LLM snapshots."""
import glob, os
snapshots = sorted(glob.glob('data/llm_snapshot_*.json'))
for f in snapshots[:-7]:
    os.remove(f)
    print(f'  Removed {f}')
print(f'  Kept {min(7, len(snapshots))} snapshots')
