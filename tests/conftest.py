import itertools as it
from pathlib import Path
from typing import Any, Callable, Iterator, Optional

import pytest
import segyio
import tiledb
from segyio import SegyFile, TraceSortingFormat

from tilesegy.create import segy_to_tiledb

from .segyio_utils import generate_structured_segy, generate_unstructured_segy

FIXTURES_DIR = Path(__file__).parent / "fixtures"
FIXTURES_DIR.mkdir(exist_ok=True)

UNSTRUCTURED_SEGY_COMBOS = {
    "sorting": [TraceSortingFormat.UNKNOWN_SORTING],
    "traces": [6300],
    "samples": [10],
}
STRUCTURED_SEGY_COMBOS = {
    "sorting": [
        TraceSortingFormat.CROSSLINE_SORTING,
        TraceSortingFormat.INLINE_SORTING,
    ],
    "ilines": [70],
    "xlines": [90],
    "offsets": [1, 2],
    "samples": [10],
}


def iter_segyfiles(structured: bool) -> Iterator[SegyFile]:
    generate_segy: Callable[..., None]
    if structured:
        combos = STRUCTURED_SEGY_COMBOS
        generate_segy = generate_structured_segy
    else:
        combos = UNSTRUCTURED_SEGY_COMBOS
        generate_segy = generate_unstructured_segy
    keys = combos.keys()
    for values in it.product(*combos.values()):
        kwargs = dict(zip(keys, values))
        filename = "-".join("{}={}".format(*item) for item in kwargs.items()) + ".sgy"
        path = FIXTURES_DIR / filename
        if not path.exists():
            generate_segy(path, **kwargs)
        yield segyio.open(path, ignore_geometry=not structured)


def tilesegy(segy_file: SegyFile) -> Path:
    path = Path(segy_file._filename).with_suffix(".tdb")
    if not path.exists():
        segy_to_tiledb(
            segy_file,
            str(path),
            tile_size=1024 ** 2,
            config=tiledb.Config({"sm.consolidation.buffer_size": 500000}),
        )
    return path


def parametrize_segys(
    segyfile_name: str, tilesegy_name: str, structured: Optional[bool] = None
) -> Any:
    segy_files: Iterator[SegyFile]
    if structured is None:
        segy_files = it.chain(iter_segyfiles(False), iter_segyfiles(True))
    else:
        segy_files = iter_segyfiles(structured)
    return pytest.mark.parametrize(
        (segyfile_name, tilesegy_name),
        ((segy_file, tilesegy(segy_file)) for segy_file in segy_files),
        ids=lambda s: Path(s._filename).stem if isinstance(s, SegyFile) else "sgy",
    )