from abc import ABC, abstractmethod
from typing import Any, Dict, List, Tuple, Union, cast

import numpy as np
import tiledb

from ._singledispatchmethod import singledispatchmethod  # type: ignore

Index = Union[int, slice]


class Indexable(ABC):
    @abstractmethod
    def __len__(self) -> int:
        ...  # pragma: nocover

    @abstractmethod
    def __getitem__(self, i: Index) -> Any:
        ...  # pragma: nocover


class Header(Indexable):
    def __init__(self, tdb: tiledb.Array):
        self._tdb = tdb

    def __len__(self) -> int:
        return len(self._tdb)

    @singledispatchmethod
    def __getitem__(self, i: object) -> None:
        raise NotImplementedError(f"Cannot index by {i.__class__}")  # pragma: nocover

    @__getitem__.register(int)
    def _get_one(self, i: int) -> int:
        return cast(int, self._tdb[i].item())

    @__getitem__.register(slice)
    def _get_many(self, i: slice) -> List[int]:
        return cast(List[int], self._tdb[i].tolist())


class Headers(Indexable):
    def __init__(self, tdb: tiledb.Array):
        self._tdb = tdb

    def __len__(self) -> int:
        return len(self._tdb)

    @singledispatchmethod
    def __getitem__(self, i: object) -> None:
        raise NotImplementedError(f"Cannot index by {i.__class__}")  # pragma: nocover

    @__getitem__.register(int)
    def _get_one(self, i: int) -> Dict[str, int]:
        return cast(Dict[str, int], self._tdb[i])

    @__getitem__.register(slice)
    def _get_many(self, i: slice) -> List[Dict[str, int]]:
        headers = self._tdb[i]
        keys = headers.keys()
        columns = [v.tolist() for v in headers.values()]
        return [dict(zip(keys, row)) for row in zip(*columns)]


class TraceDepth(Indexable):
    def __init__(self, tdb: tiledb.Array):
        self._tdb = tdb

    def __len__(self) -> int:
        return cast(int, self._tdb.shape[1])

    def __getitem__(self, i: Index) -> np.ndarray:
        data = self._tdb[:, i]
        return data.swapaxes(0, 1) if data.ndim == 2 else data


class Traces(Indexable):
    def __init__(self, data: tiledb.Array, headers: tiledb.Array):
        self._data = data
        self._headers = headers

    def __len__(self) -> int:
        return cast(int, self._data.shape[0])

    def __getitem__(
        self, i: Union[Index, Tuple[Index, Index]]
    ) -> Union[np.number, np.ndarray]:
        return self._data[i]

    @property
    def headers(self) -> Headers:
        return Headers(self._headers)

    def header(self, name: str) -> Header:
        return Header(tiledb.DenseArray(self._headers.uri, attr=name))


class Lines(Indexable):
    def __init__(
        self,
        dim_name: str,
        labels: np.ndarray,
        offsets: np.ndarray,
        data: tiledb.Array,
        headers: tiledb.Array,
    ):
        self._dim_name = dim_name
        self._label_indexer = LabelIndexer(labels)
        self._offset_indexer = LabelIndexer(offsets)
        self._default_offset = offsets[0]
        self._data = data
        self._headers = headers

    def __str__(self) -> str:
        return f"Lines({self._dim_name!r})"

    def __len__(self) -> int:
        return cast(int, self._data.shape[self._labels_axis])

    def __getitem__(self, i: Union[Index, Tuple[Index, Index]]) -> np.ndarray:
        if isinstance(i, tuple):
            labels, offsets = i
        else:
            labels, offsets = i, self._default_offset

        label_indices = self._label_indexer[labels]
        multi_labels = isinstance(label_indices, slice)
        offset_indices = self._offset_indexer[offsets]
        multi_offsets = isinstance(offset_indices, slice)

        labels_axis = self._labels_axis
        offsets_axis = self._offsets_axis
        composite_index: List[Index] = [slice(None)] * 4
        composite_index[labels_axis] = label_indices
        composite_index[offsets_axis] = offset_indices
        data = self._data[tuple(composite_index)]

        # TODO: Simplify and/or comment the swap axes logic
        if multi_labels and multi_offsets:
            major_axis = labels_axis
        elif multi_labels:
            major_axis = labels_axis - int(labels_axis > offsets_axis)
        elif multi_offsets:
            major_axis = offsets_axis - int(offsets_axis > labels_axis)
        else:
            major_axis = 0

        if major_axis > 0:
            data = data.swapaxes(0, major_axis)

        # for multiple depths need to do an extra swap: (slow, fast) -> (fast, slow)
        if self._dim_name == "samples" and multi_labels:
            data = data.swapaxes(-1, -2)

        return data

    _offsets_axis = property(lambda self: 1)
    _labels_axis = property(
        lambda self: next(
            i
            for i, dim in enumerate(self._data.schema.domain)
            if dim.name == self._dim_name
        )
    )


class LabelIndexer:
    def __init__(self, labels: np.ndarray):
        if not issubclass(labels.dtype.type, np.integer):
            raise ValueError("labels should be integers")
        if len(np.unique(labels)) != len(labels):
            raise ValueError(f"labels should not contain duplicates: {labels}")
        self._labels = labels
        self._min_label = labels.min()
        self._max_label = labels.max() + 1
        self._sorter = labels.argsort()

    @singledispatchmethod
    def __getitem__(self, label: object) -> int:
        indices = np.flatnonzero(label == self._labels)
        assert indices.size <= 1, indices
        if indices.size == 0:
            raise ValueError(f"{label} is not in labels")
        return int(indices[0])

    @__getitem__.register(slice)
    def _get_slice(self, label_slice: slice) -> slice:
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
        indices = indices[self._labels[indices] == label_range]
        if len(indices) == 0:
            raise ValueError(f"{label_slice} has no overlap with labels")

        start = indices[0]
        step = indices[1] - start if len(indices) > 1 else 1
        stop = indices[-1] + (1 if step > 0 else -1)
        if (np.arange(start, stop, step) != indices).any():
            raise ValueError(
                f"Label indices for {label_slice} is not a slice: {indices}"
            )

        return slice(start, stop, step)
