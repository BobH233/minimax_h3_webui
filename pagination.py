PAGE_SIZE = 10


def page_window(total: int, requested_page: int) -> tuple[int, int, int]:
    total_pages = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)
    page = min(max(1, requested_page), total_pages)
    return page, total_pages, (page - 1) * PAGE_SIZE
