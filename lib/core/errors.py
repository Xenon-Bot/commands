__all__ = (
    "CoreError",
    "make_core_error"
)


class CoreError(Exception):
    def __init__(self, resp, data):
        self.status = resp.status
        self.code = data["code"]


class NotFoundError(CoreError):
    def __init__(self, resp, data):
        super().__init__(resp, data)
        self.entity = data.get("entity")


class RateLimitError(CoreError):
    pass


specific_errors = {
    "rate_limit": RateLimitError,
    "not_found": NotFoundError
}


def make_core_error(resp, data):
    klass = specific_errors.get(data["code"], CoreError)
    return klass(resp, data)
