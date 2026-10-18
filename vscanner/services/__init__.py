# V-Scanner 3.0 — services package.
#
# Each service implements one SC-xx contract from SERVICE_CONTRACTS.md with
# an injectable ADB transport (see services/adb/client.AdbClientProtocol).
# ServiceRegistry composes them lazily in services/registry.py.
