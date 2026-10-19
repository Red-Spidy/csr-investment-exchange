"""Write the synthetic world to CSV and load it back.

    make datasets          # writes ml/datasets/{ngos,projects,spending}.csv

List-valued columns are stored as JSON so any consumer -- SQL, a notebook,
the API -- can read them, not just this module.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from synth.world import World, generate_world

JSON_COLUMNS = {"projects": ("activities", "sdgs", "budget_lines")}
TABLES = ("ngos", "projects", "spending")


def write_world(world: World, out_dir: Path) -> None:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    for table in TABLES:
        frame = getattr(world, table).copy()
        for col in JSON_COLUMNS.get(table, ()):
            frame[col] = frame[col].apply(json.dumps)
        frame.to_csv(out_dir / f"{table}.csv", index=False)


def load_world(out_dir: Path) -> World:
    out_dir = Path(out_dir)
    frames = {}
    for table in TABLES:
        frame = pd.read_csv(out_dir / f"{table}.csv")
        for col in JSON_COLUMNS.get(table, ()):
            frame[col] = frame[col].apply(json.loads)
        frames[table] = frame
    return World(**frames)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--out", type=Path, default=Path("ml/datasets"))
    args = parser.parse_args()

    world = generate_world(seed=args.seed)
    write_world(world, args.out)
    for table in TABLES:
        print(f"{args.out / (table + '.csv')}: {len(getattr(world, table))} rows")


if __name__ == "__main__":
    main()
