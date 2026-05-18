from rest_framework.pagination import PageNumberPagination


class ReportPageNumberPagination(PageNumberPagination):
    """Admin reports list: 15 per page by default, client may pass page_size."""

    page_size = 15
    page_size_query_param = 'page_size'
    max_page_size = 100
