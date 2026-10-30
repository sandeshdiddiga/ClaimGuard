"""A connection that fails on any query, to prove a CPT-shaped code is never looked up."""


class NoQueries:
    def execute(self, *args, **kwargs):
        raise AssertionError("a query ran for a code that must never be looked up")
