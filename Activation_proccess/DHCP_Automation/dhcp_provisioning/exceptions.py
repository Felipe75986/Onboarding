class DhcpError(Exception):
    pass


class ConfigError(DhcpError):
    pass


class MacCollectionError(DhcpError):
    pass


class DhcpApplyError(DhcpError):
    pass
