class BrokeJError(Exception):
    code = "brokej_error"


class InvalidDocumentError(BrokeJError):
    code = "invalid_document"


class ConnectorError(BrokeJError):
    code = "connector_error"


class ConnectorSchemaError(ConnectorError):
    code = "connector_schema_error"


class GitHubRateLimitError(ConnectorError):
    code = "github_rate_limit"


class SourceBusyError(BrokeJError):
    code = "source_busy"


class NotFoundError(BrokeJError):
    code = "not_found"
