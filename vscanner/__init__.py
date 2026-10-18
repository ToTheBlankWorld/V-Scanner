# V-Scanner 3.0 — shared engine and service layer (Stage 03).
#
# The engine is UI-framework-free: Textual/Rich/Qt never appear below this
# level. Public surface (stage-scoped):
#   vscanner.core      — models, errors, redaction, paths, knowledge base
#   vscanner.services  — ADB client/discovery/device-info, scanning, reports,
#                        tools provisioning, configuration, doctor, registry

__version__ = "3.0.0a0"
