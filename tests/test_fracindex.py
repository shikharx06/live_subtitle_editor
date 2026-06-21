from app import fracindex


def test_between_empty():
    k = fracindex.between(None, None)
    assert k > ""


def test_between_appends_ordered():
    keys = []
    prev = None
    for _ in range(50):
        k = fracindex.between(prev, None)
        keys.append(k)
        prev = k
    assert keys == sorted(keys)
    assert len(set(keys)) == len(keys)


def test_between_two_neighbors():
    lo = fracindex.between(None, None)
    hi = fracindex.between(lo, None)
    mid = fracindex.between(lo, hi)
    assert lo < mid < hi


def test_repeated_inserts_between_same_pair():
    lo = "a"
    hi = "b"
    prev = lo
    for _ in range(30):
        mid = fracindex.between(prev, hi)
        assert prev < mid < hi
        prev = mid


def test_adjacent_digits_descend():
    lo = "a"
    hi = "b"
    mid = fracindex.between(lo, hi)
    assert lo < mid < hi
    assert mid.startswith("a")
