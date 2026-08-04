from pagination import PAGE_SIZE, page_window


def test_page_window_clamps_and_offsets() -> None:
    assert page_window(0, 99) == (1, 1, 0)
    assert page_window(PAGE_SIZE, 1) == (1, 1, 0)
    assert page_window(PAGE_SIZE + 1, 2) == (2, 2, PAGE_SIZE)
    assert page_window(25, 99) == (3, 3, PAGE_SIZE * 2)
