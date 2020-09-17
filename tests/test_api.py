import itertools as it
from operator import attrgetter
from typing import Any, Callable, Iterator, Mapping, Tuple

import numpy as np
import pytest
from segyio import SegyFile, TraceField
from tiledb.libtiledb import TileDBError

import tilesegy
from tests.conftest import parametrize_tilesegy_segyfiles, parametrize_tilesegys
from tilesegy import StructuredTileSegy, TileSegy


def assert_equal_arrays(a: np.ndarray, b: np.ndarray, reshape: bool = False) -> None:
    assert a.dtype == b.dtype
    if reshape:
        assert a.ndim == b.ndim + 1
        assert a.shape[0] * a.shape[1] == b.shape[0]
        assert a.shape[-2:] == b.shape[-2:]
        b = b.reshape(a.shape)
    else:
        assert a.ndim == b.ndim
        assert a.shape == b.shape
    np.testing.assert_array_equal(a, b)


def segy_gen_to_array(segy_gen: Iterator[np.ndarray]) -> np.ndarray:
    return np.array(list(map(np.copy, segy_gen)))


def stringify_keys(d: Mapping[int, int]) -> Mapping[str, int]:
    return {str(k): v for k, v in d.items()}


def iter_slices(i: int, j: int) -> Iterator[slice]:
    return (slice(*bounds) for bounds in it.product((None, i), (None, j)))


def iter_slice_pairs(i: int, j: int, x: int, y: int) -> Iterator[Tuple[slice, slice]]:
    return it.product(iter_slices(i, j), iter_slices(x, y))


class TestTileSegy:
    @parametrize_tilesegy_segyfiles("t", "s")
    def test_sorting(self, t: TileSegy, s: SegyFile) -> None:
        assert t.sorting == s.sorting

    @parametrize_tilesegy_segyfiles("t", "s")
    def test_bin(self, t: TileSegy, s: SegyFile) -> None:
        assert t.bin == stringify_keys(s.bin)

    @parametrize_tilesegy_segyfiles("t", "s")
    def test_text(self, t: TileSegy, s: SegyFile) -> None:
        assert t.text == list(s.text)

    @parametrize_tilesegy_segyfiles("t", "s")
    def test_samples(self, t: TileSegy, s: SegyFile) -> None:
        assert_equal_arrays(t.samples, s.samples)

    @parametrize_tilesegys("t")
    def test_close(self, t: TileSegy) -> None:
        t.bin
        t.close()
        with pytest.raises(TileDBError):
            t.bin

    @parametrize_tilesegys("t")
    def test_context_manager(self, t: TileSegy) -> None:
        with tilesegy.open(t.uri) as t2:
            t2.bin
        with pytest.raises(TileDBError):
            t2.bin

    @parametrize_tilesegys("t", structured=False)
    def test_repr(self, t: TileSegy) -> None:
        assert repr(t) == f"TileSegy('{str(t.uri)}')"


