"""Datasets on disk must load back exactly as generated."""

import json

import pandas as pd

from synth.build import load_world, write_world
from synth.world import generate_world


def test_world_round_trips_through_csv(tmp_path):
    world = generate_world(seed=3, n_ngos=30, n_projects=60)
    write_world(world, tmp_path)
    loaded = load_world(tmp_path)
    pd.testing.assert_frame_equal(loaded.ngos, world.ngos)
    pd.testing.assert_frame_equal(loaded.projects, world.projects)
    pd.testing.assert_frame_equal(loaded.spending, world.spending)


def test_list_columns_are_stored_as_json(tmp_path):
    # Python repr ("['a', 'b']") would load fine here but break any other
    # consumer -- SQL COPY, a notebook, the API -- that expects JSON.
    write_world(generate_world(seed=3, n_ngos=30, n_projects=60), tmp_path)
    raw = pd.read_csv(tmp_path / "projects.csv")
    for col in ("activities", "sdgs", "budget_lines"):
        json.loads(raw.loc[0, col])
