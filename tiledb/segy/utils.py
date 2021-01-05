import itertools as it
from functools import singledispatch
from typing import TYPE_CHECKING, List, Tuple, TypeVar, Union

import numpy as np
import wrapt

from .singledispatchmethod import singledispatchmethod  # type: ignore

# https://github.com/python/typing/issues/684#issuecomment-548203158
if TYPE_CHECKING:  # pragma: nocover
    from enum import Enum

    class ellipsis(Enum):
        Ellipsis = "..."

    Ellipsis = ellipsis.Ellipsis
else:
    ellipsis = type(Ellipsis)


Int = Union[int, np.integer]
Index = Union[Int, slice]
T = TypeVar("T")


class TiledbArrayWrapper(wrapt.ObjectProxy):
    """
    TileDB array wrapper that provides standard python/numpy semantics for
    indexing slices with negative step.
    """

    def __getitem__(self, i: Union[ellipsis, Index, Tuple[Index, ...]]) -> np.ndarray:
        return self.__wrapped__[self._normalize_index(i)]

    @singledispatchmethod
    def _normalize_index(self, i: T) -> T:
        return i

    @_normalize_index.register(slice)
    def _normalize_slice(self, s: slice) -> slice:
        if s.step is None or s.step > 0 or s.start is s.stop is None:
            return s
        start = s.stop + 1 if s.stop is not None else None
        stop = s.start + 1 if s.start is not None else None
        return slice(start, stop, s.step)

    @_normalize_index.register(tuple)
    def _normalize_tuple(self, t: Tuple[Index, ...]) -> Tuple[Index, ...]:
        return tuple(map(self._normalize_index, t))


class TraceIndexer:
    def __init__(self, shape: Tuple[int, ...]):
        self._shape = shape

    def __len__(self) -> int:
        return int(np.asarray(self._shape).prod())

    def __getitem__(
        self, trace_index: Index
    ) -> Tuple[Tuple[Index, ...], Union[int, List[int], ellipsis]]:
        """
        Given a trace index, return a `(bounding_box, post_reshape_indices)` tuple where:
        - `bounding_box` is a tuple of (int or slice) indices for each dimension in shape that
          enclose all data of the requested `trace_index`.
        - `post_reshape_indices` is a list of indices to select from the reshaped 1-dimensional
          bounding box in order to get the requested `trace_index` data. It may also be ellipsis
          (...) if the whole bounding box is to be selected.
        """
        return (trace_index,), Ellipsis


class StructuredTraceIndexer(TraceIndexer):
    @singledispatchmethod
    def __getitem__(self, i: object) -> None:
        raise TypeError(f"Cannot index by {i.__class__}")

    @__getitem__.register(int)
    @__getitem__.register(np.integer)
    def _get_one(self, trace_index: Int) -> Tuple[Tuple[int, ...], ellipsis]:
        return np.unravel_index(trace_index, self._shape), Ellipsis

    @__getitem__.register(slice)
    def _get_many(self, trace_index: slice) -> Tuple[Tuple[slice, ...], List[int]]:
        # get indices in 1D (trace index) and 3D (fast-slow-offset indices)
        raveled_indices = np.arange(len(self))[trace_index]
        unraveled_indices = np.unravel_index(raveled_indices, self._shape)
        unique_unraveled_indices = tuple(map(np.unique, unraveled_indices))
        bounding_box = tuple(map(ensure_slice, unique_unraveled_indices))

        # find the requested subset of indices from the cartesian product
        points = frozenset(zip(*unraveled_indices))
        post_reshape_indices = [
            i
            for i, point in enumerate(it.product(*unique_unraveled_indices))
            if point in points
        ]
        return bounding_box, post_reshape_indices


class LabelIndexer:
    def __init__(self, labels: np.ndarray):
        if not issubclass(labels.dtype.type, np.integer):
            raise ValueError("labels should be integers")
        if len(np.unique(labels)) != len(labels):
            raise ValueError(f"labels should not contain duplicates: {labels}")
        self._labels = labels
        self._min_label = int(labels.min())
        self._max_label = int(labels.max() + 1)
        self._sorter = labels.argsort()

    @singledispatchmethod
    def __getitem__(self, i: object) -> None:
        raise TypeError(f"Cannot index by {i.__class__}")

    @__getitem__.register(int)
    @__getitem__.register(np.integer)
    def _get_one(self, label: Int) -> int:
        indices = np.flatnonzero(label == self._labels)
        assert indices.size <= 1, indices
        if indices.size == 0:
            raise ValueError(f"{label} is not in labels")
        return int(indices[0])

    @__getitem__.register(slice)
    def _get_many(self, label_slice: slice) -> slice:
        return ensure_slice(self._label_slice_to_indices(label_slice))

    def _label_slice_to_indices(self, label_slice: slice) -> np.ndarray:
        start, stop, step = label_slice.start, label_slice.stop, label_slice.step
        min_label = self._min_label
        if step is None or step > 0:  # increasing step
            if start is None or start < min_label:
                start = min_label
        else:  # decreasing step
            if stop is None or stop < min_label - 1:
                stop = min_label - 1

        label_range = np.arange(*slice(start, stop, step).indices(self._max_label))
        indices = self._sorter[
            self._labels.searchsorted(label_range, sorter=self._sorter)
        ]
        return indices[self._labels[indices] == label_range]


class MultiSliceError(ValueError):
    pass


@singledispatch
def ensure_slice(obj: object) -> slice:
    raise TypeError(f"Cannot convert {obj.__class__} to slice")


@ensure_slice.register(slice)
def _ensure_slice_slice(s: slice) -> slice:
    return s


@ensure_slice.register(int)
@ensure_slice.register(np.integer)
def _ensure_slice_int(i: Int) -> slice:
    return slice(i, i + 1)


@ensure_slice.register(np.ndarray)
def _ensure_slice_array(a: np.ndarray) -> slice:
    if not issubclass(a.dtype.type, np.integer):
        raise ValueError("Non-integer array cannot be converted to slice")
    if a.ndim > 1:
        raise ValueError(f"{a.ndim}D array cannot be converted to slice")
    if a.ndim == 1 and len(a) == 0:
        raise ValueError("Empty array cannot be converted to slice")
    if a.ndim == 0 or len(a) == 1:
        return ensure_slice(a.item())

    diffs = a[1:] - a[:-1]
    if not (np.all(diffs > 0) or np.all(diffs < 0)):
        raise ValueError(
            "Non-monotonically increasing or decreasing array cannot be converted to slice"
        )
    unique_diffs = np.unique(diffs)
    if len(unique_diffs) > 1:
        raise MultiSliceError("Array is not convertible to a single range")

    start = a[0]
    step = unique_diffs[0]
    stop = a[-1] + (1 if step > 0 else -1)
    return slice(start, stop, step)