class TestTileSegyTraces:
    @parametrize_tilesegy_segyfiles("t", "s", structured=False)
    def test_len(self, t: TileSegy, s: SegyFile) -> None:
        assert len(t.trace) == len(s.trace) == s.tracecount

    @parametrize_tilesegy_segyfiles("t", "s", structured=False)
    def test_get_one_trace_all_samples(self, t: TileSegy, s: SegyFile) -> None:
        i = np.random.randint(0, s.tracecount)
        assert_equal_arrays(t.trace[i], s.trace[i])

    @parametrize_tilesegy_segyfiles("t", "s", structured=False)
    def test_get_one_trace_one_sample(self, t: TileSegy, s: SegyFile) -> None:
        i = np.random.randint(0, s.tracecount)
        x = np.random.randint(0, len(s.samples))
        assert t.trace[i, x] == s.trace[i, x]

    @parametrize_tilesegy_segyfiles("t", "s", structured=False)
    def test_get_one_trace_slice_samples(self, t: TileSegy, s: SegyFile) -> None:
        i = np.random.randint(0, s.tracecount)
        x = np.random.randint(0, len(s.samples) // 2)
        y = np.random.randint(x + 1, len(s.samples))
        for sl in iter_slices(x, y):
            assert_equal_arrays(t.trace[i, sl], s.trace[i, sl])

    @parametrize_tilesegy_segyfiles("t", "s", structured=False)
    def test_get_slice_traces_all_samples(self, t: TileSegy, s: SegyFile) -> None:
        i = np.random.randint(0, s.tracecount // 2)
        j = np.random.randint(i + 1, s.tracecount)
        for sl in iter_slices(i, j):
            assert_equal_arrays(t.trace[sl], segy_gen_to_array(s.trace[sl]))

    @parametrize_tilesegy_segyfiles("t", "s", structured=False)
    def test_get_slice_traces_one_sample(self, t: TileSegy, s: SegyFile) -> None:
        i = np.random.randint(0, s.tracecount // 2)
        j = np.random.randint(i + 1, s.tracecount)
        x = np.random.randint(0, len(s.samples))
        for sl in iter_slices(i, j):
            assert_equal_arrays(t.trace[sl, x], np.fromiter(s.trace[sl, x], s.dtype))

    @parametrize_tilesegy_segyfiles("t", "s", structured=False)
    def test_get_slice_traces_slice_samples(self, t: TileSegy, s: SegyFile) -> None:
        i = np.random.randint(0, s.tracecount // 2)
        j = np.random.randint(i + 1, s.tracecount)
        x = np.random.randint(0, len(s.samples) // 2)
        y = np.random.randint(x + 1, len(s.samples))
        for sl1, sl2 in iter_slice_pairs(i, j, x, y):
            assert_equal_arrays(t.trace[sl1, sl2], segy_gen_to_array(s.trace[sl1, sl2]))

    @parametrize_tilesegy_segyfiles("t", "s", structured=False)
    def test_headers(self, t: TileSegy, s: SegyFile) -> None:
        i = np.random.randint(0, s.tracecount // 2)
        j = i + 20
        assert len(t.trace.headers) == len(s.header)
        assert t.trace.headers[i] == stringify_keys(s.header[i])
        assert t.trace.headers[i:j] == list(map(stringify_keys, s.header[i:j]))

    @parametrize_tilesegy_segyfiles("t", "s", structured=False)
    def test_header(self, t: TileSegy, s: SegyFile) -> None:
        str_attr = "TraceNumber"
        t_attrs = t.trace.header(str_attr)
        s_attrs = s.attributes(getattr(TraceField, str_attr))

        i = np.random.randint(0, s.tracecount // 2)
        j = np.random.randint(i + 1, s.tracecount)
        assert len(t_attrs) == len(s_attrs)
        assert t_attrs[i] == s_attrs[i]
        for sl in iter_slices(i, j):
            assert t_attrs[sl] == s_attrs[sl].tolist()


class TestStructuredTileSegy:
    @parametrize_tilesegys("t", structured=True)
    def test_repr(self, t: StructuredTileSegy) -> None:
        assert repr(t) == f"StructuredTileSegy('{str(t.uri)}')"

    @parametrize_tilesegy_segyfiles("t", "s", structured=True)
    def test_offsets(self, t: StructuredTileSegy, s: SegyFile) -> None:
        assert_equal_arrays(t.offsets, s.offsets)

    @parametrize_tilesegy_segyfiles("t", "s", structured=True)
    def test_fast(self, t: StructuredTileSegy, s: SegyFile) -> None:
        if s.fast is s.iline:
            assert str(t.fast) == "Lines('ilines')"
        else:
            assert s.fast is s.xline
            assert str(t.fast) == "Lines('xlines')"


def parametrize_line_getters(line_getter_name: str, lines_getter_name: str) -> Any:
    argnames = (line_getter_name, lines_getter_name)
    argvalues = [
        (attrgetter("iline"), attrgetter("ilines")),
        (attrgetter("xline"), attrgetter("xlines")),
    ]
    return pytest.mark.parametrize(argnames, argvalues, ids=["ilines", "xlines"])


class TestStructuredTileSegyLines:
    @pytest.mark.parametrize("lines", ["ilines", "xlines"])
    @parametrize_tilesegy_segyfiles("t", "s", structured=True)
    def test_lines(self, lines: str, t: StructuredTileSegy, s: SegyFile) -> None:
        assert_equal_arrays(getattr(t, lines), getattr(s, lines))

    @pytest.mark.parametrize("line", ["iline", "xline"])
    @parametrize_tilesegy_segyfiles("t", "s", structured=True)
    def test_len(self, line: str, t: StructuredTileSegy, s: SegyFile) -> None:
        assert len(getattr(t, line)) == len(getattr(s, line))

    @parametrize_line_getters("get_line", "get_lines")
    @parametrize_tilesegy_segyfiles("t", "s", structured=True)
    def test_get_one_line_one_offset(
        self,
        get_line: Callable[[Any], Any],
        get_lines: Callable[[Any], np.ndarray],
        t: StructuredTileSegy,
        s: SegyFile,
    ) -> None:
        i = np.random.choice(get_lines(s))
        x = np.random.choice(s.offsets)
        assert_equal_arrays(get_line(t)[i], get_line(s)[i])
        assert_equal_arrays(get_line(t)[i, x], get_line(s)[i, x])

    @parametrize_line_getters("get_line", "get_lines")
    @parametrize_tilesegy_segyfiles("t", "s", structured=True)
    def test_get_one_line_slice_offsets(
        self,
        get_line: Callable[[Any], Any],
        get_lines: Callable[[Any], np.ndarray],
        t: StructuredTileSegy,
        s: SegyFile,
    ) -> None:
        if len(s.offsets) == 1:
            pytest.skip("single offset segy")

        i = np.random.choice(get_lines(s))
        x, y = s.offsets[1], s.offsets[3]
        for sl in iter_slices(x, y):
            assert_equal_arrays(
                get_line(t)[i, sl], segy_gen_to_array(get_line(s)[i, sl])
            )

    @parametrize_line_getters("get_line", "get_lines")
    @parametrize_tilesegy_segyfiles("t", "s", structured=True)
    def test_get_slice_lines_one_offset(
        self,
        get_line: Callable[[Any], Any],
        get_lines: Callable[[Any], np.ndarray],
        t: StructuredTileSegy,
        s: SegyFile,
    ) -> None:
        i, j = np.sort(np.random.choice(get_lines(s), 2, replace=False))
        x = np.random.choice(s.offsets)
        for sl in iter_slices(i, j):
            assert_equal_arrays(get_line(t)[sl], segy_gen_to_array(get_line(s)[sl]))
            assert_equal_arrays(
                get_line(t)[sl, x], segy_gen_to_array(get_line(s)[sl, x])
            )

    @parametrize_line_getters("get_line", "get_lines")
    @parametrize_tilesegy_segyfiles("t", "s", structured=True)
    def test_get_slice_lines_slice_offsets(
        self,
        get_line: Callable[[Any], Any],
        get_lines: Callable[[Any], np.ndarray],
        t: StructuredTileSegy,
        s: SegyFile,
    ) -> None:
        if len(s.offsets) == 1:
            pytest.skip("single offset segy")

        i, j = np.sort(np.random.choice(get_lines(s), 2, replace=False))
        x, y = s.offsets[1], s.offsets[3]
        for sl1, sl2 in iter_slice_pairs(i, j, x, y):
            assert_equal_arrays(
                get_line(t)[sl1, sl2],
                segy_gen_to_array(get_line(s)[sl1, sl2]),
                reshape=True,
            )


class TestStructuredTileSegyDepths:
    @parametrize_tilesegy_segyfiles("t", "s", structured=True)
    def test_len(self, t: StructuredTileSegy, s: SegyFile) -> None:
        assert len(t.depth) == len(s.depth_slice)

    @parametrize_tilesegy_segyfiles("t", "s", structured=True)
    def test_get_one_line(self, t: StructuredTileSegy, s: SegyFile) -> None:
        i = np.random.randint(0, len(s.samples))
        assert_equal_arrays(t.depth[i], s.depth_slice[i])

    @parametrize_tilesegy_segyfiles("t", "s", structured=True)
    def test_get_slice_lines(self, t: StructuredTileSegy, s: SegyFile) -> None:
        i = np.random.randint(0, len(s.samples) // 2)
        j = np.random.randint(i + 1, len(s.samples))
        for sl in iter_slices(i, j):
            assert_equal_arrays(t.depth[sl], segy_gen_to_array(s.depth_slice[sl]))
